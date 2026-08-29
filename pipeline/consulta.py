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
from nomes import chave_municipio, norm

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
    # O ViaCEP devolve o código IBGE: com ele o resto da consulta é join por
    # código, sem nenhum casamento por nome no caminho.
    cod = d.get("ibge")
    return (norm(d["localidade"]), d["uf"], d.get("bairro") or "",
            int(cod) if cod and cod.isdigit() else None)


def resolver_municipio(con, cod_ibge=None, nome=None, uf=None):
    """Devolve a linha de `municipio`. Aceita código IBGE (preferido) ou
    nome+UF, casando pela chave tolerante."""
    if cod_ibge:
        r = bd.um(con, "SELECT * FROM municipio WHERE cod_ibge=%s", (cod_ibge,))
        if r:
            return r
    if nome and uf:
        with con.cursor() as cur:
            cur.execute("SELECT * FROM municipio WHERE uf=%s", (uf.upper(),))
            alvo = chave_municipio(nome)
            achados = [r for r in cur.fetchall() if chave_municipio(r["nome"]) == alvo]
        if len(achados) == 1:
            return achados[0]
    raise ValueError(f"município não encontrado: {nome or cod_ibge}/{uf or ''}")


def deputados_do_municipio(con, cod_ibge, limite=10):
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
                JOIN municipio m ON m.cod_tse = v.cod_municipio_tse
                WHERE m.cod_ibge = %s
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
        """, (cod_ibge, limite))
        return [dict(r) for r in cur.fetchall()]


def destino_das_emendas(con, sq_candidato, origem, mandato_inicio=2023):
    """Para onde foi o dinheiro deste deputado, medido a partir de `origem`
    (a linha de `municipio` correspondente ao CEP consultado).

    Duas visões, porque elas discordam e a discordância é o achado:

      planejado — 'Localidade de aplicação' declarada no empenho. A maior
                  parte vem como Múltiplo/Sem informação: a opacidade é o dado.
      executado — município do favorecido que efetivamente recebeu. Ressalva
                  que não pode cair: sede do favorecido ≠ local de aplicação
                  (fundos estaduais e fornecedores concentram-se nas capitais).

    A distância é entre CENTROIDES DE TERRITÓRIO (IBGE), não entre as sedes —
    em município de área grande, a diferença é de dezenas de km.
    """
    uf = origem["uf"]
    par = {"cod": origem["cod_ibge"], "uf": uf, "sq": sq_candidato,
           "ano": mandato_inicio}
    out = {"origem": {"cod_ibge": origem["cod_ibge"], "nome": origem["nome"],
                      "uf": uf}}
    with con.cursor() as cur:
        # As classes PARTICIONAM o total: toda linha cai em exatamente uma.
        # Filtros sobrepostos fariam as parcelas somarem mais que o todo, e
        # percentual acima de 100% no ar é munição contra o projeto.
        # A UF vem SEMPRE da tabela municipio, via cod_ibge — nunca da coluna
        # de texto da CGU. As duas discordam em algumas linhas, e misturá-las
        # colocava a mesma linha em duas classes (as parcelas somavam mais que
        # o total). Uma chave, uma verdade.
        cur.execute("""
            SELECT COALESCE(SUM(e.empenhado),0) AS total,
                   COALESCE(SUM(e.empenhado) FILTER (
                       WHERE e.cod_ibge = %(cod)s),0) AS neste_municipio,
                   COALESCE(SUM(e.empenhado) FILTER (
                       WHERE m.cod_ibge IS NOT NULL AND m.cod_ibge <> %(cod)s
                         AND m.uf = %(uf)s),0) AS outros_do_estado,
                   COALESCE(SUM(e.empenhado) FILTER (
                       WHERE m.cod_ibge IS NOT NULL AND m.uf <> %(uf)s),0) AS outros_estados,
                   COALESCE(SUM(e.empenhado) FILTER (
                       WHERE m.cod_ibge IS NULL),0) AS sem_municipio_definido
            FROM vw_emenda_deputado e
            LEFT JOIN municipio m ON m.cod_ibge = e.cod_ibge
            WHERE e.sq_candidato = %(sq)s AND e.ano >= %(ano)s
        """, par)
        out["planejado"] = dict(cur.fetchone())

        cur.execute("""
            SELECT COALESCE(SUM(f.valor_recebido),0) AS total,
                   COALESCE(SUM(f.valor_recebido) FILTER (
                       WHERE f.cod_ibge_favorecido = %(cod)s),0) AS neste_municipio,
                   COALESCE(SUM(f.valor_recebido) FILTER (
                       WHERE m.cod_ibge IS NOT NULL AND m.cod_ibge <> %(cod)s
                         AND m.uf = %(uf)s),0) AS outros_do_estado,
                   COALESCE(SUM(f.valor_recebido) FILTER (
                       WHERE m.cod_ibge IS NOT NULL AND m.uf <> %(uf)s),0) AS outros_estados,
                   COALESCE(SUM(f.valor_recebido) FILTER (
                       WHERE m.cod_ibge IS NULL),0) AS sem_local_definido
            FROM vw_favorecido_deputado f
            LEFT JOIN municipio m ON m.cod_ibge = f.cod_ibge_favorecido
            WHERE f.sq_candidato = %(sq)s AND f.ano >= %(ano)s
        """, par)
        out["executado"] = dict(cur.fetchone())

        # Distância média ponderada pelo valor: o número da manchete.
        #
        # Agrega por município ANTES de ponderar, e usa o valor LÍQUIDO. A base
        # traz estornos (linhas negativas); filtrar linha a linha por valor > 0
        # inflava o total de um município e fazia a mesma cidade aparecer com
        # dois valores diferentes na mesma tela. Um município é uma linha, e o
        # que ele recebeu é o líquido.
        cte = """
            WITH por_municipio AS (
                SELECT f.cod_ibge_favorecido AS cod,
                       SUM(f.valor_recebido) AS valor
                FROM vw_favorecido_deputado f
                WHERE f.sq_candidato = %(sq)s AND f.ano >= %(ano)s
                  AND f.cod_ibge_favorecido IS NOT NULL
                GROUP BY 1 HAVING SUM(f.valor_recebido) > 0
            ), com_distancia AS (
                SELECT p.valor, m.nome AS municipio, m.uf,
                       earth_distance(ll_to_earth(%(lat)s, %(lon)s),
                                      ll_to_earth(m.lat, m.lon)) / 1000 AS km
                FROM por_municipio p
                JOIN municipio m ON m.cod_ibge = p.cod
                WHERE m.lat IS NOT NULL
            )
        """
        cur.execute(cte + """
            SELECT SUM(valor * km) / NULLIF(SUM(valor),0) AS km_medio,
                   SUM(valor) AS valor_com_local,
                   COALESCE(SUM(valor) FILTER (WHERE km > 100),0) AS valor_acima_100km
            FROM com_distancia
        """, dict(par, lat=origem["lat"], lon=origem["lon"]))
        out["distancia"] = dict(cur.fetchone())

        cur.execute(cte + """
            SELECT municipio, uf, valor, ROUND(km::numeric) AS km
            FROM com_distancia ORDER BY valor DESC LIMIT 5
        """, dict(par, lat=origem["lat"], lon=origem["lon"]))
        out["maiores_destinos"] = [dict(r) for r in cur.fetchall()]

        cur.execute("""
            SELECT codigo_emenda, ano, municipio, uf, nome_funcao, empenhado
            FROM vw_emenda_deputado
            WHERE sq_candidato = %(sq)s AND ano >= %(ano)s AND empenhado > 0
            ORDER BY empenhado DESC LIMIT 5
        """, par)
        out["maiores_emendas"] = [
            dict(r, fonte=URL_EMENDA.format(r["codigo_emenda"])) for r in cur.fetchall()]
    _conferir_fechamento(out)
    _conferir_coerencia(out, origem)
    return out


def _conferir_coerencia(out, origem):
    """O município consultado, quando aparece na lista de maiores destinos,
    tem que trazer o MESMO valor da classe 'neste município'.

    Foi assim que se descobriu que um filtro de valor > 0 excluía estornos de
    um cálculo e não do outro: a mesma cidade aparecia com dois valores na
    mesma tela. Dois números discordando lado a lado custam mais credibilidade
    do que um número faltando.
    """
    for d in out["maiores_destinos"]:
        se_origem = (d["municipio"].upper() == origem["nome"].upper()
                     and d["uf"] == origem["uf"])
        if se_origem and abs(float(d["valor"]) - float(out["executado"]["neste_municipio"])) > 0.01:
            raise AssertionError(
                f"{origem['nome']}: maiores destinos diz {d['valor']} mas a "
                f"classe 'neste município' diz {out['executado']['neste_municipio']}")


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


def responder(con, origem, bairro="", limite=5, mandato_inicio=2023):
    deps = deputados_do_municipio(con, origem["cod_ibge"], limite)
    for d in deps:
        d["emendas"] = destino_das_emendas(con, d["sq_candidato"], origem,
                                           mandato_inicio)
    return {"municipio": origem["nome"], "uf": origem["uf"],
            "cod_ibge": origem["cod_ibge"], "bairro": bairro,
            "deputados": deps, "fontes": proveniencia(con)}


def brl(v):
    return "R$ " + f"{float(v or 0):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def imprimir(r):
    print(f"\n{r['municipio']} / {r['uf']}"
          + (f" — bairro {r['bairro']}" if r["bairro"] else "")
          + f"  [IBGE {r['cod_ibge']}]")
    if not r["deputados"]:
        print("  nenhum deputado federal eleito com votos registrados neste município")
        return
    for d in r["deputados"]:
        print(f"\n  {d['nome_urna']} ({d['partido']})")
        print(f"    votos aqui: {d['votos']:,}".replace(",", ".") +
              f"  ·  {d['pct_do_municipio']}% dos votos do município"
              f"  ·  {d['pct_do_deputado']}% da votação total dele")
        e = d["emendas"]
        p, x, dist = e["planejado"], e["executado"], e["distancia"]
        if not p["total"] and not x["total"]:
            print("    emendas: nenhuma casada com este parlamentar (ver ressalvas)")
            continue
        print(f"    emendas empenhadas (destino declarado): {brl(p['total'])}")
        print(f"      neste município {brl(p['neste_municipio'])} · "
              f"outros do estado {brl(p['outros_do_estado'])} · "
              f"outros estados {brl(p['outros_estados'])} · "
              f"sem município definido {brl(p['sem_municipio_definido'])}")
        if x["total"]:
            print(f"    valores recebidos (execução): {brl(x['total'])}")
            print(f"      favorecidos neste município {brl(x['neste_municipio'])} · "
                  f"no estado {brl(x['outros_do_estado'])} · "
                  f"outros estados {brl(x['outros_estados'])} · "
                  f"sem local declarado {brl(x['sem_local_definido'])}")
        if dist and dist["km_medio"] is not None:
            cobertura = (100 * float(dist["valor_com_local"]) / float(x["total"])
                         if x["total"] else 0)
            acima = float(dist["valor_acima_100km"] or 0)
            print(f"    distância média do dinheiro até aqui: "
                  f"{float(dist['km_medio']):,.0f} km".replace(",", ".") +
                  f" (ponderada por valor, sobre {cobertura:.0f}% do executado "
                  f"que tem município identificado)")
            if dist["valor_com_local"]:
                print(f"      além de 100 km: {brl(acima)} "
                      f"({100*acima/float(dist['valor_com_local']):.0f}% do que tem local)")
        if e["maiores_destinos"]:
            print("      maiores destinos: " + ", ".join(
                f"{m['municipio']}/{m['uf']} {brl(m['valor'])} ({m['km']:.0f} km)"
                for m in e["maiores_destinos"][:3]))
    print("\n  fontes:")
    for f in r["fontes"]:
        print(f"    {f['fonte_id']}: {f['arquivo']} "
              f"sha256={f['sha256'][:16]} baixado {f['baixado_em']:%Y-%m-%d}")
    print("  distâncias entre centroides de território (IBGE), não entre sedes.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cep")
    ap.add_argument("--municipio")
    ap.add_argument("--uf")
    ap.add_argument("--limite", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    con = bd.conectar()
    if args.cep:
        nome, uf, bairro, cod = municipio_por_cep(args.cep)
        origem = resolver_municipio(con, cod_ibge=cod, nome=nome, uf=uf)
    elif args.municipio and args.uf:
        origem, bairro = resolver_municipio(con, nome=args.municipio, uf=args.uf), ""
    else:
        ap.error("informe --cep ou (--municipio e --uf)")

    r = responder(con, origem, bairro, args.limite)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        imprimir(r)


if __name__ == "__main__":
    raise SystemExit(main())
