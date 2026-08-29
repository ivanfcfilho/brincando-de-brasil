#!/usr/bin/env python3
"""Ingere um snapshot da base de emendas (CGU) no Postgres, com diff.

Duas visões, ambas do mesmo ZIP (um hash, uma proveniência):
  EmendasParlamentares.csv                destino planejado
  EmendasParlamentares_PorFavorecido.csv  execução — quem recebeu, por município

O estado atual é substituído a cada snapshot; o que se acumula é o DIFF, na
tabela `mudanca`. Guardar 1,4 milhão de linhas por dia seria desperdício;
guardar "neste dia, este empenho subiu de A para B" é o produto.

Uso:
    python3.13 pipeline/ingest_emendas.py [--zip data/raw/EmendasParlamentares.zip]
"""
import argparse
import csv
import hashlib
import io
import os
import sys
import zipfile
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
from fontes import FONTES, caminho
from nomes import (carregar_aliases, carregar_aliases_municipios, casar_autor,
                   chave_municipio, indice_por_nome, norm, parse_valor)

COLS_EMENDA = ("chave codigo_emenda ano tipo cod_autor numero localidade cod_ibge "
               "municipio uf cod_funcao nome_funcao cod_subfuncao nome_subfuncao "
               "cod_acao nome_acao plano_orcamentario empenhado liquidado pago "
               "rp_inscritos rp_cancelados rp_pagos snapshot_id").split()

COLS_FAV = ("chave codigo_emenda cod_autor numero tipo ano_mes ano cod_favorecido "
            "favorecido natureza_juridica tipo_favorecido uf_favorecido "
            "municipio_favorecido cod_ibge_favorecido valor_recebido "
            "snapshot_id").split()


def mapa_municipios(con):
    """(UF, chave tolerante) → código IBGE, para resolver o município do
    favorecido, que a CGU só entrega por nome."""
    with con.cursor() as cur:
        cur.execute("SELECT cod_ibge, nome, uf FROM municipio")
        mapa = {(r["uf"], chave_municipio(r["nome"])): r["cod_ibge"]
                for r in cur.fetchall()}
    # Os apelidos entram pela mesma chave, para que renomeação oficial
    # (Açu→Assú, Embu→Embu das Artes) resolva aqui também.
    for k, cod in carregar_aliases_municipios().items():
        uf, nome = k.split("|", 1)
        mapa[(uf, chave_municipio(nome))] = cod
    return mapa


def chave(partes, ocorrencias):
    """Hash estável da chave natural + contador de ocorrência.

    A chave natural não é perfeitamente única: 32 linhas em 78 mil repetem
    (todas com 'Sem informação' em código de emenda e município). O contador
    desempata sem inventar identidade nem descartar linha.
    """
    base = "|".join(p or "" for p in partes)
    n = ocorrencias[base]
    ocorrencias[base] += 1
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]
    return f"{h}#{n}" if n else h


def _int(s):
    s = (s or "").strip()
    return int(s) if s.isdigit() else None


def ler_planejado(z, snap_id, autores):
    ocorr = Counter()
    with z.open("EmendasParlamentares.csv") as fh:
        r = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        r.fieldnames = [f.strip() for f in r.fieldnames]
        for row in r:
            g = row.get
            cod_autor = (g("Código do Autor da Emenda") or "").strip()
            autores[cod_autor][norm(g("Nome do Autor da Emenda"))] += 1
            k = chave((g("Código da Emenda"), g("Código Município IBGE"),
                       g("Localidade de aplicação do recurso"), g("Código Ação"),
                       g("Código Plano Orçamentário"), g("Código Função"),
                       g("Código Subfunção"), g("Código Programa")), ocorr)
            yield (k, g("Código da Emenda"), _int(g("Ano da Emenda")),
                   g("Tipo de Emenda"), cod_autor, g("Número da emenda"),
                   g("Localidade de aplicação do recurso"),
                   _int(g("Código Município IBGE")), norm(g("Município")), norm(g("UF")),
                   g("Código Função"), g("Nome Função"),
                   g("Código Subfunção"), g("Nome Subfunção"),
                   g("Código Ação"), g("Nome Ação"), g("Nome Plano Orçamentário"),
                   parse_valor(g("Valor Empenhado")), parse_valor(g("Valor Liquidado")),
                   parse_valor(g("Valor Pago")),
                   parse_valor(g("Valor Restos A Pagar Inscritos")),
                   parse_valor(g("Valor Restos A Pagar Cancelados")),
                   parse_valor(g("Valor Restos A Pagar Pagos")), snap_id)


