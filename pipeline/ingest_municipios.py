#!/usr/bin/env python3
"""Popula `municipio`: ponte TSE ↔ IBGE + coordenadas.

É o que destrava a distância em km entre a origem do voto e o destino da
verba — o número que a plataforma promete.

Três peças, todas de fonte oficial e sem autenticação:

  1. lista de municípios (IBGE/localidades): código IBGE, nome, UF;
  2. centroide (IBGE/malhas, país inteiro numa requisição): calculado do
     polígono do território. **Centroide do território, não a sede do
     município** — para "distância entre o voto e a verba" o território é a
     referência honesta, mas a diferença precisa estar escrita;
  3. código do TSE, casado por (UF, nome normalizado) contra os municípios
     que já aparecem em voto_municipio. O TSE não publica a correspondência
     com o IBGE; o nome dentro da UF é o que há, e o que não casar fica
     listado em vez de sumir.

Uso:
    python3.13 pipeline/ingest_municipios.py
"""
import gzip
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
from nomes import carregar_aliases_municipios, chave_municipio, norm

UA = {"User-Agent": "codigo-de-transicao/1.0 (dados abertos)"}
URL_LISTA = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
URL_MALHA = ("https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
             "?formato=application/vnd.geo+json&intrarregiao=municipio"
             "&qualidade=minima")

def baixar_json(url, timeout=300):
    """O IBGE responde gzip mesmo sem Accept-Encoding, e o urllib não
    descomprime sozinho."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        bruto = r.read()
    if bruto[:2] == b"\x1f\x8b":
        bruto = gzip.decompress(bruto)
    return json.loads(bruto.decode("utf-8"))


def _aneis(geom):
    """Todos os anéis externos, seja Polygon ou MultiPolygon."""
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        return [p[0] for p in geom["coordinates"]]
    return []


def centroide(geom):
    """Centroide por área (fórmula do shoelace), do maior anel.

    Média simples dos vértices puxaria o ponto para onde o contorno tem mais
    detalhe — num município de litoral recortado, para o mar.
    """
    melhor, melhor_area = None, -1.0
    for anel in _aneis(geom):
        if len(anel) < 3:
            continue
        a = cx = cy = 0.0
        for (x0, y0), (x1, y1) in zip(anel, anel[1:] + anel[:1]):
            f = x0 * y1 - x1 * y0
            a += f
            cx += (x0 + x1) * f
            cy += (y0 + y1) * f
        if a == 0:
            continue
        area = abs(a / 2)
        if area > melhor_area:
            melhor_area, melhor = area, (cx / (3 * a), cy / (3 * a))
    return melhor


def main():
    con = bd.conectar()
    bd.init(con)

    print("[1/4] lista de municípios (IBGE) …", flush=True)
    lista = baixar_json(URL_LISTA)
    munis = {}
    for m in lista:
        uf = m["microrregiao"]["mesorregiao"]["UF"]["sigla"] if m.get("microrregiao") \
            else m["regiao-imediata"]["regiao-intermediaria"]["UF"]["sigla"]
        munis[int(m["id"])] = {"nome": m["nome"], "nome_norm": norm(m["nome"]),
                               "uf": uf, "lat": None, "lon": None, "cod_tse": None}
    print(f"      {len(munis)} municípios")

    print("[2/4] malha territorial (IBGE) e centroides …", flush=True)
    malha = baixar_json(URL_MALHA)
    sem_geo = 0
    for f in malha["features"]:
        cod = int(f["properties"]["codarea"])
        c = centroide(f["geometry"])
        if cod in munis and c:
            munis[cod]["lon"], munis[cod]["lat"] = c
        else:
            sem_geo += 1
    print(f"      {sum(1 for m in munis.values() if m['lat'])} com coordenada"
          + (f", {sem_geo} feições sem correspondência" if sem_geo else ""))

    print("[3/4] correspondência com o código do TSE …", flush=True)
    with con.cursor() as cur:
        cur.execute("SELECT DISTINCT uf, municipio_norm, cod_municipio_tse "
                    "FROM voto_municipio")
        tse = cur.fetchall()
    apelidos = carregar_aliases_municipios()
    por_chave = {}
    for cod, m in munis.items():
        por_chave.setdefault((m["uf"], chave_municipio(m["nome"])), []).append(cod)
    casados, sem_casar = 0, []
    for r in tse:
        cod = apelidos.get(f"{r['uf']}|{r['municipio_norm']}")
        if cod is None:
            alvo = por_chave.get((r["uf"], chave_municipio(r["municipio_norm"])))
            cod = alvo[0] if alvo and len(alvo) == 1 else None
        if cod in munis:
            munis[cod]["cod_tse"] = r["cod_municipio_tse"]
            casados += 1
        else:
            sem_casar.append(f"{r['municipio_norm']}/{r['uf']}")
    print(f"      {casados}/{len(tse)} municípios do TSE casados com o IBGE")
    if sem_casar:
        print(f"      SEM CASAR ({len(sem_casar)}): {', '.join(sorted(sem_casar))}")

    print("[4/4] gravando …", flush=True)
    with con.cursor() as cur:
        cur.execute("CREATE TEMP TABLE stg_mun (LIKE municipio) ON COMMIT DROP")
    cols = ["cod_ibge", "nome", "nome_norm", "uf", "cod_tse", "lat", "lon"]
    bd.copiar(con, "stg_mun", cols,
              ((c, m["nome"], m["nome_norm"], m["uf"], m["cod_tse"], m["lat"], m["lon"])
               for c, m in munis.items()))
    with con.cursor() as cur:
        cur.execute(f"""
            INSERT INTO municipio ({','.join(cols)})
            SELECT {','.join(cols)} FROM stg_mun
            ON CONFLICT (cod_ibge) DO UPDATE SET
                nome=EXCLUDED.nome, nome_norm=EXCLUDED.nome_norm, uf=EXCLUDED.uf,
                cod_tse=EXCLUDED.cod_tse, lat=EXCLUDED.lat, lon=EXCLUDED.lon
        """)
    con.commit()
    print(f"ok: {bd.contar(con, 'municipio')} municípios no banco")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
