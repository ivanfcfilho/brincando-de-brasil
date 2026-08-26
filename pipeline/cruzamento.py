#!/usr/bin/env python3
"""Cruzamento piloto: voto por município (TSE) × destino de emendas (Portal).

Para cada deputado federal eleito no estado piloto:
  - de onde vieram os votos (TSE, votação nominal por município/zona)
  - para onde foram as emendas do mandato (Portal da Transparência, empenhado)

A saída são dois artefatos:
  data/out/piloto_{UF}_deputado_municipio.csv  — a matriz completa
  relatorio/PILOTO_{UF}.md                     — o relatório legível

Princípio editorial do projeto: NENHUMA inferência. Publicamos origem dos
votos, destino da verba e a divergência percentual — a conclusão é do leitor.

Uso:
    python3 pipeline/cruzamento.py --uf SE [--ano-eleicao 2022] [--mandato-inicio 2023]
"""
import argparse
import csv
import io
import os
import re
import sys
import unicodedata
import zipfile
from collections import defaultdict

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


def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().upper()


def parse_valor(s):
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def open_text(path):
    raw = open(path, "rb").read(4096)
    enc = "utf-8"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        enc = "latin-1"
    return open(path, encoding=enc, newline="")


def carregar_votos(zip_path, uf, ano):
    """Votos nominais por município para deputados federais eleitos na UF."""
    votos = defaultdict(lambda: defaultdict(int))  # sq -> municipio_norm -> votos
    info = {}                                      # sq -> dados do deputado
    with zipfile.ZipFile(zip_path) as z:
        member = next((n for n in z.namelist()
                       if n.endswith(f"_{ano}_{uf}.csv")), None)
        if not member:
            sys.exit(f"CSV da UF {uf} não encontrado em {zip_path}")
        with z.open(member) as fh:
            reader = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"),
                                    delimiter=";")
            for row in reader:
                if norm(row["DS_CARGO"]) != "DEPUTADO FEDERAL":
                    continue
                if not norm(row["DS_SIT_TOT_TURNO"]).startswith("ELEITO"):
                    continue
                sq = row["SQ_CANDIDATO"]
                mun = norm(row["NM_MUNICIPIO"])
                votos[sq][mun] += int(row["QT_VOTOS_NOMINAIS"])
                if sq not in info:
                    info[sq] = {
                        "nome": norm(row["NM_CANDIDATO"]),
                        "urna": norm(row["NM_URNA_CANDIDATO"]),
                        "partido": row["SG_PARTIDO"],
                    }
    return votos, info


def indice_por_nome(info):
    """nome normalizado (urna e civil) -> sq; nomes ambíguos são descartados."""
    idx = {}
    for sq, d in info.items():
        for chave in {d["nome"], d["urna"]}:
            if chave in idx and idx[chave] != sq:
                idx[chave] = None  # ambíguo
            else:
                idx[chave] = sq
    return {k: v for k, v in idx.items() if v}


def carregar_aliases():
    """Apelidos manuais: nome do autor na base de emendas -> nome de urna TSE.
    Necessário quando o nome parlamentar difere do civil e do de urna
    (ex.: 'YANDRA MOURA' x urna 'YANDRA DE ANDRÉ')."""
    path = os.path.join(os.path.dirname(__file__), "aliases.json")
    if not os.path.exists(path):
        return {}
    import json
    with open(path, encoding="utf-8") as f:
        return {norm(k): norm(v) for k, v in json.load(f).items()}


ALIASES = {}


def casar_autor(autor, idx, info):
    """Match exato por nome de urna/civil; fallback: tokens do autor contidos
    no nome civil (cobre 'JOSE SILVA' vs 'JOSE DA SILVA SANTOS')."""
    a = norm(autor)
    a = ALIASES.get(a, a)
    if a in idx:
        return idx[a]
    toks = set(a.split())
    if len(toks) < 2:
        return None
    candidatos = [sq for sq, d in info.items()
                  if toks <= set(d["nome"].split()) or toks <= set(d["urna"].split())]
    return candidatos[0] if len(candidatos) == 1 else None


