#!/usr/bin/env python3
"""Ingere a votação nominal por município (TSE) no Postgres.

Roda uma vez por eleição — o resultado de 2022 não muda mais. Por isso o job
diário não toca nesta fonte (periodicidade 'eleicao' em fontes.py).

Guardamos eleitos e suplentes: suplente assume, e quando assume passa a ter
emenda. Não-eleitos ficam de fora (multiplicariam as linhas por ~20 sem
responder à pergunta do projeto) — use --todos se quiser o universo completo.

Uso:
    python3.13 pipeline/ingest_tse.py [--uf TODAS] [--ano 2022]
"""
import argparse
import csv
import io
import os
import sys
import zipfile
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
from fontes import FONTES, caminho
from nomes import norm

SITUACOES = ("ELEITO", "SUPLENTE")   # prefixos de DS_SIT_TOT_TURNO

# O ZIP traz, além das 27 UFs, dois agregados nacionais que REPETEM todas
# elas. Lê-los dobra o trabalho e mistura estados num arquivo só.
AGREGADOS = ("_BR.csv", "_BRASIL.csv")

COLS_DEP = ("sq_candidato ano_eleicao uf nome nome_urna partido situacao "
            "snapshot_id").split()
COLS_VOTO = ("sq_candidato ano_eleicao uf cod_municipio_tse municipio_norm "
             "votos snapshot_id").split()


def ler_uf(z, membro, ano, snap_id, situacoes):
    """Devolve (deputados, votos) já agregados por município."""
    votos = defaultdict(int)
    info = {}
    with z.open(membro) as fh:
        r = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        for row in r:
            if norm(row["DS_CARGO"]) != "DEPUTADO FEDERAL":
                continue
            sit = norm(row["DS_SIT_TOT_TURNO"])
            if situacoes and not sit.startswith(situacoes):
                continue
            sq = row["SQ_CANDIDATO"]
            # A votação vem por zona eleitoral; o município é a granularidade
            # que casa com o destino da emenda, então agregamos aqui.
            # A UF vem de cada linha, nunca do arquivo: derivar por arquivo
            # fazia o agregado nacional carimbar uma única UF em milhões de
            # linhas (91% da base ficou marcada como 'ES').
            chave = (sq, row["SG_UF"], int(row["CD_MUNICIPIO"]),
                     norm(row["NM_MUNICIPIO"]))
            votos[chave] += int(row["QT_VOTOS_NOMINAIS"])
            if sq not in info:
                info[sq] = (sq, ano, row["SG_UF"], norm(row["NM_CANDIDATO"]),
                            norm(row["NM_URNA_CANDIDATO"]), row["SG_PARTIDO"],
                            sit, snap_id)
    linhas_voto = [(sq, ano, uf, cd, mun, v, snap_id)
                   for (sq, uf, cd, mun), v in votos.items()]
    return list(info.values()), linhas_voto


def gravar(con, deputados, votos):
    """COPY para staging + upsert. Reingerir a mesma UF é idempotente."""
    with con.cursor() as cur:
        cur.execute("CREATE TEMP TABLE stg_dep (LIKE deputado) ON COMMIT DROP")
        cur.execute("CREATE TEMP TABLE stg_voto (LIKE voto_municipio) ON COMMIT DROP")
    bd.copiar(con, "stg_dep", COLS_DEP, deputados)
    bd.copiar(con, "stg_voto", COLS_VOTO, votos)
    with con.cursor() as cur:
        cur.execute(f"""
            INSERT INTO deputado ({','.join(COLS_DEP)})
            SELECT {','.join(COLS_DEP)} FROM stg_dep
            ON CONFLICT (sq_candidato) DO UPDATE SET
                partido = EXCLUDED.partido,
                situacao = EXCLUDED.situacao,
                snapshot_id = EXCLUDED.snapshot_id
        """)
        cur.execute(f"""
            INSERT INTO voto_municipio ({','.join(COLS_VOTO)})
            SELECT {','.join(COLS_VOTO)} FROM stg_voto
            ON CONFLICT (sq_candidato, cod_municipio_tse) DO UPDATE SET
                votos = EXCLUDED.votos,
                uf = EXCLUDED.uf,
                municipio_norm = EXCLUDED.municipio_norm,
                snapshot_id = EXCLUDED.snapshot_id
        """)
    con.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uf", default="TODAS", help="sigla ou TODAS")
    ap.add_argument("--ano", type=int, default=2022)
    ap.add_argument("--zip")
    ap.add_argument("--todos", action="store_true",
                    help="inclui não-eleitos (multiplica as linhas por ~20)")
    ap.add_argument("--forcar", action="store_true",
                    help="reingere mesmo que o snapshot já conste ingerido")
    args = ap.parse_args()

    fonte = FONTES[f"tse_munzona_{args.ano}"]
    zip_path = args.zip or caminho(fonte)
    if not os.path.exists(zip_path):
        sys.exit(f"arquivo não encontrado: {zip_path}")

    con = bd.conectar()
    bd.init(con)
    bd.registrar_fonte(con, fonte)
    print("calculando sha256 (580 MB) …", flush=True)
    snap, ja = bd.registrar_snapshot(con, fonte.id, zip_path)
    if ja and snap["ingerido_em"] and args.uf == "TODAS" and not args.forcar:
        print(f"snapshot {snap['id']} já ingerido — nada a fazer (use --forcar)")
        return 0
    print(f"snapshot {snap['id']} sha={snap['sha256'][:12]}")

    situacoes = () if args.todos else SITUACOES
    tot_d = tot_v = 0
    with zipfile.ZipFile(zip_path) as z:
        membros = [n for n in z.namelist()
                   if n.endswith(".csv") and not n.endswith(AGREGADOS)]
        if args.uf != "TODAS":
            membros = [n for n in membros
                       if n.endswith(f"_{args.ano}_{args.uf.upper()}.csv")]
            if not membros:
                sys.exit(f"UF {args.uf} não encontrada no ZIP")
        # Uma transação por UF: uma transação única sobre 27 arquivos deixaria
        # o banco travado por minutos e o job diário esbarraria nela.
        for i, m in enumerate(sorted(membros), 1):
            deps, votos = ler_uf(z, m, args.ano, snap["id"], situacoes)
            gravar(con, deps, votos)
            tot_d += len(deps); tot_v += len(votos)
            print(f"  [{i}/{len(membros)}] {m}: {len(deps)} deputados, "
                  f"{len(votos)} pares município", flush=True)

    # Só uma carga completa marca o snapshot como ingerido: marcar depois de
    # uma UF isolada faria a carga nacional seguinte virar no-op silencioso.
    if args.uf == "TODAS":
        bd.marcar_ingerido(con, snap["id"], tot_v)
    print(f"ok: {tot_d} deputados, {tot_v} pares deputado×município")

    # O vínculo autor↔TSE depende dos dois lados; se as emendas já entraram,
    # revincula agora para não exigir uma segunda passada manual.
    if bd.contar(con, "autor"):
        from ingest_emendas import vincular_autores
        v, t = vincular_autores(con)
        print(f"revinculação: {v}/{t} autores casados com deputado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