def ler_favorecidos(z, snap_id, autores, mapa, faltantes):
    ocorr = Counter()
    with z.open("EmendasParlamentares_PorFavorecido.csv") as fh:
        r = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"), delimiter=";")
        r.fieldnames = [f.strip() for f in r.fieldnames]
        for row in r:
            g = row.get
            cod_autor = (g("Código do Autor da Emenda") or "").strip()
            autores[cod_autor][norm(g("Nome do Autor da Emenda"))] += 1
            am = (g("Ano/Mês") or "").strip()
            k = chave((g("Código da Emenda"), am, g("Código do Favorecido"),
                       g("UF Favorecido"), g("Município Favorecido")), ocorr)
            uf_fav = norm(g("UF Favorecido"))
            mun_fav = norm(g("Município Favorecido"))
            cod_ibge = mapa.get((uf_fav, chave_municipio(mun_fav)))
            if cod_ibge is None and mun_fav and mun_fav not in ("MULTIPLO", "SEM INFORMACAO"):
                faltantes[(uf_fav, mun_fav)] += 1
            yield (k, g("Código da Emenda"), cod_autor, g("Número da emenda"),
                   g("Tipo de Emenda"), am,
                   int(am[:4]) if am[:4].isdigit() else None,
                   g("Código do Favorecido"), g("Favorecido"),
                   g("Natureza Jurídica"), g("Tipo Favorecido"),
                   uf_fav, mun_fav, cod_ibge,
                   parse_valor(g("Valor Recebido")), snap_id)


def diff(con, tabela, stg, campos_valor, snap_id, uf_col, mun_col, snap_ant):
    """Escreve em `mudanca` o que entrou, saiu e mudou de valor.

    A carga inicial não gera feed: numa tabela vazia todas as 848 mil linhas
    seriam "novas", e o resumo do dia zero afogaria o sinal real dos dias
    seguintes. O que interessa é a variação contra um estado anterior.
    """
    principal = campos_valor[0]
    if bd.contar(con, tabela) == 0:
        return 0
    with con.cursor() as cur:
        # Idempotência por PAR de snapshots: reingerir o mesmo arquivo
        # reescreve só a transição (N→N), sem tocar na (N-1→N) verdadeira.
        cur.execute("DELETE FROM mudanca WHERE snapshot_anterior IS NOT DISTINCT FROM %s "
                    "AND snapshot_id=%s AND tabela=%s", (snap_ant, snap_id, tabela))
        cur.execute(f"""
            INSERT INTO mudanca (snapshot_anterior, snapshot_id, tabela, chave, tipo,
                                 campo, valor_antes, valor_depois, cod_autor, uf, municipio)
            SELECT %s, %s, %s, n.chave, 'nova', %s, 0, n.{principal},
                   n.cod_autor, n.{uf_col}, n.{mun_col}
            FROM {stg} n LEFT JOIN {tabela} a USING (chave)
            WHERE a.chave IS NULL AND n.{principal} <> 0
        """, (snap_ant, snap_id, tabela, principal))
        cur.execute(f"""
            INSERT INTO mudanca (snapshot_anterior, snapshot_id, tabela, chave, tipo,
                                 campo, valor_antes, valor_depois, cod_autor, uf, municipio)
            SELECT %s, %s, %s, a.chave, 'removida', %s, a.{principal}, 0,
                   a.cod_autor, a.{uf_col}, a.{mun_col}
            FROM {tabela} a LEFT JOIN {stg} n USING (chave)
            WHERE n.chave IS NULL
        """, (snap_ant, snap_id, tabela, principal))
        # Um registro por campo monetário que mexeu.
        for campo in campos_valor:
            cur.execute(f"""
                INSERT INTO mudanca (snapshot_anterior, snapshot_id, tabela, chave, tipo,
                                     campo, valor_antes, valor_depois, cod_autor, uf, municipio)
                SELECT %s, %s, %s, n.chave, 'alterada', %s, a.{campo}, n.{campo},
                       n.cod_autor, n.{uf_col}, n.{mun_col}
                FROM {stg} n JOIN {tabela} a USING (chave)
                WHERE a.{campo} IS DISTINCT FROM n.{campo}
            """, (snap_ant, snap_id, tabela, campo))
        cur.execute("SELECT COUNT(*) AS c FROM mudanca WHERE "
                    "snapshot_anterior IS NOT DISTINCT FROM %s AND snapshot_id=%s "
                    "AND tabela=%s", (snap_ant, snap_id, tabela))
        return cur.fetchone()["c"]



