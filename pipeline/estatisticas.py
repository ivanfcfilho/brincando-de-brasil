#!/usr/bin/env python3
"""Números nacionais para o dossiê da PEC do Voto Distrital Misto.

Existe para que nenhum número do white paper seja digitado à mão. Cada
afirmação empírica sobre o Brasil sai daqui, do mesmo banco que a busca por
CEP usa, e pode ser recalculada por qualquer pessoa com o repositório.

    python3.13 pipeline/estatisticas.py            # legível
    python3.13 pipeline/estatisticas.py --json     # para gerar a página
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd

MANDATO = 2023

# Centro de gravidade eleitoral de cada deputado: a média das coordenadas dos
# municípios onde teve voto, ponderada pelos votos. É o "endereço" que o
# mandato teria, se o mandato tivesse endereço.
BASE_ELEITORAL = """
    WITH eleitos AS (
        SELECT sq_candidato, uf, nome_urna, partido FROM deputado
        WHERE situacao LIKE 'ELEITO%%'
    ), centro AS (
        SELECT v.sq_candidato,
               SUM(v.votos * m.lat) / SUM(v.votos) AS lat,
               SUM(v.votos * m.lon) / SUM(v.votos) AS lon,
               SUM(v.votos) AS total_votos
        FROM voto_municipio v
        JOIN municipio m ON m.cod_tse = v.cod_municipio_tse
        JOIN eleitos e ON e.sq_candidato = v.sq_candidato
        WHERE m.lat IS NOT NULL
        GROUP BY 1
    )
