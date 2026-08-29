#!/usr/bin/env python3.13
"""Baixa a votação por município/zona do TSE.

Mantido por compatibilidade de uso: a lógica (impersonation de Chrome e
download por faixas com resume) mora em fontes.py, para existir num lugar só.

Uso:
    python3.13 pipeline/download_tse.py [--ano 2022]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fontes import FONTES, baixar

ap = argparse.ArgumentParser()
ap.add_argument("--ano", default="2022")
args = ap.parse_args()
print(baixar(FONTES[f"tse_munzona_{args.ano}"]))
