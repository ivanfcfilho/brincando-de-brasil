#!/usr/bin/env python3
"""Baixa a base de emendas parlamentares da CGU.

Mantido por compatibilidade de uso: a lógica mora em fontes.py. Prefira
`python3.13 pipeline/atualizar.py`, que só baixa se a fonte mudou.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fontes import FONTES, baixar

print(baixar(FONTES["cgu_emendas"]))
