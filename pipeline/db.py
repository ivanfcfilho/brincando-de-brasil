#!/usr/bin/env python3
"""Acesso ao Postgres: conexão, schema, proveniência e carga em massa.

A credencial vem de CT_DSN (arquivo .env na raiz, fora do git). Nada de senha
no código — o repositório é público por vocação.

Uso:
    python3.13 pipeline/db.py --init      # cria/atualiza o schema
    python3.13 pipeline/db.py --status    # o que há no banco
"""
import argparse
import csv
import hashlib
import io
import os

import psycopg2
import psycopg2.extras

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(RAIZ, "db", "schema.sql")
ENV_PATH = os.path.join(RAIZ, ".env")


def carregar_env(path=ENV_PATH):
    """Lê o .env para o ambiente sem sobrescrever o que já está definido."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            k, v = linha.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def dsn():
    carregar_env()
    d = os.environ.get("CT_DSN")
    if not d:
        raise SystemExit(
            "CT_DSN não definido. Crie o arquivo .env na raiz com:\n"
            "  CT_DSN=postgresql://usuario:senha@127.0.0.1:5433/codigo_transicao")
    return d


def conectar(d=None):
    con = psycopg2.connect(d or dsn(), cursor_factory=psycopg2.extras.DictCursor)
    con.autocommit = False
    return con


def init(con):
    """Idempotente: todo o schema é CREATE ... IF NOT EXISTS / OR REPLACE."""
    with open(SCHEMA_PATH, encoding="utf-8") as f, con.cursor() as cur:
        cur.execute(f.read())
    con.commit()


def sha256_arquivo(path, bloco=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(bloco):
            h.update(chunk)
    return h.hexdigest()


def um(con, sql, params=None):
    """Primeira linha da consulta.

    Sem parâmetros, executa sem interpolação: do contrário um '%' literal
    (LIKE 'ELEITO%') seria lido como placeholder e estouraria.
    """
    with con.cursor() as cur:
        cur.execute(sql, params) if params else cur.execute(sql)
        return cur.fetchone()


def contar(con, tabela):
    return um(con, f"SELECT COUNT(*) AS c FROM {tabela}")["c"]


# ---------------------------------------------------------------- carga em massa

class _IterFile(io.RawIOBase):
    """Adapta um gerador de bytes a um objeto file-like, para alimentar o
    COPY sem materializar 1,3 milhão de linhas na memória."""

    def __init__(self, gerador):
        self.gerador = gerador
        self.buf = b""

    def readable(self):
        return True

    def readinto(self, destino):
        while len(self.buf) < len(destino):
            try:
                self.buf += next(self.gerador)
            except StopIteration:
                break
        n = min(len(destino), len(self.buf))
        destino[:n] = self.buf[:n]
        self.buf = self.buf[n:]
        return n


def copiar(con, tabela, cols, linhas):
    """COPY FROM STDIN. Devolve o número de linhas copiadas.

    Ordens de grandeza mais rápido que executemany — a base PorFavorecido tem
    1,3 milhão de linhas e é recarregada a cada snapshot.
    """
    contador = [0]

    def gerar():
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        for linha in linhas:
            w.writerow(linha)
            contador[0] += 1
            if buf.tell() > (1 << 20):
                yield buf.getvalue().encode("utf-8")
                buf.seek(0); buf.truncate(0)
        if buf.tell():
            yield buf.getvalue().encode("utf-8")

    sql = (f"COPY {tabela} ({','.join(cols)}) FROM STDIN "
           f"WITH (FORMAT csv, NULL '')")
    with con.cursor() as cur:
        cur.copy_expert(sql, _IterFile(gerar()))
    return contador[0]


# ------------------------------------------------------------------ proveniência

def registrar_fonte(con, fonte):
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO fonte (id, descricao, url, periodicidade) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (id) DO UPDATE SET descricao=EXCLUDED.descricao, "
            "url=EXCLUDED.url, periodicidade=EXCLUDED.periodicidade",
            (fonte.id, fonte.descricao, fonte.url, fonte.periodicidade))
    con.commit()


def registrar_checagem(con, fonte_id, cab, mudou, erro=None):
    cab = cab or {}
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO checagem (fonte_id, etag, last_modified, tamanho, mudou, erro) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (fonte_id, cab.get("etag"), cab.get("last_modified"),
             cab.get("tamanho"), bool(mudou), erro))
    con.commit()


def ultimo_snapshot(con, fonte_id):
    return um(con, "SELECT * FROM snapshot WHERE fonte_id=%s "
                   "ORDER BY baixado_em DESC LIMIT 1", (fonte_id,))


def registrar_snapshot(con, fonte_id, arquivo, cab=None):
    """Cria (ou recupera) o snapshot correspondente ao conteúdo do arquivo.

    Devolve (row, ja_existia). A identidade é o sha256: rebaixar um arquivo
    idêntico não cria snapshot novo nem dispara reingestão.
    """
    sha = sha256_arquivo(arquivo)
    existente = um(con, "SELECT * FROM snapshot WHERE fonte_id=%s AND sha256=%s",
                   (fonte_id, sha))
    if existente:
        return existente, True
    cab = cab or {}
    with con.cursor() as cur:
        cur.execute(
            "INSERT INTO snapshot (fonte_id, publicado_em, etag, tamanho, sha256, arquivo) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
            (fonte_id, cab.get("last_modified"), cab.get("etag"),
             os.path.getsize(arquivo), sha, os.path.relpath(arquivo, RAIZ)))
        row = cur.fetchone()
    con.commit()
    return row, False


def marcar_ingerido(con, snapshot_id, linhas):
    with con.cursor() as cur:
        cur.execute("UPDATE snapshot SET ingerido_em=now(), linhas=%s WHERE id=%s",
                    (linhas, snapshot_id))
    con.commit()


def status(con):
    linhas = []
    with con.cursor() as cur:
        cur.execute("SELECT * FROM fonte ORDER BY id")
        for f in cur.fetchall():
            s = ultimo_snapshot(con, f["id"])
            c = um(con, "SELECT COUNT(*) AS n FROM checagem WHERE fonte_id=%s",
                   (f["id"],))["n"]
            quando = s["baixado_em"].strftime("%Y-%m-%d %H:%M") if s else "—"
            linhas.append(f"{f['id']:20s} {f['periodicidade']:8s} snapshot={quando} "
                          f"linhas={s['linhas'] if s and s['linhas'] else '—'} "
                          f"checagens={c}")
    for t in ("deputado", "voto_municipio", "autor", "emenda",
              "emenda_favorecido", "municipio", "mudanca"):
        linhas.append(f"{t:20s} {contar(con, t):>12,} linhas".replace(",", "."))
    tot = contar(con, "autor")
    if tot:
        v = um(con, "SELECT COUNT(*) AS c FROM autor WHERE sq_candidato IS NOT NULL")["c"]
        linhas.append(f"{'autores vinculados':20s} {v}/{tot}")
    return "\n".join(linhas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()
    con = conectar()
    if args.init or not args.status:
        init(con)
        print("schema aplicado")
    if args.status:
        print(status(con))


if __name__ == "__main__":
    main()
