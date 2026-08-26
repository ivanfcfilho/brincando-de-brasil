#!/usr/bin/env python3
"""Baixa a base completa de emendas parlamentares do Portal da Transparência.

Fonte oficial (CGU, dados abertos, sem autenticação):
https://portaldatransparencia.gov.br/download-de-dados/emendas-parlamentares

Uso:
    python3 pipeline/download_emendas.py [--dest data/raw]
"""
import argparse
import os
import urllib.request
import zipfile

URL = ("https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/"
       "saida/emendas-parlamentares/EmendasParlamentares.zip")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="data/raw")
    args = ap.parse_args()
    os.makedirs(args.dest, exist_ok=True)
    dst = os.path.join(args.dest, "EmendasParlamentares.zip")

    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    print("baixando", URL, flush=True)
    with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    print(f"ok: {dst} ({os.path.getsize(dst)/1e6:.0f} MB)")

    with zipfile.ZipFile(dst) as z:
        z.extract("EmendasParlamentares.csv", args.dest)
    print("extraído: EmendasParlamentares.csv")


if __name__ == "__main__":
    main()