def substituir(con, tabela, stg, cols):
    with con.cursor() as cur:
        cur.execute(f"TRUNCATE {tabela}")
        cur.execute(f"INSERT INTO {tabela} ({','.join(cols)}) "
                    f"SELECT {','.join(cols)} FROM {stg}")


def sincronizar_autores(con, autores):
    """Catálogo cod_autor → nome, coletado durante a leitura do ZIP.

    O código do autor é estável; a grafia do nome não (89 dos ~1.573 autores
    aparecem escritos de mais de um jeito na mesma base). Guardamos a grafia
    mais frequente só para exibição — o que junta com o TSE é o código.
    Autor já conhecido não tem o nome sobrescrito: o vínculo humano vale mais
    que a grafia do dia.
    """
    linhas = [(cod, g.most_common(1)[0][0], g.most_common(1)[0][0])
              for cod, g in autores.items() if cod and g]
    with con.cursor() as cur:
        cur.executemany("INSERT INTO autor (cod_autor, nome, nome_norm) "
                        "VALUES (%s,%s,%s) ON CONFLICT (cod_autor) DO NOTHING", linhas)
    con.commit()
    return bd.contar(con, "autor")


def vincular_autores(con):
    """Casa cod_autor → sq_candidato e persiste. Respeita conferido = TRUE."""
    with con.cursor() as cur:
        # O nome parlamentar da Câmara entra como terceira grafia conhecida.
        # É justamente ele que costuma bater com o autor da emenda na CGU
        # quando o TSE diverge ('DEPUTADO DAL' no TSE x 'DAL BARRETO' na CGU).
        cur.execute("""
            SELECT d.sq_candidato, d.nome, d.nome_urna, c.nome_eleitoral,
                   d.situacao LIKE 'ELEITO%' AS eleito
            FROM deputado d
            LEFT JOIN nome_camara c ON c.id_camara = d.id_camara
        """)
        linhas = cur.fetchall()
    cands = [(r["sq_candidato"], r["nome"], r["nome_urna"]) for r in linhas]
    total = bd.contar(con, "autor")
    if not cands:
        return 0, total
    idx = indice_por_nome(
        (r["sq_candidato"], r["nome"], r["nome_urna"], r["nome_eleitoral"],
         r["eleito"]) for r in linhas)
    aliases = carregar_aliases()
    with con.cursor() as cur:
        cur.execute("SELECT cod_autor, nome_norm FROM autor WHERE NOT conferido")
        pendentes = cur.fetchall()
        for a in pendentes:
            sq, metodo = casar_autor(a["nome_norm"], idx, cands, aliases)
            cur.execute("UPDATE autor SET sq_candidato=%s, metodo_match=%s, "
                        "vinculado_em=now() WHERE cod_autor=%s AND NOT conferido",
                        (sq, metodo if sq else None, a["cod_autor"]))
    con.commit()
    v = bd.um(con, "SELECT COUNT(*) AS c FROM autor WHERE sq_candidato IS NOT NULL")["c"]
    return v, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default=caminho(FONTES["cgu_emendas"]))
    ap.add_argument("--forcar", action="store_true",
                    help="reingere mesmo que o snapshot já conste ingerido")
    args = ap.parse_args()

    if not os.path.exists(args.zip):
        sys.exit(f"arquivo não encontrado: {args.zip} "
                 f"(rode: python3.13 pipeline/atualizar.py)")

    con = bd.conectar()
    bd.init(con)
    fonte = FONTES["cgu_emendas"]
    bd.registrar_fonte(con, fonte)
    snap, ja = bd.registrar_snapshot(con, fonte.id, args.zip)
    if ja and snap["ingerido_em"] and not args.forcar:
        print(f"snapshot {snap['id']} (sha {snap['sha256'][:12]}) já ingerido "
              f"— nada a fazer (use --forcar)")
        return 0
    print(f"snapshot {snap['id']} sha={snap['sha256'][:12]} "
          f"publicado={snap['publicado_em'] or '—'}")

    # O snapshot anterior é o que carimbou as linhas hoje no banco.
    ant_e = bd.um(con, "SELECT MAX(snapshot_id) AS s FROM emenda")["s"]
    ant_f = bd.um(con, "SELECT MAX(snapshot_id) AS s FROM emenda_favorecido")["s"]
    autores = defaultdict(Counter)
    faltantes = Counter()
    mapa = mapa_municipios(con)
    if not mapa:
        print("  aviso: tabela `municipio` vazia — o município do favorecido "
              "ficará sem código IBGE (rode ingest_municipios.py e reingira)")
    with zipfile.ZipFile(args.zip) as z, con.cursor() as cur:
        cur.execute("CREATE TEMP TABLE stg_emenda (LIKE emenda) ON COMMIT DROP")
        cur.execute("CREATE TEMP TABLE stg_fav (LIKE emenda_favorecido) ON COMMIT DROP")

        print("[1/4] destino planejado …", flush=True)
        n_e = bd.copiar(con, "stg_emenda", COLS_EMENDA,
                        ler_planejado(z, snap["id"], autores))
        m_e = diff(con, "emenda", "stg_emenda", ("empenhado", "pago"),
                   snap["id"], "uf", "municipio", ant_e)
        substituir(con, "emenda", "stg_emenda", COLS_EMENDA)
        print(f"      {n_e:,} linhas, {m_e:,} mudanças".replace(",", "."))

        print("[2/4] execução por favorecido …", flush=True)
        n_f = bd.copiar(con, "stg_fav", COLS_FAV,
                        ler_favorecidos(z, snap["id"], autores, mapa, faltantes))
        m_f = diff(con, "emenda_favorecido", "stg_fav", ("valor_recebido",),
                   snap["id"], "uf_favorecido", "municipio_favorecido", ant_f)
        substituir(con, "emenda_favorecido", "stg_fav", COLS_FAV)
        print(f"      {n_f:,} linhas, {m_f:,} mudanças".replace(",", "."))
        if faltantes:
            top = ", ".join(f"{m}/{u}" for (u, m), _ in faltantes.most_common(8))
            print(f"      {len(faltantes)} municípios de favorecido sem código "
                  f"IBGE (ficam sem distância): {top}")
    con.commit()

    print("[3/4] catálogo de autores …", flush=True)
    print(f"      {sincronizar_autores(con, autores)} autores")

    print("[4/4] vinculando autores ao TSE …", flush=True)
    v, t = vincular_autores(con)
    print(f"      {v}/{t} autores vinculados a deputado eleito/suplente")

    bd.marcar_ingerido(con, snap["id"], n_e + n_f)
    print(f"ok: snapshot {snap['id']} ingerido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