"""


def stats(con):
    r = {}

    # 1. Distância entre o centro do voto e o destino do dinheiro.
    r["distancia"] = dict(bd.um(con, BASE_ELEITORAL + """
        , dinheiro AS (
            SELECT f.sq_candidato, m.cod_ibge, SUM(f.valor_recebido) AS valor
            FROM vw_favorecido_deputado f
            JOIN municipio m ON m.cod_ibge = f.cod_ibge_favorecido
            JOIN eleitos e ON e.sq_candidato = f.sq_candidato
            WHERE f.ano >= %s AND m.lat IS NOT NULL
            GROUP BY 1,2 HAVING SUM(f.valor_recebido) > 0
        ), por_dep AS (
            SELECT d.sq_candidato,
                   SUM(d.valor * earth_distance(ll_to_earth(c.lat, c.lon),
                       ll_to_earth(m.lat, m.lon)) / 1000) / SUM(d.valor) AS km
            FROM dinheiro d
            JOIN centro c ON c.sq_candidato = d.sq_candidato
            JOIN municipio m ON m.cod_ibge = d.cod_ibge
            GROUP BY 1
        )
        SELECT COUNT(*) AS deputados,
               ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY km)::numeric) AS mediana_km,
               ROUND(AVG(km)::numeric) AS media_km,
               ROUND(percentile_cont(0.9) WITHIN GROUP (ORDER BY km)::numeric) AS p90_km,
               COUNT(*) FILTER (WHERE km > 500) AS acima_500km
        FROM por_dep
    """, (MANDATO,)))

    # 2. O município que mais recebeu dinheiro é o que mais deu votos?
    r["coincidencia"] = dict(bd.um(con, """
        WITH eleitos AS (
            SELECT sq_candidato FROM deputado WHERE situacao LIKE 'ELEITO%%'
        ), topo_voto AS (
            SELECT DISTINCT ON (v.sq_candidato) v.sq_candidato, m.cod_ibge
            FROM voto_municipio v
            JOIN municipio m ON m.cod_tse = v.cod_municipio_tse
            JOIN eleitos e ON e.sq_candidato = v.sq_candidato
            ORDER BY v.sq_candidato, v.votos DESC
        ), topo_dinheiro AS (
            SELECT DISTINCT ON (f.sq_candidato) f.sq_candidato,
                   f.cod_ibge_favorecido AS cod_ibge
            FROM (SELECT sq_candidato, cod_ibge_favorecido, SUM(valor_recebido) AS v
                  FROM vw_favorecido_deputado
                  WHERE ano >= %s AND cod_ibge_favorecido IS NOT NULL
                  GROUP BY 1,2) f
            JOIN eleitos e ON e.sq_candidato = f.sq_candidato
            ORDER BY f.sq_candidato, f.v DESC
        )
        SELECT COUNT(*) AS com_os_dois,
               COUNT(*) FILTER (WHERE tv.cod_ibge = td.cod_ibge) AS coincidem
        FROM topo_voto tv JOIN topo_dinheiro td USING (sq_candidato)
    """, (MANDATO,)))

    # 3. Dispersão do voto: quantos municípios somam metade da votação.
    #    É a medida de quão "sem endereço" é o mandato.
    r["dispersao"] = dict(bd.um(con, """
        WITH eleitos AS (
            SELECT sq_candidato FROM deputado WHERE situacao LIKE 'ELEITO%%'
        ), ordenado AS (
            SELECT v.sq_candidato, v.votos,
                   SUM(v.votos) OVER (PARTITION BY v.sq_candidato
                                      ORDER BY v.votos DESC) AS acum,
                   SUM(v.votos) OVER (PARTITION BY v.sq_candidato) AS total,
                   ROW_NUMBER() OVER (PARTITION BY v.sq_candidato
                                      ORDER BY v.votos DESC) AS pos
            FROM voto_municipio v JOIN eleitos e USING (sq_candidato)
        ), meia AS (
            SELECT sq_candidato, MIN(pos) AS municipios
            FROM ordenado WHERE acum >= total * 0.5 GROUP BY 1
        )
        SELECT ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY municipios)::numeric) AS mediana,
               MAX(municipios) AS maximo, COUNT(*) AS deputados FROM meia
    """))

    # 4. Opacidade do destino planejado.
    r["opacidade"] = dict(bd.um(con, """
        SELECT ROUND(100.0 * SUM(empenhado) FILTER (WHERE cod_ibge IS NULL)
                     / NULLIF(SUM(empenhado),0), 1) AS pct_sem_municipio,
               ROUND(SUM(empenhado) FILTER (WHERE cod_ibge IS NULL)/1e9, 1) AS bilhoes_sem_municipio
        FROM emenda WHERE ano >= %s
    """, (MANDATO,)))

    # 5. Quanto do dinheiro não tem deputado individual a quem cobrar.
    r["sem_autor"] = dict(bd.um(con, """
        SELECT ROUND(100.0 * SUM(e.empenhado) FILTER (WHERE a.sq_candidato IS NULL)
                     / NULLIF(SUM(e.empenhado),0), 1) AS pct,
               ROUND(SUM(e.empenhado) FILTER (WHERE a.sq_candidato IS NULL)/1e9, 1) AS bilhoes
        FROM emenda e LEFT JOIN autor a ON a.cod_autor = e.cod_autor
        WHERE e.ano >= %s
    """, (MANDATO,)))

    # 6. Volume por deputado, para dar escala ao leitor.
    r["volume"] = dict(bd.um(con, """
        WITH por_dep AS (
            SELECT e.sq_candidato, SUM(e.empenhado) AS v
            FROM vw_emenda_deputado e JOIN deputado d USING (sq_candidato)
            WHERE d.situacao LIKE 'ELEITO%%' AND e.ano = 2025
            GROUP BY 1 HAVING SUM(e.empenhado) > 0
        )
        SELECT COUNT(*) AS deputados,
               ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY v))::numeric/1e6, 1) AS mediana_milhoes
        FROM por_dep
    """))

    r["fontes"] = [dict(x) for x in con.cursor().connection.cursor().execute(
        "SELECT 1") or []] if False else None
    with con.cursor() as cur:
        cur.execute("""SELECT DISTINCT ON (fonte_id) fonte_id, arquivo, sha256,
                              baixado_em FROM snapshot WHERE ingerido_em IS NOT NULL
                       ORDER BY fonte_id, baixado_em DESC""")
        r["fontes"] = [dict(x) for x in cur.fetchall()]
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = stats(bd.conectar())
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        return 0
    d, c, disp = r["distancia"], r["coincidencia"], r["dispersao"]
    print(f"""
DISTÂNCIA entre o centro do voto e o destino do dinheiro ({d['deputados']} deputados)
  mediana {d['mediana_km']} km · média {d['media_km']} km · 10% piores acima de {d['p90_km']} km
  {d['acima_500km']} deputados com média acima de 500 km

O MUNICÍPIO QUE MAIS RECEBEU é o que mais deu votos?
  sim em {c['coincidem']} de {c['com_os_dois']} deputados
  ({100*c['coincidem']/c['com_os_dois']:.0f}%)

DISPERSÃO DO VOTO (municípios necessários para somar metade da votação)
  mediana {disp['mediana']} municípios · máximo {disp['maximo']} · base {disp['deputados']}

OPACIDADE
  {r['opacidade']['pct_sem_municipio']}% do empenhado não informa município
  (R$ {r['opacidade']['bilhoes_sem_municipio']} bi)
  {r['sem_autor']['pct']}% não tem deputado individual identificável
  (R$ {r['sem_autor']['bilhoes']} bi)

ESCALA
  mediana de R$ {r['volume']['mediana_milhoes']} mi por deputado em 2025
""")


if __name__ == "__main__":
    raise SystemExit(main())
