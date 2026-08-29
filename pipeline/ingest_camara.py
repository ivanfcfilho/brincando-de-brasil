#!/usr/bin/env python3
"""Registro da Câmara: id, nome parlamentar e nome civil dos 513 em exercício.

Fecha o buraco que nem o TSE nem a CGU fecham sozinhos. O TSE tem nome civil e
de urna; a CGU tem o nome parlamentar do autor da emenda. Quando os três
divergem ('DEPUTADO DAL' no TSE × 'DAL BARRETO' na CGU), não há como ligar —
a Câmara é o registro que traz os dois lados na mesma linha.

Também resolve a ambiguidade com suplentes: a Câmara lista quem está EM
EXERCÍCIO, então um homônimo suplente deixa de competir pelo mesmo nome.

Fonte: dadosabertos.camara.leg.br (aberta, sem autenticação).

Uso:
    python3.13 pipeline/ingest_camara.py [--legislatura 57]
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from curl_cffi import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
from nomes import norm

API = "https://dadosabertos.camara.leg.br/api/v2"


def buscar(url, timeout=30, tentativas=4):
    """A API responde em ~0,2 s a um cliente de navegador e leva 20 s (ou
    estoura) para o urllib — mesmo comportamento do CDN do TSE. curl_cffi com
    impersonation resolve, e é dependência que o projeto já tem."""
    for i in range(tentativas):
        try:
            r = requests.get(url, impersonate="chrome", timeout=timeout,
                             headers={"Accept": "application/json"})
            if r.status_code == 200:
                return r.json()
            raise RuntimeError(f"HTTP {r.status_code}")
        except Exception as e:
            if i == tentativas - 1:
                raise
            time.sleep(2 ** i)


def listar(legislatura, max_paginas=20):
    """Pagina pelo link rel=next da própria API.

    Parar quando a página vier com menos de 100 itens NÃO funciona aqui: a
    API devolve 100 indefinidamente, repetindo registros, e o laço nunca
    termina (o que rende bloqueio por excesso de requisição). A deduplicação
    por id e o teto de páginas são a segunda e a terceira trava.
    """
    url = f"{API}/deputados?idLegislatura={legislatura}&itens=100&pagina=1"
    vistos, todos = set(), []
    for _ in range(max_paginas):
        d = buscar(url)
        # Filtra item a item: a API repete registros DENTRO da mesma página,
        # e atualizar `vistos` só no fim da página deixava a duplicata passar.
        novos = []
        for x in d.get("dados", []):
            if x["id"] not in vistos:
                vistos.add(x["id"])
                novos.append(x)
        if not novos:
            break
        todos.extend(novos)
        prox = next((l["href"] for l in d.get("links", []) if l.get("rel") == "next"), None)
        if not prox:
            break
        url = prox
        time.sleep(0.2)   # cortesia com a API pública
    return todos


def detalhar(dep):
    """O nome civil só vem no detalhe — é ele que casa com o TSE."""
    try:
        d = buscar(f"{API}/deputados/{dep['id']}")["dados"]
        return {"id_camara": dep["id"], "uf": dep["siglaUf"],
                "partido": dep.get("siglaPartido"),
                "nome_eleitoral": norm(d["ultimoStatus"].get("nomeEleitoral") or dep["nome"]),
                "nome_civil": norm(d.get("nomeCivil") or "")}
    except Exception as e:
        print(f"  aviso: detalhe de {dep['id']} ({dep['nome']}) falhou: {e}")
        return None


def casar_com_tse(con, deps):
    """Câmara → TSE por nome civil dentro da UF, com nome eleitoral de reserva.

    A restrição por UF é o que torna isto seguro: dois homônimos em estados
    diferentes deixam de competir.
    """
    with con.cursor() as cur:
        cur.execute("SELECT sq_candidato, uf, nome, nome_urna, situacao FROM deputado")
        tse = cur.fetchall()
    por_civil, por_urna = {}, {}
    for r in tse:
        eleito = r["situacao"].startswith("ELEITO")
        for idx, chave in ((por_civil, (r["uf"], r["nome"])),
                           (por_urna, (r["uf"], r["nome_urna"]))):
            # Eleito ganha de suplente na disputa pelo mesmo nome: quem exerce
            # o mandato é quem apresenta emenda.
            atual = idx.get(chave)
            if atual is None or (eleito and not atual[1]):
                idx[chave] = (r["sq_candidato"], eleito)
            elif eleito and atual[1]:
                idx[chave] = (None, True)   # dois eleitos homônimos: ambíguo

    casados, sem = [], []
    for d in deps:
        alvo = (por_civil.get((d["uf"], d["nome_civil"]))
                or por_urna.get((d["uf"], d["nome_eleitoral"])))
        if alvo and alvo[0]:
            casados.append((alvo[0], d["id_camara"]))
        else:
            sem.append(d)
    return casados, sem


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislatura", type=int, default=57)
    args = ap.parse_args()
    con = bd.conectar()
    bd.init(con)

    print(f"[1/3] listando deputados da legislatura {args.legislatura} …", flush=True)
    lista = listar(args.legislatura)
    print(f"      {len(lista)} deputados")

    print("[2/3] buscando nome civil de cada um …", flush=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        deps = [d for d in ex.map(detalhar, lista) if d]
    print(f"      {len(deps)} detalhados")

    print("[3/3] casando com o TSE e gravando …", flush=True)
    casados, sem = casar_com_tse(con, deps)
    with con.cursor() as cur:
        cur.executemany("UPDATE deputado SET id_camara=%s WHERE sq_candidato=%s",
                        [(idc, sq) for sq, idc in casados])
    con.commit()
    print(f"      {len(casados)}/{len(deps)} casados com candidato do TSE")
    if sem:
        print(f"      sem casar ({len(sem)}): " +
              ", ".join(f"{d['nome_eleitoral']}/{d['uf']}" for d in sem[:10]))

    # O nome parlamentar da Câmara vira mais uma grafia conhecida do deputado,
    # e é justamente ela que costuma bater com o autor da emenda na CGU.
    with con.cursor() as cur:
        cur.execute("CREATE TABLE IF NOT EXISTS nome_camara ("
                    "id_camara INTEGER PRIMARY KEY, nome_eleitoral TEXT NOT NULL, "
                    "nome_civil TEXT, uf TEXT, partido TEXT)")
        cur.executemany(
            "INSERT INTO nome_camara (id_camara, nome_eleitoral, nome_civil, uf, partido) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id_camara) DO UPDATE SET "
            "nome_eleitoral=EXCLUDED.nome_eleitoral, nome_civil=EXCLUDED.nome_civil, "
            "uf=EXCLUDED.uf, partido=EXCLUDED.partido",
            [(d["id_camara"], d["nome_eleitoral"], d["nome_civil"], d["uf"], d["partido"])
             for d in deps])
    con.commit()
    print(f"ok: {bd.contar(con, 'nome_camara')} nomes parlamentares gravados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
