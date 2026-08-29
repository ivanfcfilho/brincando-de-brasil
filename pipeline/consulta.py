#!/usr/bin/env python3
"""A pergunta da plataforma, respondida a partir do banco.

    CEP → município → deputados que tiveram votos aqui → para onde foi a
    emenda deles.

Camada de consulta pura: devolve estruturas de dados, não texto de campanha.
A regra editorial do projeto vale aqui como código, não como recomendação —
esta camada expõe origem do voto, destino da verba, percentual e a fonte de
cada número. Ela não classifica, não adjetiva e não conclui. Emenda para
outro município é legal; a leitura é de quem lê.

Uso:
    python3.13 pipeline/consulta.py --cep 49010-000
    python3.13 pipeline/consulta.py --municipio ARACAJU --uf SE
"""
import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
from nomes import norm

VIACEP = "https://viacep.com.br/ws/{}/json/"
# Cada valor publicado precisa apontar para o documento oficial de origem.
URL_EMENDA = "https://portaldatransparencia.gov.br/emendas/{}"
SEM_MUNICIPIO = ("MULTIPLO", "SEM INFORMACAO")


def municipio_por_cep(cep):
    """CEP → (municipio_norm, uf). Fonte: ViaCEP (base dos Correios).

    O CEP resolve município, não seção eleitoral: é a granularidade honesta
    hoje. Descer a bairro exige a base de seções do TSE (votacao_secao), que
    ainda não está carregada — e prometer bairro sem ela seria inventar.
    """
    digitos = "".join(c for c in cep if c.isdigit())
    if len(digitos) != 8:
        raise ValueError(f"CEP inválido: {cep}")
    req = urllib.request.Request(VIACEP.format(digitos),
                                 headers={"User-Agent": "codigo-de-transicao/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    if d.get("erro"):
        raise ValueError(f"CEP não encontrado: {cep}")
    return norm(d["localidade"]), d["uf"], d.get("bairro") or ""


def deputados_do_municipio(con, municipio, uf, limite=10):
    """Quem recebeu votos neste município, e quanto o município pesou para
    cada um. As duas porcentagens respondem a perguntas diferentes:

      pct_do_municipio — quanto deste município foi para o deputado
      pct_do_deputado  — quanto da votação total do deputado veio daqui
    """
    with con.cursor() as cur:
        cur.execute("""
            WITH aqui AS (
                SELECT v.sq_candidato, v.votos
                FROM voto_municipio v
                WHERE v.uf = %s AND v.municipio_norm = %s
            ), total_municipio AS (
                SELECT SUM(votos) AS t FROM aqui
            )
            SELECT d.sq_candidato, d.nome_urna, d.partido, d.situacao,
                   a.votos,
                   ROUND(100.0 * a.votos / NULLIF((SELECT t FROM total_municipio),0), 2)
                       AS pct_do_municipio,
                   ROUND(100.0 * a.votos / NULLIF(vt.total_votos,0), 2)
                       AS pct_do_deputado,
                   vt.total_votos
            FROM aqui a
            JOIN deputado d ON d.sq_candidato = a.sq_candidato
            JOIN vw_votos_totais vt ON vt.sq_candidato = a.sq_candidato
            WHERE d.situacao LIKE 'ELEITO%%'
            ORDER BY a.votos DESC
            LIMIT %s
        """, (uf, municipio, limite))
        return [dict(r) for r in cur.fetchall()]


def destino_das_emendas(con, sq_candidato, municipio, uf, mandato_inicio=2023):
    """Para onde foi o dinheiro deste deputado, com o município em foco
    destacado. Duas visões, porque elas discordam e a discordância é o achado:

      planejado — 'Localidade de aplicação' declarada no empenho. 70–95% vem
                  como Múltiplo/Sem informação: a opacidade é o dado.
      executado — município do favorecido que efetivamente recebeu. Ressalva:
                  sede do favorecido ≠ local de aplicação (fundos estaduais e
                  fornecedores concentram-se nas capitais).
    """
    out = {}
    with con.cursor() as cur:
        # As quatro classes PARTICIONAM o total: toda linha cai em exatamente
        # uma. Filtros sobrepostos aqui fariam as parcelas somarem mais que o
        # todo — e um percentual acima de 100% no ar é munição contra o projeto.
        cur.execute("""
            SELECT COALESCE(SUM(e.empenhado),0) AS total,
                   COALESCE(SUM(e.empenhado) FILTER (
                       WHERE e.municipio NOT IN %(sem)s
                         AND e.uf = %(uf)s AND e.municipio = %(mun)s), 0) AS neste_municipio,
                   COALESCE(SUM(e.empenhado) FILTER (
                       WHERE e.municipio NOT IN %(sem)s
                         AND e.uf = %(uf)s AND e.municipio <> %(mun)s), 0) AS outros_do_estado,
                   COALESCE(SUM(e.empenhado) FILTER (
                       WHERE e.municipio NOT IN %(sem)s
                         AND e.uf IS NOT NULL AND e.uf <> %(uf)s), 0) AS outros_estados,
                   COALESCE(SUM(e.empenhado) FILTER (
                       WHERE e.municipio IN %(sem)s OR e.municipio IS NULL
                          OR e.uf IS NULL), 0) AS sem_municipio_definido
            FROM vw_emenda_deputado e
            WHERE e.sq_candidato = %(sq)s AND e.ano >= %(ano)s
        """, {"sem": SEM_MUNICIPIO, "uf": uf, "mun": municipio,
              "sq": sq_candidato, "ano": mandato_inicio})
        out["planejado"] = dict(cur.fetchone())

        cur.execute("""
            SELECT COALESCE(SUM(f.valor_recebido),0) AS total,
                   COALESCE(SUM(f.valor_recebido) FILTER (
                       WHERE f.uf_favorecido = %(uf)s
                         AND f.municipio_favorecido = %(mun)s),0) AS neste_municipio,
                   COALESCE(SUM(f.valor_recebido) FILTER (
                       WHERE f.uf_favorecido = %(uf)s
                         AND f.municipio_favorecido <> %(mun)s),0) AS outros_do_estado,
                   COALESCE(SUM(f.valor_recebido) FILTER (
                       WHERE f.uf_favorecido IS NOT NULL
                         AND f.uf_favorecido <> %(uf)s),0) AS outros_estados,
                   -- 4.975 linhas (R$ 378 mi no país) não trazem UF do
                   -- favorecido. Sem classe própria elas sumiriam da conta;
                   -- a opacidade tem que aparecer, não ser absorvida.
                   COALESCE(SUM(f.valor_recebido) FILTER (
                       WHERE f.uf_favorecido IS NULL),0) AS sem_local_definido
            FROM vw_favorecido_deputado f
            WHERE f.sq_candidato = %(sq)s AND f.ano >= %(ano)s
        """, {"uf": uf, "mun": municipio, "sq": sq_candidato, "ano": mandato_inicio})
        out["executado"] = dict(cur.fetchone())

        cur.execute("""
            SELECT f.municipio_favorecido AS municipio, f.uf_favorecido AS uf,
                   SUM(f.valor_recebido) AS valor
            FROM vw_favorecido_deputado f
            WHERE f.sq_candidato = %s AND f.ano >= %s
            GROUP BY 1,2 ORDER BY 3 DESC LIMIT 5
        """, (sq_candidato, mandato_inicio))
        out["maiores_destinos"] = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT e.codigo_emenda, e.ano, e.municipio, e.uf, e.nome_funcao,
                   e.empenhado
            FROM vw_emenda_deputado e
            WHERE e.sq_candidato = %s AND e.ano >= %s AND e.empenhado > 0
            ORDER BY e.empenhado DESC LIMIT 5
        """, (sq_candidato, mandato_inicio))
        out["maiores_emendas"] = [
            dict(r, fonte=URL_EMENDA.format(r["codigo_emenda"])) for r in cur.fetchall()]
    _conferir_fechamento(out)
    return out


def _conferir_fechamento(out):
    """As parcelas têm que somar o total, nas duas visões.

    Verificação barata que impede a classe de erro mais perigosa aqui: uma
    quebra por classes que não fecha vira percentual absurdo na tela, e um
    número visivelmente errado desmoraliza os que estão certos.
    """
    for visao, campos in (("planejado", ("neste_municipio", "outros_do_estado",
                                         "outros_estados", "sem_municipio_definido")),
                          ("executado", ("neste_municipio", "outros_do_estado",
                                         "outros_estados", "sem_local_definido"))):
        d = out[visao]
        soma = sum(d[c] for c in campos)
        if abs(soma - d["total"]) > 0.01:
            raise AssertionError(
                f"{visao}: parcelas somam {soma} mas o total é {d['total']}")


def proveniencia(con):
    """De qual arquivo oficial, baixado quando, veio cada número da resposta."""
    with con.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (fonte_id) fonte_id, baixado_em, publicado_em,
                   sha256, arquivo
            FROM snapshot WHERE ingerido_em IS NOT NULL
            ORDER BY fonte_id, baixado_em DESC
        """)
        return [dict(r) for r in cur.fetchall()]


def responder(con, municipio, uf, bairro="", limite=5, mandato_inicio=2023):
    deps = deputados_do_municipio(con, municipio, uf, limite)
    for d in deps:
        d["emendas"] = destino_das_emendas(con, d["sq_candidato"], municipio, uf,
                                           mandato_inicio)
    return {"municipio": municipio, "uf": uf, "bairro": bairro,
            "deputados": deps, "fontes": proveniencia(con)}


def brl(v):
    return "R$ " + f"{float(v or 0):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def imprimir(r):
    print(f"\n{r['municipio']} / {r['uf']}" + (f" — bairro {r['bairro']}" if r["bairro"] else ""))
    if not r["deputados"]:
        print("  nenhum deputado federal eleito com votos registrados neste município")
        return
    for d in r["deputados"]:
        print(f"\n  {d['nome_urna']} ({d['partido']})")
        print(f"    votos aqui: {d['votos']:,}".replace(",", ".") +
              f"  ·  {d['pct_do_municipio']}% dos votos do município"
              f"  ·  {d['pct_do_deputado']}% da votação total dele")
        p, e = d["emendas"]["planejado"], d["emendas"]["executado"]
        if not p["total"]:
            print("    emendas: nenhuma casada com este parlamentar (ver ressalvas)")
            continue
        print(f"    emendas empenhadas (destino declarado): {brl(p['total'])}")
        print(f"      neste município {brl(p['neste_municipio'])} · "
              f"outros do estado {brl(p['outros_do_estado'])} · "
              f"outros estados {brl(p['outros_estados'])} · "
              f"sem município definido {brl(p['sem_municipio_definido'])}")
        if e["total"]:
            print(f"    valores recebidos (execução): {brl(e['total'])}")
            print(f"      favorecidos neste município {brl(e['neste_municipio'])} · "
                  f"no estado {brl(e['outros_do_estado'])} · "
                  f"outros estados {brl(e['outros_estados'])} · "
                  f"sem local declarado {brl(e['sem_local_definido'])}")
        if d["emendas"]["maiores_destinos"]:
            print("      maiores destinos:", ", ".join(
                f"{m['municipio'].title()}/{m['uf']} {brl(m['valor'])}"
                for m in d["emendas"]["maiores_destinos"][:3]))
    print("\n  fontes:")
    for f in r["fontes"]:
        print(f"    {f['fonte_id']}: {f['arquivo']} "
              f"sha256={f['sha256'][:16]} baixado {f['baixado_em']:%Y-%m-%d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cep")
    ap.add_argument("--municipio")
    ap.add_argument("--uf")
    ap.add_argument("--limite", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.cep:
        municipio, uf, bairro = municipio_por_cep(args.cep)
    elif args.municipio and args.uf:
        municipio, uf, bairro = norm(args.municipio), args.uf.upper(), ""
    else:
        ap.error("informe --cep ou (--municipio e --uf)")

    con = bd.conectar()
    r = responder(con, municipio, uf, bairro, args.limite)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        imprimir(r)


if __name__ == "__main__":
    raise SystemExit(main())
