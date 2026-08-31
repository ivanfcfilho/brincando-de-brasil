#!/usr/bin/env python3
"""A pergunta da educação, respondida a partir do banco.

    CEP → município → como está a escola daqui, e quem responde por ela.

O achado que organiza esta camada não é estatístico, é cívico: **a rede de
ensino diz qual político responde pela escola.** Os anos iniciais são quase
todos municipais (prefeito e vereadores); o ensino médio é quase todo
estadual (governador e deputados estaduais). Boa parte das pessoas cobra o
político errado — e cobrar o errado é o mesmo que não cobrar.

A segunda coisa que esta camada expõe é a fórmula. O Ideb é divulgado como um
número só, e um número só esconde a pergunta:

    ideb = nota × fluxo

`nota` é quanto os alunos acertaram no Saeb (0 a 10); `fluxo` é a fração que
passou de ano (0 a 1). Confirmado nos dados: em 34.339 medições de 2023 a
identidade fecha, com erro médio 0,0000 (o máximo de 0,1 é arredondamento).
Duas cidades com o mesmo Ideb podem ter chegado lá por caminhos opostos — uma
ensinando mais, outra aprovando mais. Mostrar as duas parcelas é o que
transforma um número em entendimento.

A regra editorial do projeto vale aqui igual: esta camada publica o valor, a
meta que o próprio governo assinou e a comparação. Ela não diz "o prefeito
fracassou" — Ideb baixo tem muita causa, e a maior delas é a renda da
família, não a prefeitura. A conclusão é de quem lê.

Uso:
    python3.13 pipeline/educacao.py --cep 49010-000
    python3.13 pipeline/educacao.py --municipio ARACAJU --uf SE
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
from consulta import municipio_por_cep, proveniencia, resolver_municipio

# Para cada etapa, a rede que responde pela maior parte das matrículas e
# quem, na estrutura federativa, responde por ela. É a tradução do dado para
# a pergunta que a pessoa realmente tem: "reclamo com quem?"
ETAPAS = [
    {"id": "anos_iniciais", "titulo": "Do 1º ao 5º ano",
     "rede": "Municipal", "responsavel": "a prefeitura",
     "cobra": "prefeito(a) e vereadores",
     "explica": "Quase toda cidade do país tem rede municipal nesta etapa: "
                "é a escola que a prefeitura administra."},
    {"id": "anos_finais", "titulo": "Do 6º ao 9º ano",
     "rede": "Municipal", "responsavel": "a prefeitura",
     "cobra": "prefeito(a) e vereadores",
     "explica": "Aqui a divisão varia de cidade para cidade: parte é da "
                "prefeitura, parte do governo do estado."},
    {"id": "ensino_medio", "titulo": "Ensino médio",
     "rede": "Estadual", "responsavel": "o governo do estado",
     "cobra": "governador(a) e deputados estaduais",
     "explica": "O ensino médio é quase todo do estado — a prefeitura "
                "normalmente não administra essas escolas."},
]

# O INEP publica a página de resultados por município; é para lá que cada
# número desta camada aponta.
URL_INEP = "https://www.gov.br/inep/pt-br/areas-de-atuacao/pesquisas-estatisticas-e-indicadores/ideb"


def _linha_atual(con, cod_ibge, etapa, rede):
    """A medição mais recente COM valor. Não se fixa 2023: rede pequena pode
    não ter sido divulgada no último ciclo, e fixar o ano devolveria vazio
    justamente para o município menor."""
    return bd.um(con, """
        SELECT ano, ideb, nota, fluxo, meta
        FROM ideb
        WHERE cod_ibge=%s AND etapa=%s AND rede=%s AND ideb IS NOT NULL
        ORDER BY ano DESC LIMIT 1
    """, (cod_ibge, etapa, rede))


def _serie(con, cod_ibge, etapa, rede):
    with con.cursor() as cur:
        cur.execute("""
            SELECT ano, ideb, meta FROM ideb
            WHERE cod_ibge=%s AND etapa=%s AND rede=%s AND ideb IS NOT NULL
            ORDER BY ano
        """, (cod_ibge, etapa, rede))
        return [dict(r) for r in cur.fetchall()]


def _ultima_meta(con, cod_ibge, etapa, rede):
    """O último ano em que havia meta, e o que o município fez naquele ano.

    O INEP projetou metas até 2021 e não publicou projeção para 2023 — por
    isso a medição mais recente vem quase sempre "sem meta". Deixar só isso
    na tela jogaria fora a informação mais cobrável que existe aqui: a meta
    é um compromisso que o poder público assinou, com prazo. Então a página
    mostra a medição atual E o último acerto de contas com uma meta real.
    """
    return bd.um(con, """
        SELECT ano, ideb, meta FROM ideb
        WHERE cod_ibge=%s AND etapa=%s AND rede=%s
          AND ideb IS NOT NULL AND meta IS NOT NULL
        ORDER BY ano DESC LIMIT 1
    """, (cod_ibge, etapa, rede))


def _comparacao(con, cod_ibge, etapa, rede, ano, uf):
    """Onde este município está, entre os do estado e os do país.

    Mediana, não média: a distribuição do Ideb tem cauda, e a mediana é o
    'município do meio' — que é o que a comparação quer dizer em português.
    """
    return dict(bd.um(con, """
        WITH universo AS (
            SELECT i.cod_ibge, i.ideb, m.uf
            FROM ideb i JOIN municipio m ON m.cod_ibge = i.cod_ibge
            WHERE i.etapa=%s AND i.rede=%s AND i.ano=%s AND i.ideb IS NOT NULL
        ), eu AS (SELECT ideb FROM universo WHERE cod_ibge=%s)
        SELECT
          (SELECT ideb FROM eu) AS meu,
          COUNT(*) FILTER (WHERE uf=%s) AS n_uf,
          COUNT(*) AS n_br,
          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY ideb)
                FILTER (WHERE uf=%s)::numeric, 2) AS mediana_uf,
          ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY ideb)::numeric, 2)
                AS mediana_br,
          COUNT(*) FILTER (WHERE uf=%s AND ideb > (SELECT ideb FROM eu)) + 1
                AS posicao_uf
        FROM universo
    """, (etapa, rede, ano, cod_ibge, uf, uf, uf)))


def retrato(con, origem):
    """O retrato da educação do município, etapa por etapa."""
    cod, uf = origem["cod_ibge"], origem["uf"]
    etapas = []
    for e in ETAPAS:
        atual = _linha_atual(con, cod, e["id"], e["rede"])
        if not atual:
            etapas.append({**e, "medido": False})
            continue
        ano = atual["ano"]
        comp = _comparacao(con, cod, e["id"], e["rede"], ano, uf)
        meta = atual["meta"]
        etapas.append({
            **e,
            "medido": True,
            "ano": ano,
            "ideb": atual["ideb"],
            "nota": atual["nota"],
            "fluxo": atual["fluxo"],
            "meta": meta,
            # A meta do Ideb foi projetada até 2021; depois dela o INEP não
            # publica projeção nova. Sem meta, não se inventa comparação.
            "bateu_meta": (None if meta is None else atual["ideb"] >= meta),
            "serie": _serie(con, cod, e["id"], e["rede"]),
            "comparacao": comp,
            "ultima_meta": (lambda u: None if u is None else {
                "ano": u["ano"], "ideb": u["ideb"], "meta": u["meta"],
                "bateu": u["ideb"] >= u["meta"]})(
                    _ultima_meta(con, cod, e["id"], e["rede"])),
        })
    return {"municipio": origem["nome"], "uf": uf, "cod_ibge": cod,
            "etapas": etapas, "fonte_inep": URL_INEP,
            "fontes": proveniencia(con)}


# ------------------------------------------------------------------- impressão

def imprimir(r):
    print(f"\n{r['municipio']}/{r['uf']}  (IBGE {r['cod_ibge']})")
    for e in r["etapas"]:
        print(f"\n── {e['titulo']}  ·  rede {e['rede'].lower()} — {e['responsavel']}")
        if not e["medido"]:
            print("   sem medição divulgada para esta rede neste município")
            continue
        meta = "o INEP não publicou meta para este ano" if e["meta"] is None else (
            f"meta {e['meta']} — {'bateu' if e['bateu_meta'] else 'não bateu'}")
        print(f"   Ideb {e['ideb']} em {e['ano']}   ({meta})")
        u = e["ultima_meta"]
        if u:
            print(f"   última meta com prazo: {u['meta']} para {u['ano']}; "
                  f"fez {u['ideb']} — {'cumpriu' if u['bateu'] else 'não cumpriu'}")
        print(f"   = nota {float(e['nota']):.2f} × fluxo {100*float(e['fluxo']):.1f}% "
              f"de aprovação")
        c = e["comparacao"]
        print(f"   {c['posicao_uf']}º de {c['n_uf']} municípios do {r['uf']}  ·  "
              f"mediana do estado {c['mediana_uf']}  ·  do país {c['mediana_br']}")
        print(f"   quem responde: {e['cobra']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cep")
    ap.add_argument("--municipio")
    ap.add_argument("--uf")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    con = bd.conectar()
    if args.cep:
        nome, uf, bairro, cod = municipio_por_cep(args.cep)
        origem = resolver_municipio(con, cod_ibge=cod, nome=nome, uf=uf)
    elif args.municipio:
        origem = resolver_municipio(con, nome=args.municipio, uf=args.uf)
    else:
        return ap.error("informe --cep ou --municipio/--uf")
    r = retrato(con, origem)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        imprimir(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
