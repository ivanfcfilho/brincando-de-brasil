#!/usr/bin/env python3
"""Registro das fontes oficiais: como checar se mudaram e como baixar.

A checagem é um HEAD e custa ~1 KB. Só quando ETag/Last-Modified/tamanho
mudam é que se baixa o arquivo inteiro — por isso o job pode rodar todo dia
sem torrar banda nem incomodar o servidor da CGU.

A periodicidade é por fonte, não do job: a votação do TSE de 2022 não muda
mais (são 580 MB estáticos até a próxima eleição), então ela fica marcada
como 'eleicao' e o job diário nem a consulta, a menos que se peça.

Uso:
    python3.13 pipeline/fontes.py --listar
    python3.13 pipeline/fontes.py --checar cgu_emendas
"""
import argparse
import os
import time
import urllib.request
from dataclasses import dataclass

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(RAIZ, "data", "raw")
UA = "Mozilla/5.0 (compatible; codigo-de-transicao/1.0; +dados abertos)"


@dataclass(frozen=True)
class Fonte:
    id: str
    descricao: str
    url: str
    arquivo: str
    periodicidade: str   # 'diaria' | 'eleicao'
    cliente: str         # 'urllib' | 'curl_cffi'


FONTES = {
    "cgu_emendas": Fonte(
        id="cgu_emendas",
        descricao="Emendas parlamentares — CGU/Portal da Transparência",
        url=("https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/"
             "saida/emendas-parlamentares/EmendasParlamentares.zip"),
        arquivo="EmendasParlamentares.zip",
        periodicidade="diaria",
        cliente="urllib",
    ),
    "tse_munzona_2022": Fonte(
        id="tse_munzona_2022",
        descricao="Votação nominal por município/zona — TSE, eleição 2022",
        url=("https://cdn.tse.jus.br/estatistica/sead/odsele/"
             "votacao_candidato_munzona/votacao_candidato_munzona_2022.zip"),
        arquivo="votacao_candidato_munzona_2022.zip",
        periodicidade="eleicao",
        cliente="curl_cffi",   # o CDN do TSE (Akamai) bloqueia urllib por TLS
    ),
}


def caminho(fonte, raw=RAW):
    return os.path.join(raw, fonte.arquivo)


# ------------------------------------------------------------------ checagem

def _cabecalhos_urllib(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        h = r.headers
        return {"etag": h.get("ETag"), "last_modified": h.get("Last-Modified"),
                "tamanho": int(h.get("Content-Length") or 0)}


def _cabecalhos_curl_cffi(url):
    from curl_cffi import requests
    # O CDN do TSE responde melhor a um GET de 1 byte que a um HEAD.
    r = requests.get(url, impersonate="chrome", timeout=60,
                     headers={"Range": "bytes=0-0"})
    if r.status_code not in (200, 206):
        raise RuntimeError(f"HTTP {r.status_code}")
    cr = r.headers.get("content-range", "")
    total = int(cr.split("/")[1]) if "/" in cr else 0
    return {"etag": r.headers.get("etag"),
            "last_modified": r.headers.get("last-modified"), "tamanho": total}


def checar(fonte):
    """Cabeçalhos da fonte. Levanta exceção se a fonte estiver inacessível."""
    if fonte.cliente == "curl_cffi":
        return _cabecalhos_curl_cffi(fonte.url)
    return _cabecalhos_urllib(fonte.url)


def mudou(cab, snap):
    """Compara os cabeçalhos com o último snapshot registrado.

    Sem snapshot anterior, é mudança (primeira carga). ETag é a comparação
    forte; Last-Modified e tamanho são a rede de segurança para servidor que
    não manda ETag estável.
    """
    if snap is None:
        return True, "primeira carga"
    if cab.get("etag") and snap["etag"]:
        if cab["etag"] != snap["etag"]:
            return True, f"etag {snap['etag']} → {cab['etag']}"
        return False, "etag idêntico"
    if cab.get("last_modified") and snap["publicado_em"]:
        if cab["last_modified"] != snap["publicado_em"]:
            return True, f"last-modified {snap['publicado_em']} → {cab['last_modified']}"
    if cab.get("tamanho") and snap["tamanho"] and cab["tamanho"] != snap["tamanho"]:
        return True, f"tamanho {snap['tamanho']} → {cab['tamanho']}"
    return False, "sem alteração nos cabeçalhos"


# ------------------------------------------------------------------ download

def _baixar_urllib(url, dst):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    tmp = dst + ".parcial"
    with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(tmp, dst)
    return dst


def _baixar_curl_cffi(url, dst, chunk=16 << 20, retries=6):
    """Download por faixas com resume — 580 MB caem no meio com frequência,
    e o bloqueio do CDN do TSE é intermitente: retomar é obrigatório."""
    from curl_cffi import requests
    total = _cabecalhos_curl_cffi(url)["tamanho"]
    tmp = dst + ".parcial"
    feito = os.path.getsize(tmp) if os.path.exists(tmp) else 0
    if feito >= total > 0:
        os.replace(tmp, dst)
        return dst
    print(f"  {total/1e6:.0f} MB, retomando de {feito/1e6:.0f} MB", flush=True)
    with open(tmp, "ab") as f:
        while feito < total:
            fim = min(feito + chunk, total) - 1
            for tentativa in range(retries):
                try:
                    r = requests.get(url, impersonate="chrome", timeout=120,
                                     headers={"Range": f"bytes={feito}-{fim}"})
                    if r.status_code not in (200, 206):
                        raise RuntimeError(f"HTTP {r.status_code}")
                    break
                except Exception as e:
                    espera = 2 ** tentativa
                    print(f"  faixa {feito}-{fim}: {e} — retry em {espera}s", flush=True)
                    time.sleep(espera)
            else:
                raise RuntimeError(f"faixa {feito}-{fim} falhou após {retries} tentativas")
            f.write(r.content)
            feito += len(r.content)
            print(f"  {feito/1e6:.0f}/{total/1e6:.0f} MB", flush=True)
    os.replace(tmp, dst)
    return dst


def baixar(fonte, raw=RAW):
    """Baixa para data/raw/. Escreve em .parcial e só renomeia no fim, para
    que uma queda no meio nunca deixe um arquivo truncado passando por bom."""
    os.makedirs(raw, exist_ok=True)
    dst = caminho(fonte, raw)
    print(f"baixando {fonte.id} …", flush=True)
    if fonte.cliente == "curl_cffi":
        return _baixar_curl_cffi(fonte.url, dst)
    return _baixar_urllib(fonte.url, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--checar", metavar="FONTE_ID")
    args = ap.parse_args()
    if args.listar or not args.checar:
        for f in FONTES.values():
            local = caminho(f)
            tam = f"{os.path.getsize(local)/1e6:.0f} MB" if os.path.exists(local) else "ausente"
            print(f"{f.id:20s} {f.periodicidade:8s} local={tam:>10s}  {f.descricao}")
    if args.checar:
        f = FONTES[args.checar]
        print(f.id, checar(f))


if __name__ == "__main__":
    main()
