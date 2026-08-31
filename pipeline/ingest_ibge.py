#!/usr/bin/env python3
"""Séries nacionais do IBGE (SIDRA) → banco.

Para o quadro comparativo entre governos. Cada série é declarada aqui com a
tabela e a variável do SIDRA, e a API do IBGE é **auto-descritiva**: a
resposta traz o nome da variável e a unidade de medida. O ingestor CONFERE
esses dois campos contra o que foi declarado e aborta se divergirem.

Isso não é preciosismo. A primeira tentativa deste trabalho usou o SGS do
Banco Central chutando códigos de série: o código que eu supus ser "taxa de
desocupação" devolveu 109,89 — um número plausível de índice, absurdo de
percentual. Um chute desses vira gráfico publicado. Com a conferência, série
trocada não passa: quebra a ingestão.

    python3.13 pipeline/ingest_ibge.py
    python3.13 pipeline/ingest_ibge.py --serie ipca
"""
import argparse
import gzip
import json
import os
import sys
import urllib.request
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd

UA = {"User-Agent": "Mozilla/5.0 (compatible; brincando-de-brasil/1.0; +dados abertos)",
      "Accept-Encoding": "gzip"}
SIDRA = "https://apisidra.ibge.gov.br/values/t/{t}/n1/all/v/{v}/p/all{c}"
LINK = "https://sidra.ibge.gov.br/tabela/{t}"


@dataclass(frozen=True)
class Serie:
    id: str
    nome: str              # como aparece no site
    unidade: str           # unidade esperada, conferida contra a resposta
    tabela: str            # tabela do SIDRA
    variavel: str          # variável dentro da tabela
    espera_nome: str       # trecho que o nome da variável do IBGE deve conter
    # Filtro de período: as séries mensais/trimestrais precisam de UM ponto por
    # ano, e qual ponto é uma decisão metodológica, não um detalhe.
    #   'dezembro'  — o acumulado do ano fechado em dezembro (IPCA)
    #   'q4'        — o 4º trimestre (acumulado no ano do PIB)
    #   'media'     — média dos períodos do ano (desemprego)
    #   'anual'     — a série já é anual
    corte: str = "anual"
    observacao: str = ""
    # Sufixo de classificação do SIDRA (ex.: "/c11255/90707").
    #
    # Não é opcional quando a tabela tem classificação: a 5932 devolve a
    # variável do PIB com TODOS os valores vazios se ninguém disser de qual
    # setor se está falando. Sem o filtro, "PIB a preços de mercado" some e a
    # série vem em branco — falha barulhenta, felizmente, e não silenciosa.
    classificacao: str = ""


SERIES = {
    # ---------------------------------------------------------------- economia
    "ipca": Serie(
        id="ipca", nome="Inflação no ano (IPCA)", unidade="%",
        tabela="1737", variavel="69", espera_nome="acumulada no ano",
        corte="dezembro",
        observacao="Variação acumulada no ano, fechada em dezembro. É o índice "
                   "oficial de inflação do país."),
    "pib": Serie(
        id="pib", nome="Crescimento do PIB no ano", unidade="%",
        tabela="5932", variavel="6563", espera_nome="acumulada ao longo do ano",
        corte="q4", classificacao="/c11255/90707",   # PIB a preços de mercado
        observacao="Variação real do volume do PIB, acumulada no ano, no 4º "
                   "trimestre. Começa em 1996: antes disso o IBGE não publica "
                   "esta série trimestral."),
    # PIB per capita (tabela 6784, variável 9812) foi DELIBERADAMENTE deixado
    # de fora. O IBGE o publica a preços correntes de cada ano, sem correção
    # pela inflação: numa tabela entre governos ele sobe sempre, para todo
    # mundo, e o leitor conclui que a economia cresceu em todos os mandatos.
    # A própria página ensina a desconfiar disso ("é o total ou é por pessoa,
    # corrigido?") — publicá-lo aqui seria contradizer a lição na linha de
    # baixo. Entra quando houver a série a preços constantes.
    "desemprego": Serie(
        id="desemprego", nome="Desemprego", unidade="%",
        tabela="6381", variavel="4099", espera_nome="desocupa", corte="media",
        observacao="PNAD Contínua, média dos trimestres do ano. Começa em 2012: "
                   "as pesquisas anteriores usavam outra metodologia e outro "
                   "recorte, e encaixá-las na mesma linha seria comparar "
                   "coisas diferentes."),
    # ------------------------------------------------------------------ saúde
    "mortalidade_infantil_antiga": Serie(
        id="mortalidade_infantil_antiga",
        nome="Mortalidade infantil (série 1990–2009)", unidade="‰",
        tabela="1175", variavel="1940", espera_nome="mortalidade infantil",
        observacao="Mortes de menores de 1 ano por mil nascidos vivos. "
                   "Série encerrada pelo IBGE."),
    "mortalidade_infantil": Serie(
        id="mortalidade_infantil",
        nome="Mortalidade infantil", unidade="‰",
        tabela="3834", variavel="1940", espera_nome="mortalidade infantil",
        observacao="Mortes de menores de 1 ano por mil nascidos vivos."),
    "esperanca_vida": Serie(
        id="esperanca_vida", nome="Expectativa de vida ao nascer", unidade="Anos",
        tabela="3825", variavel="2503", espera_nome="esperança de vida",
        observacao="Vai só até 2016: é o fim da série publicada nesta tabela."),
}


