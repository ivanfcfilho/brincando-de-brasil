#!/usr/bin/env python3
"""Vincula autor de emenda ↔ deputado do TSE, e produz a fila de revisão.

O casamento por nome é a fragilidade conhecida do projeto. Este comando torna
a fragilidade visível em vez de escondê-la:

  - o vínculo por nome exato é aceito automaticamente;
  - o vínculo por tokens entra na FILA DE REVISÃO — ele acerta a maioria, mas
    erra o suficiente para não ser publicável sem olho humano;
  - deputado ligado a mais de um código de autor também entra na fila: às
    vezes é a mesma pessoa em duas legislaturas (legítimo), às vezes é
    homônimo (erro grave).

Confirmar um vínculo marca conferido = TRUE, e a partir daí nenhuma
reingestão o sobrescreve.

Uso:
    python3.13 pipeline/vincular.py                     # revincula e mostra a fila
    python3.13 pipeline/vincular.py --revisar           # só a fila
    python3.13 pipeline/vincular.py --confirmar 4309    # marca como conferido
    python3.13 pipeline/vincular.py --desfazer 2732     # remove vínculo errado
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
from ingest_emendas import vincular_autores

FILA = """
    SELECT a.cod_autor, a.nome AS autor_emenda, a.metodo_match,
           d.nome_urna, d.nome AS nome_civil, d.uf, d.partido, d.situacao,
           COUNT(*) OVER (PARTITION BY a.sq_candidato) AS codigos_no_mesmo_deputado
    FROM autor a JOIN deputado d ON d.sq_candidato = a.sq_candidato
    WHERE NOT a.conferido
      AND (a.metodo_match = 'tokens'
           OR EXISTS (SELECT 1 FROM autor b
                      WHERE b.sq_candidato = a.sq_candidato
                        AND b.cod_autor <> a.cod_autor))
    ORDER BY d.situacao, a.nome
"""


def revisar(con, limite=None):
    with con.cursor() as cur:
        cur.execute(FILA)
        linhas = cur.fetchall()
    print(f"\nFILA DE REVISÃO — {len(linhas)} vínculos a confirmar antes de publicar\n")
    print(f"{'cod':>6}  {'autor da emenda':28s} {'método':7s} "
          f"{'deputado (urna)':24s} {'nome civil':38s} UF  situação")
    print("-" * 132)
    for r in linhas[:limite]:
        marca = "!" if r["codigos_no_mesmo_deputado"] > 1 else " "
        print(f"{r['cod_autor']:>6}{marca} {r['autor_emenda'][:28]:28s} "
              f"{(r['metodo_match'] or '—'):7s} {r['nome_urna'][:24]:24s} "
              f"{r['nome_civil'][:38]:38s} {r['uf']:3s} {r['situacao']}")
    if limite and len(linhas) > limite:
        print(f"... e mais {len(linhas)-limite}")
    print("\n  ! = o deputado está ligado a mais de um código de autor")
    print("  confirmar: python3.13 pipeline/vincular.py --confirmar <cod>")
    print("  desfazer : python3.13 pipeline/vincular.py --desfazer  <cod>")
    return linhas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--revisar", action="store_true", help="não revincula, só lista")
    ap.add_argument("--confirmar", metavar="COD")
    ap.add_argument("--desfazer", metavar="COD")
    ap.add_argument("--limite", type=int, default=40)
    args = ap.parse_args()
    con = bd.conectar()

    if args.confirmar:
        with con.cursor() as cur:
            cur.execute("UPDATE autor SET conferido = TRUE, metodo_match = 'manual' "
                        "WHERE cod_autor = %s RETURNING nome, sq_candidato", (args.confirmar,))
            r = cur.fetchone()
        con.commit()
        print(f"confirmado: {args.confirmar} = {r['nome']} → {r['sq_candidato']}" if r
              else f"código {args.confirmar} não encontrado")
        return 0

    if args.desfazer:
        with con.cursor() as cur:
            cur.execute("UPDATE autor SET sq_candidato = NULL, metodo_match = NULL, "
                        "conferido = TRUE WHERE cod_autor = %s RETURNING nome", (args.desfazer,))
            r = cur.fetchone()
        con.commit()
        # conferido = TRUE mantém a decisão humana: a reingestão não vai
        # recriar o vínculo que alguém desfez de propósito.
        print(f"vínculo removido e travado: {args.desfazer} = {r['nome']}" if r
              else f"código {args.desfazer} não encontrado")
        return 0

    if not args.revisar:
        v, t = vincular_autores(con)
        print(f"{v}/{t} autores vinculados")
        el = bd.um(con, """SELECT COUNT(DISTINCT d.sq_candidato) AS c FROM deputado d
                           JOIN autor a ON a.sq_candidato = d.sq_candidato
                           WHERE d.situacao LIKE 'ELEITO%'""")["c"]
        print(f"{el}/513 deputados federais eleitos com autoria de emenda identificada")
    revisar(con, args.limite)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