def carregar_emendas(csv_path, idx, info, uf, mandato_inicio):
    """Emendas por autor casado com deputado da UF piloto, ano >= início do mandato."""
    emendas = defaultdict(lambda: defaultdict(float))  # sq -> destino -> R$ empenhado
    uf_nome = norm(UF_NOME[uf])
    with open_text(csv_path) as fh:
        reader = csv.DictReader(fh, delimiter=";")
        reader.fieldnames = [f.strip() for f in reader.fieldnames]
        for row in reader:
            try:
                if int(row["Ano da Emenda"]) < mandato_inicio:
                    continue
            except ValueError:
                continue
            sq = casar_autor(row["Nome do Autor da Emenda"], idx, info)
            if not sq:
                continue
            valor = parse_valor(row["Valor Empenhado"])
            if not valor:
                continue
            mun, uf_dest = norm(row["Município"]), norm(row["UF"])
            if mun in ("MULTIPLO", "SEM INFORMACAO"):
                mun = ""  # não é um município — vai para as classes agregadas
            if mun and uf_dest == uf_nome:
                destino = ("DENTRO", mun)
            elif mun:
                destino = ("FORA", f"{mun} ({uf_dest.title()})")
            elif uf_dest == uf_nome:
                destino = ("ESTADO", "ESTADO — MÚLTIPLO/SEM MUNICÍPIO DEFINIDO")
            else:
                destino = ("AMPLO", "NACIONAL / MÚLTIPLO / OUTRA UF SEM MUNICÍPIO")
            emendas[sq][destino] += valor
    return emendas


def carregar_favorecidos(zip_path, idx, info, mandato_inicio):
    """Execução financeira: quem recebeu o dinheiro, por município (sigla UF).

    Fonte: EmendasParlamentares_PorFavorecido.csv (Valor Recebido). Resolve a
    massa 'Múltiplo/Sem informação' do destino planejado, com a ressalva de que
    a sede do favorecido não é necessariamente o local de aplicação (fundos
    estaduais e fornecedores concentram-se nas capitais).
    """
    receb = defaultdict(lambda: defaultdict(float))  # sq -> (uf, mun) -> R$
    with zipfile.ZipFile(zip_path) as z:
        with z.open("EmendasParlamentares_PorFavorecido.csv") as fh:
            reader = csv.DictReader(io.TextIOWrapper(fh, encoding="latin-1"),
                                    delimiter=";")
            for row in reader:
                anomes = row["Ano/Mês"]
                if not anomes[:4].isdigit() or int(anomes[:4]) < mandato_inicio:
                    continue
                sq = casar_autor(row["Nome do Autor da Emenda"], idx, info)
                if not sq:
                    continue
                valor = parse_valor(row["Valor Recebido"])
                if not valor:
                    continue
                mun = norm(row["Município Favorecido"])
                uf_fav = norm(row["UF Favorecido"])
                if mun in ("MULTIPLO", "SEM INFORMACAO", ""):
                    mun = "(SEM MUNICÍPIO)"
                receb[sq][(uf_fav, mun)] += valor
    return receb