def baixar(serie):
    url = SIDRA.format(t=serie.tabela, v=serie.variavel, c=serie.classificacao)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        bruto = r.read()
    if bruto[:2] == b"\x1f\x8b":
        bruto = gzip.decompress(bruto)
    return json.loads(bruto.decode("utf-8"))


def conferir_resposta(serie, dados):
    """A resposta do SIDRA descreve a si mesma. Conferimos antes de acreditar."""
    if not dados or len(dados) < 2:
        raise ValueError(f"{serie.id}: resposta vazia")
    linha = dados[1]
    nome = (linha.get("D2N") or linha.get("D3N") or "")
    unidade = linha.get("MN") or ""
    if serie.espera_nome.lower() not in nome.lower():
        raise ValueError(
            f"{serie.id}: a variável do IBGE mudou de sentido.\n"
            f"  esperado conter: {serie.espera_nome!r}\n"
            f"  veio: {nome!r}\n"
            f"  Não ingerido — série trocada vira número errado publicado.")
    if unidade and serie.unidade not in unidade:
        raise ValueError(f"{serie.id}: unidade {unidade!r}, esperada {serie.unidade!r}")
    return nome, unidade


def _ano_e_chave(periodo):
    """'202312'→(2023,'12'); '2023'→(2023,''); '202304'(trimestre)→(2023,'04')."""
    p = str(periodo)
    if len(p) == 4:
        return int(p), ""
    return int(p[:4]), p[4:]


def valores_por_ano(serie, dados):
    """Aplica o corte e devolve {ano: valor}. Valores ausentes viram nada:
    o SIDRA marca indisponível com '-', '...' ou '..'."""
    bruto = {}
    for linha in dados[1:]:
        v = (linha.get("V") or "").strip()
        if v in ("", "-", "...", "..", "X"):
            continue
        try:
            valor = float(v.replace(",", "."))
        except ValueError:
            continue
        ano, chave = _ano_e_chave(linha.get("D3C") or linha.get("D2C") or "")
        bruto.setdefault(ano, []).append((chave, valor))

    # Quantos períodos tem um ano COMPLETO nesta série? Não dá para cravar:
    # a tabela do desemprego é de "trimestre móvel" e traz 12 pontos por ano,
    # não 4. Descobrir pelo próprio dado evita o palpite — e evita que a média
    # de um ano pela metade entre na tabela parecendo comparável.
    completo = max((len(v) for v in bruto.values()), default=0)

    saida = {}
    for ano, pares in bruto.items():
        pares.sort()
        if serie.corte == "dezembro":
            escolha = [v for k, v in pares if k == "12"]
            if escolha:
                saida[ano] = escolha[0]
        elif serie.corte == "q4":
            escolha = [v for k, v in pares if k in ("04", "4")]
            if escolha:
                saida[ano] = escolha[0]
        elif serie.corte == "media":
            # Só entra ano COMPLETO. O primeiro ano da série (que começa no meio)
            # e o ano em curso ficam de fora: a média de 7 períodos contra a
            # média de 12 não é a mesma medida, e num quadro entre governos a
            # diferença cairia toda na conta de um deles.
            if len(pares) == completo:
                saida[ano] = sum(v for _, v in pares) / len(pares)
        else:
            saida[ano] = pares[-1][1]
    return saida


def ingerir(con, serie):
    print(f"── {serie.id}")
    dados = baixar(serie)
    nome_ibge, unidade = conferir_resposta(serie, dados)
    print(f"  IBGE confirma: {nome_ibge[:56]!r} [{unidade}]")
    anos = valores_por_ano(serie, dados)
    if not anos:
        raise ValueError(f"{serie.id}: nenhum valor após o corte {serie.corte!r}")

    with con.cursor() as cur:
        cur.execute("""
            INSERT INTO serie (id, nome, unidade, fonte, tabela_sidra, variavel,
                               corte, observacao, url)
            VALUES (%s,%s,%s,'IBGE/SIDRA',%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                nome=EXCLUDED.nome, unidade=EXCLUDED.unidade,
                tabela_sidra=EXCLUDED.tabela_sidra, variavel=EXCLUDED.variavel,
                corte=EXCLUDED.corte, observacao=EXCLUDED.observacao,
                url=EXCLUDED.url
        """, (serie.id, serie.nome, serie.unidade, serie.tabela, serie.variavel,
              serie.corte, serie.observacao, LINK.format(t=serie.tabela)))
        cur.executemany("""
            INSERT INTO serie_valor (serie_id, ano, valor)
            VALUES (%s,%s,%s)
            ON CONFLICT (serie_id, ano) DO UPDATE SET valor=EXCLUDED.valor
        """, [(serie.id, a, round(v, 4)) for a, v in sorted(anos.items())])
    con.commit()
    a = sorted(anos)
    print(f"  {len(anos)} anos: {a[0]}–{a[-1]}")
    return len(anos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--serie", choices=list(SERIES), action="append")
    args = ap.parse_args()
    con = bd.conectar()
    bd.init(con)
    total = 0
    for sid in (args.serie or list(SERIES)):
        total += ingerir(con, SERIES[sid])
    print(f"\nok: {bd.contar(con, 'serie_valor')} pontos em "
          f"{bd.contar(con, 'serie')} séries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
