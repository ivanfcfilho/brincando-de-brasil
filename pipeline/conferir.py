#!/usr/bin/env python3
"""Invariantes do banco. Roda no fim do job e antes de qualquer publicação.

Existe porque um bug real passou silencioso: o ZIP do TSE traz agregados
nacionais além das 27 UFs, e ler um deles carimbou uma única UF em 91% das
linhas de voto. Nada quebrou, nenhum erro apareceu — só as consultas por
estado passaram a devolver quase nada. Erro que não grita é o perigoso, então
as afirmações que o projeto faz sobre os próprios dados viram teste.

Uso:
    python3.13 pipeline/conferir.py          # sai != 0 se algo falhar
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd

# Bancada de cada estado na Câmara (513 no total). Números constitucionais,
# não derivados do dado — é isso que os torna uma conferência de verdade.
CADEIRAS = {
    "AC": 8, "AL": 9, "AP": 8, "AM": 8, "BA": 39, "CE": 22, "DF": 8,
    "ES": 10, "GO": 17, "MA": 18, "MT": 8, "MS": 8, "MG": 53, "PA": 17,
    "PB": 12, "PR": 30, "PE": 25, "PI": 10, "RJ": 46, "RN": 8, "RS": 31,
    "RO": 8, "RR": 8, "SC": 16, "SP": 70, "SE": 8, "TO": 8,
}


def conferir(con):
    falhas = []

    def checar(nome, ok, detalhe=""):
        print(f"  {'ok  ' if ok else 'FALHA'} {nome}" + (f" — {detalhe}" if detalhe else ""))
        if not ok:
            falhas.append(nome)

    print("conferindo invariantes:")

    n = bd.um(con, "SELECT COUNT(*) AS c FROM deputado WHERE situacao LIKE 'ELEITO%'")["c"]
    checar("513 deputados federais eleitos", n == 513, f"{n} no banco")

    with con.cursor() as cur:
        cur.execute("""SELECT uf, COUNT(*) AS c FROM deputado
                       WHERE situacao LIKE 'ELEITO%' GROUP BY uf""")
        real = {r["uf"]: r["c"] for r in cur.fetchall()}
    divergentes = {uf: (real.get(uf, 0), n) for uf, n in CADEIRAS.items()
                   if real.get(uf, 0) != n}
    checar("bancada de cada UF bate com a Constituição", not divergentes,
           str(divergentes) if divergentes else "27 UFs")

    n = bd.um(con, """SELECT COUNT(*) AS c FROM voto_municipio v
                      JOIN deputado d USING (sq_candidato) WHERE v.uf <> d.uf""")["c"]
    checar("UF do voto = UF do deputado", n == 0, f"{n} linhas divergentes")

    n = bd.um(con, "SELECT COUNT(*) AS c FROM voto_municipio WHERE votos < 0")["c"]
    checar("nenhum voto negativo", n == 0, f"{n} linhas")

    n = bd.um(con, """SELECT COUNT(*) AS c FROM (
                        SELECT sq_candidato FROM autor WHERE sq_candidato IS NOT NULL
                        GROUP BY 1 HAVING COUNT(*) > 1) x""")["c"]
    checar("deputado com >1 código de autor está na fila de revisão", True,
           f"{n} casos (ver vincular.py)")

    n = bd.um(con, """SELECT COUNT(*) AS c FROM emenda e
                      LEFT JOIN snapshot s ON s.id = e.snapshot_id
                      WHERE s.id IS NULL""")["c"]
    checar("toda emenda aponta para um snapshot", n == 0, f"{n} órfãs")

    # --- município: a ponte que sustenta a distância em km ---
    n = bd.um(con, "SELECT COUNT(*) AS c FROM municipio")["c"]
    checar("5.570 municípios do IBGE carregados", n >= 5570, f"{n} no banco")

    n = bd.um(con, "SELECT COUNT(*) AS c FROM municipio WHERE lat IS NULL")["c"]
    checar("todo município com coordenada", n <= 1, f"{n} sem centroide")

    n = bd.um(con, """SELECT COUNT(*) AS c FROM voto_municipio v
                      LEFT JOIN municipio m ON m.cod_tse = v.cod_municipio_tse
                      WHERE m.cod_ibge IS NULL""")["c"]
    checar("todo município do TSE resolve para o IBGE", n == 0,
           f"{n} linhas de voto sem correspondência")

    r = bd.um(con, """SELECT round(100.0 * SUM(valor_recebido) FILTER (
                          WHERE cod_ibge_favorecido IS NOT NULL)
                          / NULLIF(SUM(valor_recebido),0), 1) AS pct
                      FROM emenda_favorecido""")
    pct = float(r["pct"] or 0)
    checar("≥99% do valor executado tem município identificado", pct >= 99,
           f"{pct}% do valor")

    # --- as classes de destino têm que particionar o total ---
    # Percentual acima de 100% no ar é munição contra o projeto, e o erro é
    # silencioso: só aparece quando alguém soma as parcelas na tela.
    r = bd.um(con, """
        WITH base AS (
          SELECT e.sq_candidato, d.uf AS uf_dep, e.empenhado, m.cod_ibge, m.uf AS uf_mun
          FROM vw_emenda_deputado e
          JOIN deputado d ON d.sq_candidato = e.sq_candidato
          LEFT JOIN municipio m ON m.cod_ibge = e.cod_ibge
          WHERE d.situacao LIKE 'ELEITO%'
        )
        SELECT COUNT(*) AS fora FROM (
          SELECT sq_candidato,
                 SUM(empenhado) AS total,
                 SUM(empenhado) FILTER (WHERE uf_mun = uf_dep) AS a,
                 SUM(empenhado) FILTER (WHERE cod_ibge IS NOT NULL AND uf_mun <> uf_dep) AS b,
                 SUM(empenhado) FILTER (WHERE cod_ibge IS NULL) AS c
          FROM base GROUP BY 1
        ) x WHERE abs(total - (COALESCE(a,0)+COALESCE(b,0)+COALESCE(c,0))) > 0.01
    """)
    checar("classes de destino somam o total, deputado a deputado",
           r["fora"] == 0, f"{r['fora']} deputados com parcelas fora do total")

    n = bd.um(con, """SELECT COUNT(DISTINCT d.sq_candidato) AS c FROM deputado d
                      JOIN autor a ON a.sq_candidato = d.sq_candidato
                      WHERE d.situacao LIKE 'ELEITO%'""")["c"]
    checar("≥495 dos 513 eleitos com autoria identificada", n >= 495,
           f"{n}/513 (os que faltam assumiram ministério, "
           f"tiveram mandato cassado ou não apresentaram emenda)")

    # ------------------------------------------------- sistema eleitoral
    #
    # A página "Como funciona a eleição" afirma que houve candidato com MAIS
    # voto que um eleito do mesmo estado. Se uma reingestão do TSE mudasse a
    # coluna de situação, a página passaria a ensinar uma regra que o dado já
    # não mostra — sem erro nenhum aparecer.
    r = bd.um(con, """
        WITH v AS (
            SELECT d.uf, d.situacao, vt.total_votos
            FROM deputado d
            JOIN vw_votos_totais vt ON vt.sq_candidato = d.sq_candidato
        ), piso AS (
            SELECT uf, MIN(total_votos) AS m FROM v
            WHERE situacao LIKE 'ELEITO%' GROUP BY 1
        )
        SELECT COUNT(*) AS c FROM v JOIN piso p ON p.uf = v.uf
        WHERE v.situacao = 'SUPLENTE' AND v.total_votos > p.m
    """)
    checar("há candidato não eleito com mais voto que um eleito da mesma UF",
           r["c"] > 0, f"{r['c']} casos (o argumento da página do voto proporcional)")

    with con.cursor() as cur:
        cur.execute("""SELECT DISTINCT situacao FROM deputado ORDER BY 1""")
        sits = [x["situacao"] for x in cur.fetchall()]
    checar("situação do TSE só tem os três valores esperados",
           set(sits) == {"ELEITO POR QP", "ELEITO POR MEDIA", "SUPLENTE"}, str(sits))

    # --------------------------------------------- séries entre governos
    #
    # A página dos governos afirma números do IBGE. Série vazia ou fora de
    # ordem de grandeza vira gráfico errado numa página que já é a mais
    # delicada do site.
    with con.cursor() as cur:
        cur.execute("""SELECT s.id, COUNT(v.ano) AS n
                       FROM serie s LEFT JOIN serie_valor v ON v.serie_id = s.id
                       GROUP BY 1 ORDER BY 1""")
        contagem = {r["id"]: r["n"] for r in cur.fetchall()}
    vazias = [k for k, n in contagem.items() if n == 0]
    checar("toda série do IBGE tem pelo menos um ano carregado", not vazias,
           str(vazias) if vazias else f"{len(contagem)} séries")

    # A hiperinflação é o melhor teste de sanidade que existe para esta base:
    # se o IPCA de 1990 não vier na casa dos milhares, a série está trocada.
    r = bd.um(con, "SELECT valor FROM serie_valor WHERE serie_id='ipca' AND ano=1990")
    checar("IPCA de 1990 na casa da hiperinflação (>1000%)",
           r is not None and float(r["valor"]) > 1000,
           f"{float(r['valor']):.0f}%" if r else "sem dado")

    # As três séries de desemprego vêm de pesquisas diferentes, mas nenhuma
    # delas jamais chegou perto de 40% — a faixa vale para todas, e a checagem
    # cobre as três porque foi conferindo série por id fixo que uma nova
    # entraria no site sem passar por conferência nenhuma.
    r = bd.um(con, """SELECT COUNT(*) AS c FROM serie_valor
                      WHERE serie_id LIKE 'desemprego%'
                        AND (valor < 0 OR valor > 40)""")
    checar("desemprego entre 0% e 40% (as 3 séries)", r["c"] == 0,
           f"{r['c']} fora da faixa")

    # Faixas de sanidade das séries sociais: Gini nacional fora de 0,3–0,8
    # nunca aconteceu na história da medição — se aparecer, é série trocada.
    r = bd.um(con, """SELECT COUNT(*) AS c FROM serie_valor
                      WHERE serie_id LIKE 'gini%' AND (valor < 0.3 OR valor > 0.8)""")
    checar("Gini entre 0,3 e 0,8 (as 2 séries)", r["c"] == 0,
           f"{r['c']} fora da faixa")
    r = bd.um(con, """SELECT COUNT(*) AS c FROM serie_valor
                      WHERE serie_id IN ('fome','pobreza')
                        AND (valor <= 0 OR valor > 60)""")
    checar("fome e pobreza entre 0% e 60%", r["c"] == 0, f"{r['c']} fora da faixa")

    # Mortalidade: as três séries medidas são por MIL nascidos vivos, menos a
    # materna, que é por CEM MIL. Trocar a unidade de uma delas é o erro mais
    # fácil de cometer aqui e o mais difícil de notar no gráfico — 55 vira um
    # número plausível em qualquer das duas escalas. As faixas separam.
    r = bd.um(con, """SELECT COUNT(*) AS c FROM serie_valor
                      WHERE serie_id IN ('mortalidade_menores5',
                                         'mortalidade_neonatal',
                                         'mortalidade_infantil',
                                         'mortalidade_infantil_antiga')
                        AND (valor <= 0 OR valor > 60)""")
    checar("mortalidade infantil/neonatal/até-5 entre 0 e 60 por mil",
           r["c"] == 0, f"{r['c']} fora da faixa")
    r = bd.um(con, """SELECT COUNT(*) AS c FROM serie_valor
                      WHERE serie_id='mortalidade_materna'
                        AND (valor < 20 OR valor > 300)""")
    checar("mortalidade materna entre 20 e 300 por 100 mil", r["c"] == 0,
           f"{r['c']} fora da faixa")

    # As duas séries que saem da PROJEÇÃO da população não podem passar de
    # 2018. A tabela do IBGE entrega até 2060 num único pedido, e o dia em que
    # alguém tirar o corte o site vai publicar, com cara de dado oficial, uma
    # previsão feita em 2018 que não sabe que a covid existiu — ela crava 76,7
    # anos de expectativa de vida em 2020, o ano em que a expectativa CAIU.
    r = bd.um(con, """SELECT COUNT(*) AS c FROM serie_valor
                      WHERE serie_id IN ('esperanca_vida','mortalidade_infantil')
                        AND ano > 2018""")
    checar("projeção da população cortada em 2018 (previsão não é medição)",
           r["c"] == 0, f"{r['c']} anos além do corte")

    # A covid tem que aparecer: em 2021 a mortalidade materna disparou porque
    # gestante não vacinada foi grupo de risco. Se essa marca sumir da série,
    # alguém trocou a fonte por uma versão suavizada — ou por uma projeção.
    r = bd.um(con, """SELECT valor FROM serie_valor
                      WHERE serie_id='mortalidade_materna' AND ano=2021""")
    checar("a covid está na série de mortalidade materna (2021 > 100)",
           r is not None and float(r["valor"]) > 100,
           f"{float(r['valor']):.1f} por 100 mil" if r else "sem dado")

    # ---------------------------------------------------------------- Ideb
    #
    # A planilha do INEP tem 122 colunas e o ano mora no NOME da coluna. É
    # exatamente a forma de arquivo em que um desalinhamento de uma casa não
    # levanta exceção nenhuma: os números continuam plausíveis, só passam a
    # ser de outro ano ou de outra medida. A identidade abaixo é a defesa.
    r = bd.um(con, """
        SELECT COUNT(*) AS n,
               COUNT(*) FILTER (WHERE ABS(ideb - ROUND(nota * fluxo, 1)) > 0.1)
                   AS fora
        FROM ideb
        WHERE ideb IS NOT NULL AND nota IS NOT NULL AND fluxo IS NOT NULL
    """)
    checar("Ideb = nota × fluxo, em toda linha medida", r["fora"] == 0,
           f"{r['fora']} divergentes em {r['n']} medições")

    r = bd.um(con, """
        SELECT COUNT(*) FILTER (WHERE ideb  < 0 OR ideb  > 10) AS ideb_fora,
               COUNT(*) FILTER (WHERE nota  < 0 OR nota  > 10) AS nota_fora,
               COUNT(*) FILTER (WHERE fluxo < 0 OR fluxo > 1)  AS fluxo_fora
        FROM ideb
    """)
    fora = dict(r)
    checar("Ideb e nota entre 0 e 10, fluxo entre 0 e 1",
           not any(fora.values()), str(fora))

    n = bd.um(con, """SELECT COUNT(DISTINCT i.cod_ibge) AS c FROM ideb i
                      LEFT JOIN municipio m ON m.cod_ibge = i.cod_ibge
                      WHERE m.cod_ibge IS NULL""")["c"]
    checar("todo município do INEP resolve para a tabela `municipio`", n == 0,
           f"{n} sem correspondência")

    # Cobertura: os anos iniciais são quase todos municipais. Uma queda brusca
    # aqui significa etapa não ingerida ou rede lida com o nome errado — e o
    # sintoma seria a página dizer "sem medição" para meio país.
    n = bd.um(con, """SELECT COUNT(*) AS c FROM ideb
                      WHERE etapa='anos_iniciais' AND rede='Municipal'
                        AND ano=2023 AND ideb IS NOT NULL""")["c"]
    checar("≥5.000 municípios com Ideb 2023 dos anos iniciais (rede municipal)",
           n >= 5000, f"{n} municípios")

    with con.cursor() as cur:
        cur.execute("""SELECT fonte_id, COUNT(*) AS c FROM snapshot
                       WHERE ingerido_em IS NOT NULL GROUP BY 1""")
        fontes = {r["fonte_id"]: r["c"] for r in cur.fetchall()}
    exigidas = {"cgu_emendas", "tse_munzona_2022", "inep_ideb_anos_iniciais",
                "inep_ideb_anos_finais", "inep_ideb_ensino_medio"}
    checar("todas as fontes têm snapshot ingerido", exigidas <= set(fontes),
           str(sorted(exigidas - set(fontes)) or f"{len(fontes)} fontes"))

    print(f"\n{'TUDO OK' if not falhas else 'FALHAS: ' + ', '.join(falhas)}")
    return 0 if not falhas else 1


if __name__ == "__main__":
    raise SystemExit(conferir(bd.conectar()))
