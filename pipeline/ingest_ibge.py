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
SIDRA = "https://apisidra.ibge.gov.br/values/t/{t}/{n}/all/v/{v}/p/all{c}"
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
    # Nível territorial. Quase tudo aqui é "n1" (Brasil), mas a Pesquisa
    # Mensal de Emprego nunca cobriu o país: ela media seis regiões
    # metropolitanas, e o SIDRA publica esse recorte no nível "n110"
    # ("Total das áreas - PME"). Pedir n1 numa tabela da PME devolve HTTP 400.
    nivel: str = "n1"
    # Em que dimensão da resposta está o ANO.
    #
    # Normalmente o ano é o PERÍODO da tabela e o ingestor o acha sozinho. Nas
    # tabelas de projeção, não: o período é a REVISÃO da projeção (uma só:
    # "2018") e o ano de referência é uma classificação à parte. Ler o período
    # ali daria 61 valores todos carimbados como 2018 — e o último a entrar
    # sobrescreveria os outros, deixando a série inteira com o número de um
    # ano só. Erro silencioso, do tipo que passa na conferência.
    dim_ano: str = ""
    # Último ano que pode entrar. Existe para as projeções: elas seguem até
    # 2060, e a partir de certo ponto deixam de descrever o que aconteceu
    # para descrever o que o modelo achava que ia acontecer.
    ano_max: int = 0


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
    # A PNAD Contínua começa em 2012 — de FHC a Dilma o quadro ficava vazio
    # na linha que mais aparece em discussão de botequim. O IBGE tem o número
    # antes disso, mas em pesquisas DIFERENTES, e o buraco não se tapa
    # emendando uma na outra: a "taxa de desemprego aberto" da PME antiga
    # conta quem procurou trabalho na semana, um recorte mais estreito que a
    # "desocupação" de hoje, e por isso dá 6% onde a medida atual daria o
    # dobro. Emendar as três produziria uma queda histórica que nunca houve.
    #
    # Então elas entram como TRÊS linhas separadas, cada uma dizendo de que
    # pesquisa veio e que anos cobre. Comparar governo com governo dentro da
    # mesma linha é legítimo; atravessar as linhas, não — e a página mostra
    # os anos cobertos em cada coluna justamente para isso ficar visível.
    "desemprego_pme_antiga": Serie(
        id="desemprego_pme_antiga",
        nome="Desemprego aberto nas regiões metropolitanas (1991–2002)",
        unidade="%", tabela="13", variavel="8", espera_nome="desemprego aberto",
        corte="media", nivel="n110",
        observacao="Pesquisa Mensal de Emprego, metodologia antiga, média dos "
                   "meses do ano. Cobre SEIS regiões metropolitanas (São "
                   "Paulo, Rio, Belo Horizonte, Porto Alegre, Salvador e "
                   "Recife), não o país. E mede 'desemprego aberto' — quem "
                   "procurou trabalho na semana da entrevista —, recorte mais "
                   "estreito que a desocupação medida hoje. Serve para "
                   "comparar anos DENTRO desta linha, nunca com as de baixo."),
    "desemprego_pme": Serie(
        id="desemprego_pme",
        nome="Desocupação nas regiões metropolitanas (2003–2015)",
        unidade="%", tabela="1168", variavel="2498", espera_nome="desocupação",
        corte="anual", nivel="n110",
        observacao="Pesquisa Mensal de Emprego, metodologia de 2002, taxa "
                   "média do ano já calculada pelo IBGE. Também cobre só as "
                   "seis regiões metropolitanas. Ficou no ar até 2015, quando "
                   "a PNAD Contínua a substituiu."),
    # --------------------------------------------------------- fome e renda
    "fome": Serie(
        id="fome", nome="Fome (insegurança alimentar grave)", unidade="%",
        tabela="6665", variavel="2133",
        espera_nome="insegurança alimentar grave",
        classificacao="/c12404/109102",
        observacao="Percentual de pessoas em lares com insegurança alimentar "
                   "GRAVE — a definição oficial de quem passou por falta real "
                   "de comida. A pesquisa não é anual: foi a campo em 2004, "
                   "2009, 2013, 2018, 2023 e 2024, e os anos sem medição ficam "
                   "vazios em vez de inventados."),
    # A tabela do ODS 1.1.1 (10443, linha internacional) publica só os
    # recortes por sexo e por cor — o TOTAL do país vem vazio ('..') em todos
    # os anos, inclusive forçando as categorias de total. Publicar o recorte
    # de um grupo como se fosse o país seria número errado; usamos a linha de
    # pobreza REGIONAL do painel ODS Brasil (10660), que traz o total.
    "pobreza": Serie(
        id="pobreza", nome="Pobreza", unidade="%",
        tabela="10660", variavel="14137", espera_nome="linha de pobreza",
        observacao="Percentual da população abaixo da linha de pobreza "
                   "regional (metodologia do painel ODS Brasil, calculada "
                   "pelo IBGE sobre a PNAD Contínua, que começa em 2012)."),
    "gini": Serie(
        id="gini", nome="Desigualdade de renda (índice de Gini)",
        unidade="Índice",
        tabela="7435", variavel="10681", espera_nome="Gini",
        observacao="De 0 a 1: quanto mais perto de 1, mais concentrada a "
                   "renda. Calculado sobre o rendimento domiciliar per capita "
                   "da PNAD Contínua, que começa em 2012."),
    # Mesma história do desemprego: a desigualdade só tem série contínua a
    # partir de 2012. A PNAD antiga mediu de 1992 a 2011 — mas o Gini dela é
    # sobre o rendimento DAS PESSOAS QUE TÊM RENDIMENTO, e o de hoje é sobre o
    # rendimento domiciliar per capita de todo mundo. Dá 0,58 onde o atual dá
    # 0,54. São duas perguntas diferentes, e ficam em duas linhas.
    "gini_pnad_antiga": Serie(
        id="gini_pnad_antiga",
        nome="Desigualdade de renda — PNAD antiga (1992–2011)", unidade="Índice",
        tabela="1167", variavel="1879", espera_nome="Gini",
        observacao="Índice de Gini do rendimento mensal das pessoas de 10 anos "
                   "ou mais COM RENDIMENTO, na PNAD anual. Base diferente da "
                   "linha da PNAD Contínua (que usa o rendimento domiciliar "
                   "per capita de toda a população), por isso o nível é mais "
                   "alto. Não há medição em 1994, 2000 e 2010: nesses anos a "
                   "PNAD não foi a campo (Censo)."),
    # ------------------------------------------------------------------ saúde
    "mortalidade_infantil_antiga": Serie(
        id="mortalidade_infantil_antiga",
        nome="Mortalidade infantil (série 1990–2009)", unidade="‰",
        tabela="1175", variavel="1940", espera_nome="mortalidade infantil",
        observacao="Mortes de menores de 1 ano por mil nascidos vivos. "
                   "Série encerrada pelo IBGE."),
    "mortalidade_infantil": Serie(
        id="mortalidade_infantil",
        nome="Mortalidade infantil (projeção, até 2018)", unidade="‰",
        tabela="7362", variavel="1940", espera_nome="mortalidade infantil",
        classificacao="/c2/6794/c1933/all", dim_ano="D5N", ano_max=2018,
        observacao="Mortes de menores de 1 ano por mil nascidos vivos, na "
                   "Projeção da População do IBGE, revisão de 2018. É modelo "
                   "calibrado, não contagem — e por isso para em 2018: a "
                   "projeção segue até 2060, mas foi feita antes da covid e "
                   "não sabe o que aconteceu depois. Para os anos recentes, "
                   "as linhas de mortalidade neonatal e até 5 anos são "
                   "medidas, não projetadas."),
    # As duas linhas de mortalidade infantil acima param em 2009 e em 2016, e
    # as duas saem da PROJEÇÃO da população do IBGE (revisão de 2018) — ou
    # seja, de um modelo. A projeção continua até 2060, e seria fácil puxá-la
    # para preencher Temer, Bolsonaro e Lula 3. Seria também publicar como
    # "o que aconteceu" uma previsão feita ANTES da covid: ela crava
    # expectativa de vida de 76,7 anos em 2020, ano em que a expectativa de
    # vida do brasileiro CAIU. Não entra.
    #
    # O que entra são três indicadores de saúde MEDIDOS, do painel dos
    # Objetivos de Desenvolvimento Sustentável, que o IBGE calcula do registro
    # civil e das estatísticas de saúde — não de modelo. Eles cobrem os
    # governos recentes, inclusive a covid, com o que de fato foi contado.
    "mortalidade_menores5": Serie(
        id="mortalidade_menores5",
        nome="Mortalidade de crianças até 5 anos", unidade="Óbitos por mil",
        tabela="6695", variavel="9731", espera_nome="menores de 5 anos",
        observacao="ODS 3.2.1. De cada mil crianças nascidas vivas, quantas "
                   "morreram antes de completar 5 anos. Medida, ano a ano, "
                   "desde 2000 — não é projeção."),
    "mortalidade_neonatal": Serie(
        id="mortalidade_neonatal",
        nome="Mortalidade nos primeiros 27 dias de vida",
        unidade="Óbitos por mil",
        tabela="6696", variavel="9732", espera_nome="neonatal",
        observacao="ODS 3.2.2. De cada mil bebês nascidos vivos, quantos "
                   "morreram antes de completar 28 dias. É a série de saúde "
                   "mais longa que o IBGE publica medida: começa em 1990."),
    "mortalidade_materna": Serie(
        id="mortalidade_materna",
        nome="Mortalidade materna", unidade="Óbitos por 100 mil",
        tabela="6694", variavel="9730", espera_nome="materna",
        observacao="ODS 3.1.1. Mortes de mulheres por causas ligadas à "
                   "gravidez, ao parto ou ao pós-parto, por 100 mil crianças "
                   "nascidas vivas. Medida desde 2009. O salto de 2021 é a "
                   "covid: gestante não vacinada foi grupo de risco."),
    # ESTA SÉRIE MUDOU DE TABELA EM 2026-08-31, e vale registrar por quê.
    #
    # Antes vinha da tabela 3825, que o SIDRA ainda publica mas cujo rodapé
    # diz "Revisão 2013" — projeção da população de treze anos atrás, com uma
    # casa decimal, congelada em 2016 (última atualização: 05/06/2017). A
    # 7362 é a MESMA série, na revisão de 2018: duas casas decimais e dois
    # anos a mais. As duas concordam nos 17 anos em comum dentro do
    # arredondamento (a maior diferença é 0,05 ano), então trocar não reescreve
    # a história — só a traz para a revisão vigente e completa o mandato do
    # Temer, que antes ficava sem nenhum dado de saúde.
    "esperanca_vida": Serie(
        id="esperanca_vida",
        nome="Expectativa de vida ao nascer (projeção, até 2018)",
        unidade="Anos",
        tabela="7362", variavel="2503", espera_nome="esperança de vida",
        classificacao="/c2/6794/c1933/all", dim_ano="D5N", ano_max=2018,
        observacao="Projeção da População do IBGE, revisão de 2018. É modelo "
                   "calibrado nas estatísticas vitais, não contagem direta. "
                   "Para em 2018 de propósito: a projeção segue até 2060, mas "
                   "foi feita antes da covid e crava 76,7 anos para 2020 — o "
                   "ano em que a expectativa de vida do brasileiro CAIU. "
                   "Publicar essa previsão como 'o que aconteceu no mandato' "
                   "seria número errado com cara de oficial."),
}


def baixar(serie):
    url = SIDRA.format(t=serie.tabela, n=serie.nivel, v=serie.variavel,
                       c=serie.classificacao)
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
    # O sentido de uma série pode morar na variável (D2N) OU numa categoria de
    # classificação (D4N): na tabela da fome, a variável é só "Moradores em
    # domicílios particulares" — quem diz "insegurança alimentar grave" é a
    # categoria. Procuramos o nome esperado em todas as dimensões da linha.
    dims = " | ".join(str(v) for k, v in linha.items() if k.endswith("N"))
    nome = (linha.get("D2N") or linha.get("D3N") or "")
    unidade = linha.get("MN") or ""
    if serie.espera_nome.lower() not in dims.lower():
        raise ValueError(
            f"{serie.id}: a variável do IBGE mudou de sentido.\n"
            f"  esperado conter: {serie.espera_nome!r}\n"
            f"  veio: {dims!r}\n"
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
        if serie.dim_ano:
            ano, chave = int(linha[serie.dim_ano]), ""
        else:
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
    if serie.ano_max:
        saida = {a: v for a, v in saida.items() if a <= serie.ano_max}
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