def brl(v):
    inteiro = f"{v:,.0f}".replace(",", ".")
    return f"R$ {inteiro}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uf", default="SE")
    ap.add_argument("--ano-eleicao", type=int, default=2022)
    ap.add_argument("--mandato-inicio", type=int, default=2023)
    ap.add_argument("--raw", default="data/raw")
    args = ap.parse_args()
    uf = args.uf.upper()

    zip_path = os.path.join(args.raw, f"votacao_candidato_munzona_{args.ano_eleicao}.zip")
    emendas_csv = os.path.join(args.raw, "EmendasParlamentares.csv")

    print(f"[1/4] votos TSE {args.ano_eleicao} / {uf} …", flush=True)
    votos, info = carregar_votos(zip_path, uf, args.ano_eleicao)
    print(f"      {len(info)} deputados federais eleitos")

    global ALIASES
    ALIASES = carregar_aliases()
    idx = indice_por_nome(info)
    print(f"[2/4] emendas ≥ {args.mandato_inicio} …", flush=True)
    emendas = carregar_emendas(emendas_csv, idx, info, uf, args.mandato_inicio)
    sem_emenda = [info[sq]["urna"] for sq in info if sq not in emendas]
    if sem_emenda:
        print(f"      sem emenda casada (verificar nome): {', '.join(sem_emenda)}")

    print("[3/4] execução por favorecido …", flush=True)
    emendas_zip = os.path.join(args.raw, "EmendasParlamentares.zip")
    receb = carregar_favorecidos(emendas_zip, idx, info, args.mandato_inicio)

    print("[4/4] cruzando e escrevendo saídas …", flush=True)
    os.makedirs("data/out", exist_ok=True)
    os.makedirs("relatorio", exist_ok=True)
    csv_out = f"data/out/piloto_{uf}_deputado_municipio.csv"
    md_out = f"relatorio/PILOTO_{uf}.md"

    with open(csv_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["deputado", "partido", "municipio", "classe_destino",
                    "votos", "pct_votos", "valor_empenhado", "pct_emendas"])
        linhas_md = []
        for sq, d in sorted(info.items(), key=lambda kv: -sum(votos[kv[0]].values())):
            tot_v = sum(votos[sq].values())
            em = emendas.get(sq, {})
            tot_e = sum(em.values())
            dentro = sum(v for (c, _), v in em.items() if c == "DENTRO")
            fora = sum(v for (c, _), v in em.items() if c == "FORA")
            estado = sum(v for (c, _), v in em.items() if c == "ESTADO")
            amplo = sum(v for (c, _), v in em.items() if c == "AMPLO")

            # matriz município a município (universo: votos ∪ emendas dentro da UF)
            muns = set(votos[sq]) | {m for (c, m) in em if c == "DENTRO"}
            for m in sorted(muns, key=lambda m: -votos[sq].get(m, 0)):
                v = votos[sq].get(m, 0)
                e = em.get(("DENTRO", m), 0.0)
                w.writerow([d["urna"], d["partido"], m, "DENTRO", v,
                            round(100 * v / tot_v, 2) if tot_v else 0,
                            round(e, 2),
                            round(100 * e / tot_e, 2) if tot_e else 0])
            for (c, m), e in sorted(em.items(), key=lambda kv: -kv[1]):
                if c != "DENTRO":
                    w.writerow([d["urna"], d["partido"], m, c, 0, 0,
                                round(e, 2),
                                round(100 * e / tot_e, 2) if tot_e else 0])

            # bloco do relatório
            top_v = sorted(votos[sq].items(), key=lambda kv: -kv[1])[:5]
            top_e = sorted(((m, v) for (c, m), v in em.items() if c == "DENTRO"),
                           key=lambda kv: -kv[1])[:5]
            linhas_md.append(f"\n## {d['urna'].title()} ({d['partido']})\n")
            linhas_md.append(f"- **Votos em {args.ano_eleicao}:** {tot_v:,}".replace(",", "."))
            if tot_e:
                linhas_md.append(f"- **Emendas empenhadas {args.mandato_inicio}–2026:** {brl(tot_e)}")
                linhas_md.append(
                    f"- **Destino:** {100*dentro/tot_e:.0f}% municípios do estado · "
                    f"{100*estado/tot_e:.0f}% estado sem município definido · "
                    f"{100*fora/tot_e:.0f}% outros estados · "
                    f"{100*amplo/tot_e:.0f}% nacional/múltiplo")
                linhas_md.append("\n| Município (top-5 em votos) | % dos votos | % das emendas |")
                linhas_md.append("|---|---:|---:|")
                for m, v in top_v:
                    e = em.get(("DENTRO", m), 0.0)
                    linhas_md.append(
                        f"| {m.title()} | {100*v/tot_v:.1f}% | "
                        f"{100*e/tot_e:.1f}% |")
                if top_e:
                    linhas_md.append("\n| Maior destino de emenda no estado | Valor | % das emendas |")
                    linhas_md.append("|---|---:|---:|")
                    for m, e in top_e[:3]:
                        linhas_md.append(f"| {m.title()} | {brl(e)} | {100*e/tot_e:.1f}% |")
                rc = receb.get(sq, {})
                tot_r = sum(rc.values())
                if tot_r:
                    dentro_r = sum(v for (u, _), v in rc.items() if u == uf)
                    linhas_md.append(
                        f"\n**Execução financeira (quem recebeu):** {brl(tot_r)} pagos — "
                        f"{100*dentro_r/tot_r:.0f}% a favorecidos sediados em {uf}.")
                    linhas_md.append("\n| Favorecidos por município (top-5) | Valor recebido | % |")
                    linhas_md.append("|---|---:|---:|")
                    for (u, m), v in sorted(rc.items(), key=lambda kv: -kv[1])[:5]:
                        linhas_md.append(f"| {m.title()} ({u}) | {brl(v)} | {100*v/tot_r:.1f}% |")
            else:
                linhas_md.append("- **Emendas:** nenhuma casada pelo nome "
                                 "(licença, suplência ou grafia divergente — verificar manualmente)")

    with open(md_out, "w") as f:
        f.write(f"""# Estudo piloto — {UF_NOME[uf].title()} ({uf})

**Pergunta única:** de onde vieram os votos de cada deputado federal, e para
onde foram as emendas do mandato?

- Votos: TSE, votação nominal por município/zona, eleição de {args.ano_eleicao}.
- Emendas: Portal da Transparência (CGU), **valor empenhado**, anos {args.mandato_inicio}+.
- Metodologia e ressalvas: ver `README.md`. Nenhuma linha deste relatório
  afirma irregularidade — emenda para outro município é legal; o dado apenas
  mostra a divergência entre origem do voto e destino da verba.
""")
        f.write("\n".join(linhas_md) + "\n")

    print(f"ok: {csv_out}")
    print(f"ok: {md_out}")


if __name__ == "__main__":
    main()
