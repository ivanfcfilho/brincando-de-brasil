#!/usr/bin/env python3
"""Carrega os .csv.gz exportados para o banco deste servidor.

Roda DEPOIS de `python pipeline/db.py --init` — o schema vem do repositório,
não do dump. Ver o cabeçalho de `exportar_dados.py` para o porquê.

É idempotente: cada tabela é esvaziada antes de receber os dados, então rodar
duas vezes dá o mesmo resultado. `TRUNCATE … CASCADE` numa transação só, para
que uma falha no meio não deixe o banco com metade dos dados — pior que vazio
é meio cheio, porque meio cheio parece que funcionou.

    ./.venv/bin/python deploy/importar_dados.py
"""
import gzip
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "pipeline"))
import db as bd
from exportar_dados import TABELAS

ORIGEM = os.path.join(bd.RAIZ, "data", "export")


def main():
    faltando = [t for t in TABELAS
                if not os.path.exists(os.path.join(ORIGEM, f"{t}.csv.gz"))]
    if faltando:
        print(f"faltam arquivos em {ORIGEM}: {', '.join(faltando)}")
        return 1

    con = bd.conectar()
    with con.cursor() as cur:
        cur.execute(f"TRUNCATE {', '.join(TABELAS)} CASCADE")
        for tabela in TABELAS:
            caminho = os.path.join(ORIGEM, f"{tabela}.csv.gz")
            print(f"  {tabela:20s} …", end="", flush=True)
            with gzip.open(caminho, "rb") as f:
                # A primeira linha traz os nomes das colunas na ordem em que
                # foram exportadas. Copiar NOMEANDO as colunas faz a carga
                # independer da ordem física das duas pontas — que diverge
                # sempre que uma coluna nasceu de `ALTER TABLE ADD COLUMN`
                # num lado e de `CREATE TABLE` no outro.
                cabecalho = f.readline().decode("utf-8").strip()
                cols = ",".join(f'"{c.strip()}"' for c in cabecalho.split(","))
                cur.copy_expert(
                    f"COPY {tabela} ({cols}) FROM STDIN WITH (FORMAT csv)", f)
            cur.execute(f"SELECT COUNT(*) FROM {tabela}")
            print(f" {cur.fetchone()[0]:>10,} linhas")

        # As colunas de identidade foram carregadas com os valores de origem;
        # sem reposicionar a sequência, o próximo INSERT tentaria reusar id=1
        # e quebraria na chave primária.
        for tabela in ("snapshot", "checagem", "mudanca"):
            cur.execute(f"""
                SELECT setval(pg_get_serial_sequence('{tabela}', 'id'),
                              GREATEST(COALESCE((SELECT MAX(id) FROM {tabela}), 1), 1))
            """)
    con.commit()
    print("\ncarga concluída — rode `python pipeline/conferir.py`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
