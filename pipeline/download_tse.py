#!/usr/bin/env python3.13
"""Baixa a votação por município/zona do TSE (dados abertos).

O CDN do TSE (Akamai) bloqueia clientes com fingerprint TLS de bot (curl,
urllib). Usamos curl_cffi com impersonation de Chrome + download por faixas
(Range) com resume, que é também o que permite retomar um arquivo de 580 MB
caído no meio.

Uso:
    python3.13 pipeline/download_tse.py [--ano 2022] [--dest data/raw]
"""
import argparse
import os
import sys
import time

from curl_cffi import requests

BASE = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona"
CHUNK = 16 * 1024 * 1024  # 16 MB por faixa
RETRIES = 6


def fetch_range(url, start, end):
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, impersonate="chrome", timeout=120,
                             headers={"Range": f"bytes={start}-{end}"})
            if r.status_code in (200, 206):
                return r.content
            raise RuntimeError(f"HTTP {r.status_code}")
        except Exception as e:
            wait = 2 ** attempt
            print(f"  faixa {start}-{end}: {e} — retry em {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"faixa {start}-{end} falhou após {RETRIES} tentativas")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", default="2022")
    ap.add_argument("--dest", default="data/raw")
    args = ap.parse_args()

    name = f"votacao_candidato_munzona_{args.ano}.zip"
    url = f"{BASE}/{name}"
    dst = os.path.join(args.dest, name)
    os.makedirs(args.dest, exist_ok=True)

    probe = requests.get(url, impersonate="chrome", timeout=60,
                         headers={"Range": "bytes=0-0"})
    if probe.status_code not in (200, 206):
        sys.exit(f"probe falhou: HTTP {probe.status_code}")
    total = int(probe.headers["content-range"].split("/")[1])

    done = os.path.getsize(dst) if os.path.exists(dst) else 0
    if done >= total:
        print(f"{name} já completo ({total} bytes)")
        return
    print(f"{name}: {total/1e6:.0f} MB, retomando de {done/1e6:.0f} MB", flush=True)

    with open(dst, "ab") as f:
        while done < total:
            end = min(done + CHUNK, total) - 1
            data = fetch_range(url, done, end)
            f.write(data)
            done += len(data)
            print(f"  {done/1e6:.0f}/{total/1e6:.0f} MB", flush=True)
    print("download completo:", dst)


if __name__ == "__main__":
    main()
