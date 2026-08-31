#!/usr/bin/env python3
"""Exporta as tabelas para arquivos .csv.gz, para levar a outro servidor.

Por que não `pg_dump`: a máquina de desenvolvimento roda **PostgreSQL 18** e o
servidor roda **16**. O `pg_dump` se recusa a falar com um servidor mais novo
que ele ("aborting because of server version mismatch"), e um dump gerado pelo
18 pode conter sintaxe que o 16 não entende.

`COPY … TO STDOUT` em formato texto não tem esse problema: é o mesmo formato
há muitas versões, para os dois lados. E o schema não vem no dump — vem do
`db/schema.sql` do próprio repositório, aplicado com `db.py --init`. Assim o
banco de produção é construído pela MESMA definição que o de desenvolvimento,
em vez de por um retrato dele.

    python3.13 deploy/exportar_dados.py
    scp -r data/export kakashi@servidor:~/brincandodebrasil/data/
"""
import gzip
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import db as bd

# Ordem que respeita as chaves estrangeiras: quem é apontado vem antes de quem
# aponta. Carregar `emenda` antes de `snapshot` violaria a FK e abortaria a
# carga no meio, deixando o banco pela metade.
TABELAS = [
    "fonte", "snapshot", "checagem", "municipio", "deputado",
    "voto_municipio", "autor", "emenda", "emenda_favorecido", "ideb",
    "mudanca",
]

DESTINO = os.path.join(bd.RAIZ, "data", "export")


def main():
    os.makedirs(DESTINO, exist_ok=True)
    con = bd.conectar()
    total = 0
    for tabela in TABELAS:
        n = bd.contar(con, tabela)
        caminho = os.path.join(DESTINO, f"{tabela}.csv.gz")
        print(f"  {tabela:20s} {n:>10,} linhas …", end="", flush=True)
        with gzip.open(caminho, "wb", compresslevel=6) as saida, con.cursor() as cur:
            cur.copy_expert(f"COPY {tabela} TO STDOUT WITH (FORMAT csv)", saida)
        mb = os.path.getsize(caminho) / 1e6
        print(f" {mb:>7.1f} MB")
        total += n
    con.close()
    print(f"\n{total:,} linhas em {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
