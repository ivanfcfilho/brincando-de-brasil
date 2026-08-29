#!/usr/bin/env python3
"""Relatório por UF: origem do voto × destino da emenda, direto do banco.

Antes este script lia os ZIPs a cada execução. Agora lê o Postgres: o mesmo
estado que a consulta por CEP enxerga. Isso não é só desempenho — enquanto o
relatório e a plataforma calculavam por caminhos diferentes, havia como
publicar dois números distintos para a mesma pergunta.

Princípio editorial: NENHUMA inferência. Publicamos origem dos votos, destino
da verba e a divergência percentual — a conclusão é do leitor.

Uso:
    python3.13 pipeline/cruzamento.py --uf SE [--mandato-inicio 2023]
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd

UF_NOME = {
    "AC": "ACRE", "AL": "ALAGOAS", "AP": "AMAPÁ", "AM": "AMAZONAS",
    "BA": "BAHIA", "CE": "CEARÁ", "DF": "DISTRITO FEDERAL",
    "ES": "ESPÍRITO SANTO", "GO": "GOIÁS", "MA": "MARANHÃO",
    "MT": "MATO GROSSO", "MS": "MATO GROSSO DO SUL", "MG": "MINAS GERAIS",
    "PA": "PARÁ", "PB": "PARAÍBA", "PR": "PARANÁ", "PE": "PERNAMBUCO",
    "PI": "PIAUÍ", "RJ": "RIO DE JANEIRO", "RN": "RIO GRANDE DO NORTE",
    "RS": "RIO GRANDE DO SUL", "RO": "RONDÔNIA", "RR": "RORAIMA",
    "SC": "SANTA CATARINA", "SP": "SÃO PAULO", "SE": "SERGIPE",
    "TO": "TOCANTINS",
}
SEM_MUNICIPIO = ("MULTIPLO", "SEM INFORMACAO")


def brl(v):
    return "R$ " + f"{float(v or 0):,.0f}".replace(",", ".")


def eleitos(con, uf):
    with con.cursor() as cur:
        cur.execute("""
            SELECT d.sq_candidato, d.nome_urna, d.partido, vt.total_votos
            FROM deputado d JOIN vw_votos_totais vt USING (sq_candidato)
            WHERE d.uf = %s AND d.situacao LIKE 'ELEITO%%'
            ORDER BY vt.total_votos DESC
        """, (uf,))
        return [dict(r) for r in cur.fetchall()]


def votos_por_municipio(con, sq):
    with con.cursor() as cur:
        cur.execute("SELECT municipio_norm, votos FROM voto_municipio "
                    "WHERE sq_candidato=%s ORDER BY votos DESC", (sq,))
        return [dict(r) for r in cur.fetchall()]


def emendas_por_destino(con, sq, uf, ano):
    """Classes de destino, na mesma taxonomia do piloto original:
    DENTRO (município da UF), FORA (município de outra UF),
    ESTADO (a UF, sem município definido), AMPLO (nacional/múltiplo)."""
    with con.cursor() as cur:
        cur.execute("""
            SELECT CASE
                     WHEN municipio NOT IN %(sem)s AND uf = %(uf)s THEN 'DENTRO'
                     WHEN municipio NOT IN %(sem)s                 THEN 'FORA'
                     WHEN uf = %(uf)s                              THEN 'ESTADO'
                     ELSE 'AMPLO' END AS classe,
                   CASE WHEN municipio NOT IN %(sem)s AND uf <> %(uf)s
                        THEN municipio || ' (' || uf || ')' ELSE municipio END AS destino,
                   SUM(empenhado) AS valor
            FROM vw_emenda_deputado
            WHERE sq_candidato = %(sq)s AND ano >= %(ano)s AND empenhado <> 0
            GROUP BY 1,2 ORDER BY 3 DESC
        """, {"sem": SEM_MUNICIPIO, "uf": uf, "sq": sq, "ano": ano})
        return [dict(r) for r in cur.fetchall()]


def recebido_por_municipio(con, sq, ano):
    with con.cursor() as cur:
        cur.execute("""
            SELECT uf_favorecido AS uf, municipio_favorecido AS municipio,
                   SUM(valor_recebido) AS valor
            FROM vw_favorecido_deputado
            WHERE sq_candidato=%s AND ano >= %s AND valor_recebido <> 0
            GROUP BY 1,2 ORDER BY 3 DESC
        """, (sq, ano))
        return [dict(r) for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uf", default="SE")
    ap.add_argument("--ano-eleicao", type=int, default=2022)
    ap.add_argument("--mandato-inicio", type=int, default=2023)
    args = ap.parse_args()
    uf, ano = args.uf.upper(), args.mandato_inicio

    con = bd.conectar()
    deps = eleitos(con, uf)
    if not deps:
        sys.exit(f"nenhum deputado eleito de {uf} no banco — rode ingest_tse.py")
    print(f"{len(deps)} deputados federais eleitos em {uf}")

    os.makedirs("data/out", exist_ok=True)
    os.makedirs("relatorio", exist_ok=True)
    csv_out = f"data/out/piloto_{uf}_deputado_municipio.csv"
    md_out = f"relatorio/PILOTO_{uf}.md"
    md = []
    sem_emenda = []

    with open(csv_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["deputado", "partido", "municipio", "classe_destino",
                    "votos", "pct_votos", "valor_empenhado", "pct_emendas"])
        for d in deps:
            sq, tot_v = d["sq_candidato"], d["total_votos"]
            votos = {r["municipio_norm"]: r["votos"] for r in votos_por_municipio(con, sq)}
            dest = emendas_por_destino(con, sq, uf, ano)
            tot_e = sum(float(r["valor"]) for r in dest)
            dentro = {r["destino"]: float(r["valor"]) for r in dest if r["classe"] == "DENTRO"}
            por_classe = {c: sum(float(r["valor"]) for r in dest if r["classe"] == c)
                          for c in ("DENTRO", "FORA", "ESTADO", "AMPLO")}

            universo = set(votos) | set(dentro)
            for m in sorted(universo, key=lambda m: -votos.get(m, 0)):
                v, e = votos.get(m, 0), dentro.get(m, 0.0)
                w.writerow([d["nome_urna"], d["partido"], m, "DENTRO", v,
                            round(100 * v / tot_v, 2) if tot_v else 0,
                            round(e, 2), round(100 * e / tot_e, 2) if tot_e else 0])
            for r in dest:
                if r["classe"] != "DENTRO":
                    e = float(r["valor"])
                    w.writerow([d["nome_urna"], d["partido"], r["destino"], r["classe"],
                                0, 0, round(e, 2),
                                round(100 * e / tot_e, 2) if tot_e else 0])

            md.append(f"\n## {d['nome_urna'].title()} ({d['partido']})\n")
            md.append(f"- **Votos em {args.ano_eleicao}:** {tot_v:,}".replace(",", "."))
            if not tot_e:
                sem_emenda.append(d["nome_urna"])
                md.append("- **Emendas:** nenhuma casada com este parlamentar "
                          "(licença, suplência ou grafia divergente — verificar manualmente)")
                continue
            md.append(f"- **Emendas empenhadas {ano}–2026:** {brl(tot_e)}")
            md.append(
                f"- **Destino:** {100*por_classe['DENTRO']/tot_e:.0f}% municípios do estado · "
                f"{100*por_classe['ESTADO']/tot_e:.0f}% estado sem município definido · "
                f"{100*por_classe['FORA']/tot_e:.0f}% outros estados · "
                f"{100*por_classe['AMPLO']/tot_e:.0f}% nacional/múltiplo")
            md.append("\n| Município (top-5 em votos) | % dos votos | % das emendas |")
            md.append("|---|---:|---:|")
            for m, v in sorted(votos.items(), key=lambda kv: -kv[1])[:5]:
                e = dentro.get(m, 0.0)
                md.append(f"| {m.title()} | {100*v/tot_v:.1f}% | {100*e/tot_e:.1f}% |")
            if dentro:
                md.append("\n| Maior destino de emenda no estado | Valor | % das emendas |")
                md.append("|---|---:|---:|")
                for m, e in sorted(dentro.items(), key=lambda kv: -kv[1])[:3]:
                    md.append(f"| {m.title()} | {brl(e)} | {100*e/tot_e:.1f}% |")
            rc = recebido_por_municipio(con, sq, ano)
            tot_r = sum(float(r["valor"]) for r in rc)
            if tot_r:
                dentro_r = sum(float(r["valor"]) for r in rc if r["uf"] == uf)
                md.append(f"\n**Execução financeira (quem recebeu):** {brl(tot_r)} pagos — "
                          f"{100*dentro_r/tot_r:.0f}% a favorecidos sediados em {uf}.")
                md.append("\n| Favorecidos por município (top-5) | Valor recebido | % |")
                md.append("|---|---:|---:|")
                for r in rc[:5]:
                    md.append(f"| {r['municipio'].title()} ({r['uf']}) | "
                              f"{brl(r['valor'])} | {100*float(r['valor'])/tot_r:.1f}% |")

    fontes = "\n".join(
        f"  - `{f['arquivo']}` — sha256 `{f['sha256'][:16]}`, "
        f"baixado em {f['baixado_em']:%Y-%m-%d}"
        for f in _fontes(con))
    with open(md_out, "w") as f:
        f.write(f"""# Estudo piloto — {UF_NOME[uf].title()} ({uf})

**Pergunta única:** de onde vieram os votos de cada deputado federal, e para
onde foram as emendas do mandato?

- Votos: TSE, votação nominal por município/zona, eleição de {args.ano_eleicao}.
- Emendas: Portal da Transparência (CGU), **valor empenhado**, anos {ano}+.
- Metodologia e ressalvas: ver `README.md`. Nenhuma linha deste relatório
  afirma irregularidade — emenda para outro município é legal; o dado apenas
  mostra a divergência entre origem do voto e destino da verba.

**Snapshots que geraram estes números:**

{fontes}
""")
        f.write("\n".join(md) + "\n")

    if sem_emenda:
        print(f"sem emenda casada (verificar nome): {', '.join(sem_emenda)}")
    print(f"ok: {csv_out}")
    print(f"ok: {md_out}")


def _fontes(con):
    with con.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ON (fonte_id) fonte_id, arquivo, sha256, baixado_em
            FROM snapshot WHERE ingerido_em IS NOT NULL
            ORDER BY fonte_id, baixado_em DESC
        """)
        return [dict(r) for r in cur.fetchall()]


if __name__ == "__main__":
    raise SystemExit(main())
