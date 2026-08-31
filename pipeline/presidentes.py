#!/usr/bin/env python3
"""Quadro comparativo entre os governos, desde 1990.

AVISO QUE VALE MAIS QUE O CÓDIGO
================================
Estes números dizem **o que aconteceu no país durante o mandato**, e não
**o que o presidente causou**. A diferença não é detalhe:

  - preço de commodity, crise mundial e juro dos Estados Unidos entram na
    conta e não passam por Brasília;
  - política pública leva anos para aparecer em indicador — parte do que se
    mede num mandato foi decidida no anterior;
  - Congresso, Banco Central, governadores e prefeitos decidem pedaços
    grandes do que estes números medem.

Por isso esta camada não calcula "nota", não ordena do melhor para o pior e
não escolhe um indicador-síntese. Ela publica a série oficial, o recorte de
anos usado e o link da fonte — e deixa a leitura para quem lê. Montar um
ranking daqui seria o conteúdo mais compartilhável e mais desonesto que este
projeto poderia produzir.

REGRA DE ATRIBUIÇÃO DE ANOS
===========================
Os dados do IBGE são anuais; os mandatos começam e terminam no meio do ano.
Cada ano é atribuído a quem governou a MAIOR PARTE dele. É uma escolha, tem
efeito no resultado, e por isso a página mostra sempre quais anos entraram
em cada coluna.

    python3.13 pipeline/presidentes.py
    python3.13 pipeline/presidentes.py --json
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
from consulta import proveniencia

# Mandatos presidenciais desde 1990. Fatos históricos, digitados da
# Constituição e dos atos de posse — não derivados de dado nenhum, que é o
# que os torna uma referência independente.
#
# `anos` é a aplicação da regra "quem governou a maior parte do ano":
#   1990 Collor toma posse em 15/03  → 9 meses e meio, é dele
#   1992 Collor se afasta em 02/10   → 9 meses, é dele
#   1995 FHC toma posse em 01/01     → ano inteiro
#   2016 Dilma é afastada em 31/08   → 8 meses, é dela
PRESIDENTES = [
    {"id": "collor", "nome": "Fernando Collor", "partido": "PRN",
     "inicio": "1990-03-15", "fim": "1992-10-02", "anos": list(range(1990, 1993)),
     "nota": "Afastado por impeachment em 1992. Governou 2 anos e meio."},
    {"id": "itamar", "nome": "Itamar Franco", "partido": "PMDB",
     "inicio": "1992-10-02", "fim": "1995-01-01", "anos": [1993, 1994],
     "nota": "Assumiu como vice. O Plano Real foi lançado no governo dele, "
             "em julho de 1994."},
    {"id": "fhc", "nome": "Fernando Henrique Cardoso", "partido": "PSDB",
     "inicio": "1995-01-01", "fim": "2003-01-01", "anos": list(range(1995, 2003)),
     "nota": "Dois mandatos."},
    {"id": "lula12", "nome": "Lula (1º e 2º)", "partido": "PT",
     "inicio": "2003-01-01", "fim": "2011-01-01", "anos": list(range(2003, 2011)),
     "nota": "Dois mandatos."},
    {"id": "dilma", "nome": "Dilma Rousseff", "partido": "PT",
     "inicio": "2011-01-01", "fim": "2016-08-31", "anos": list(range(2011, 2017)),
     "nota": "Afastada por impeachment em agosto de 2016."},
    {"id": "temer", "nome": "Michel Temer", "partido": "PMDB",
     "inicio": "2016-08-31", "fim": "2019-01-01", "anos": [2017, 2018],
     "nota": "Assumiu como vice, após o impeachment."},
    {"id": "bolsonaro", "nome": "Jair Bolsonaro", "partido": "PSL/sem partido",
     "inicio": "2019-01-01", "fim": "2023-01-01", "anos": list(range(2019, 2023)),
     "nota": "A pandemia de covid-19 atravessa 2020 e 2021."},
    {"id": "lula3", "nome": "Lula (3º)", "partido": "PT",
     "inicio": "2023-01-01", "fim": None, "anos": list(range(2023, 2026)),
     "nota": "Mandato em curso — os anos de 2026 ainda não fecharam."},
]

# Como cada indicador se resume num período de vários anos. A escolha muda o
# número, então ela é declarada aqui e mostrada na página.
#
#   'media_geometrica' — para TAXA que se acumula (inflação, PIB). A média
#       aritmética de taxas de crescimento é errada: crescer 50% e depois cair
#       50% não dá média zero, dá −13,4% no total.
#   'media'            — para NÍVEL que oscila (desemprego).
#   'inicio_fim'       — para NÍVEL com tendência (mortalidade, expectativa
#       de vida): o que interessa é de quanto para quanto foi.
RESUMO = {
    "ipca": "media_geometrica",
    "pib": "media_geometrica",
    "desemprego": "media",
    "fome": "inicio_fim",
    "pobreza": "inicio_fim",
    "gini": "inicio_fim",
    "mortalidade_infantil_antiga": "inicio_fim",
    "mortalidade_infantil": "inicio_fim",
    "esperanca_vida": "inicio_fim",
    "ideb_anos_iniciais": "inicio_fim",
}


def _media_geometrica(valores):
    """Média anual de uma taxa percentual que se acumula."""
    produto = 1.0
    for v in valores:
        produto *= (1 + float(v) / 100)
    return (produto ** (1 / len(valores)) - 1) * 100


def series(con):
    """As séries disponíveis, com a procedência de cada uma."""
    with con.cursor() as cur:
        cur.execute("SELECT * FROM serie ORDER BY id")
        fora = [dict(r) for r in cur.fetchall()]
    # O Ideb não vem do SIDRA: sai do nosso próprio banco, do INEP.
    fora.append({
        "id": "ideb_anos_iniciais",
        "nome": "Ideb — anos iniciais (mediana dos municípios)",
        "unidade": "nota de 0 a 10", "fonte": "INEP/MEC",
        "tabela_sidra": None, "variavel": None, "corte": "bienal",
        "observacao": "É a MEDIANA das notas municipais da rede municipal, "
                      "calculada por nós — não é o Ideb nacional oficial, que o "
                      "INEP calcula com outra ponderação. Serve para comparar "
                      "anos entre si, não para citar como 'o Ideb do Brasil'. "
                      "Sai a cada dois anos, desde 2005.",
        "url": "https://www.gov.br/inep/pt-br/areas-de-atuacao/"
               "pesquisas-estatisticas-e-indicadores/ideb"})
    return fora


def valores(con):
    """{serie_id: {ano: valor}} — tudo que há, para todas as séries."""
    fora = {}
    with con.cursor() as cur:
        cur.execute("SELECT serie_id, ano, valor FROM serie_valor ORDER BY 1,2")
        for r in cur.fetchall():
            fora.setdefault(r["serie_id"], {})[r["ano"]] = float(r["valor"])
        cur.execute("""
            SELECT ano, ROUND(percentile_cont(0.5) WITHIN GROUP
                       (ORDER BY ideb)::numeric, 2) AS v
            FROM ideb
            WHERE etapa='anos_iniciais' AND rede='Municipal' AND ideb IS NOT NULL
            GROUP BY ano ORDER BY ano
        """)
        fora["ideb_anos_iniciais"] = {r["ano"]: float(r["v"]) for r in cur.fetchall()}
    return fora


def resumir(serie_id, dados_da_serie, anos):
    """Resume a série no período do mandato. Devolve None quando não há dado —
    e 'não há dado' é uma resposta legítima que a página mostra como tal, em
    vez de preencher com o número mais próximo."""
    pares = [(a, dados_da_serie[a]) for a in anos if a in dados_da_serie]
    if not pares:
        return None
    modo = RESUMO.get(serie_id, "media")
    vals = [v for _, v in pares]
    saida = {"anos_usados": [a for a, _ in pares],
             "cobertura": f"{pares[0][0]}–{pares[-1][0]}",
             "completo": len(pares) == len(anos), "modo": modo}
    if modo == "media_geometrica":
        saida["valor"] = round(_media_geometrica(vals), 2)
        saida["min"] = round(min(vals), 2)
        saida["max"] = round(max(vals), 2)
    elif modo == "inicio_fim":
        saida["valor"] = round(vals[-1], 2)
        saida["de"] = round(vals[0], 2)
        saida["para"] = round(vals[-1], 2)
        saida["variacao"] = round(vals[-1] - vals[0], 2)
    else:
        saida["valor"] = round(sum(vals) / len(vals), 2)
        saida["min"] = round(min(vals), 2)
        saida["max"] = round(max(vals), 2)
    return saida


def quadro(con):
    metas = {s["id"]: s for s in series(con)}
    dados = valores(con)
    linhas = []
    for p in PRESIDENTES:
        col = {k: p[k] for k in ("id", "nome", "partido", "inicio", "fim",
                                 "anos", "nota")}
        col["indicadores"] = {
            sid: resumir(sid, dados.get(sid, {}), p["anos"]) for sid in metas
        }
        linhas.append(col)
    return {"presidentes": linhas, "series": metas,
            "valores_por_ano": dados, "fontes": proveniencia(con)}


def imprimir(q):
    ordem = ["ipca", "pib", "desemprego", "fome", "pobreza", "gini",
             "esperanca_vida",
             "mortalidade_infantil_antiga", "mortalidade_infantil",
             "ideb_anos_iniciais"]
    for sid in ordem:
        s = q["series"].get(sid)
        if not s:
            continue
        print(f"\n── {s['nome']}  [{s['unidade']}]")
        for p in q["presidentes"]:
            r = p["indicadores"].get(sid)
            if not r:
                print(f"   {p['nome'][:26]:26s} sem dado no período")
                continue
            if r["modo"] == "inicio_fim":
                txt = f"{r['de']} → {r['para']}  ({r['variacao']:+})"
            else:
                txt = f"{r['valor']}  (de {r['min']} a {r['max']})"
            marca = "" if r["completo"] else f"  ⚠ só {r['cobertura']}"
            print(f"   {p['nome'][:26]:26s} {txt}{marca}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    con = bd.conectar()
    q = quadro(con)
    if args.json:
        print(json.dumps(q, ensure_ascii=False, indent=2, default=str))
    else:
        imprimir(q)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
