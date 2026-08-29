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

    with con.cursor() as cur:
        cur.execute("""SELECT fonte_id, COUNT(*) AS c FROM snapshot
                       WHERE ingerido_em IS NOT NULL GROUP BY 1""")
        fontes = {r["fonte_id"]: r["c"] for r in cur.fetchall()}
    checar("as duas fontes têm snapshot ingerido",
           {"cgu_emendas", "tse_munzona_2022"} <= set(fontes), str(fontes))

    print(f"\n{'TUDO OK' if not falhas else 'FALHAS: ' + ', '.join(falhas)}")
    return 0 if not falhas else 1


if __name__ == "__main__":
    raise SystemExit(conferir(bd.conectar()))
