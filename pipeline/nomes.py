#!/usr/bin/env python3
"""Normalização de nomes e casamento autor-de-emenda ↔ candidato do TSE.

Lógica compartilhada entre a ingestão e o relatório — um único lugar onde se
decide que "YANDRA MOURA" e "YANDRA DE ANDRÉ" são a mesma pessoa. Qualquer
divergência entre esses dois caminhos produziria dois números diferentes para
a mesma pergunta, que é exatamente o erro que destrói a credibilidade.
"""
import json
import os
import re
import unicodedata

ALIASES_PATH = os.path.join(os.path.dirname(__file__), "aliases.json")


def norm(s):
    """Maiúsculas, sem acento, sem espaço duplicado."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip().upper()


def parse_valor(s):
    """'1.234,56' → 1234.56. Campo vazio ou lixo vira 0.0."""
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def carregar_aliases():
    """Apelidos manuais: nome do autor na base de emendas → nome no TSE.

    Necessário quando o nome parlamentar não bate nem com o civil nem com o de
    urna. Com o casamento por 'Código do Autor da Emenda' persistido na tabela
    `autor`, este arquivo tende a virar histórico — mas continua sendo o jeito
    de corrigir um vínculo sem editar o banco à mão.
    """
    if not os.path.exists(ALIASES_PATH):
        return {}
    with open(ALIASES_PATH, encoding="utf-8") as f:
        return {norm(k): norm(v) for k, v in json.load(f).items()}


def indice_por_nome(candidatos):
    """{nome_norm: sq_candidato}; nomes ambíguos (homônimos) são descartados.

    `candidatos` é um iterável de (sq_candidato, nome, nome_urna).
    """
    idx = {}
    for sq, nome, urna in candidatos:
        for chave in {norm(nome), norm(urna)}:
            if chave in idx and idx[chave] != sq:
                idx[chave] = None  # ambíguo: melhor nenhum match que o errado
            else:
                idx[chave] = sq
    return {k: v for k, v in idx.items() if v}


def _compativel(autor_toks, alvo_toks):
    """Subconjunto de tokens NÃO basta: o primeiro e o último nome também
    precisam coincidir.

    Sem essa trava, 'EDUARDO BRAGA' (senador/AM) casa com 'CARLOS EDUARDO
    BRAGA MENEZES' (suplente/MG) e 'KATIA ABREU' casa com 'CRISTIANE KATIA
    SIMONI ABREU' — pessoas diferentes. Atribuir a emenda de alguém a outra
    pessoa é o erro que o projeto não pode cometer, então a regra é a mais
    restritiva que ainda aceita os casos legítimos ('JOVAIR ARANTES' ×
    'JOVAIR DE OLIVEIRA ARANTES', 'LUIZ CARLOS HAULY' × 'LUIZ CARLOS JORGE
    HAULY'), onde primeiro e último nome se preservam.
    """
    if not set(autor_toks) <= set(alvo_toks):
        return False
    return autor_toks[0] == alvo_toks[0] and autor_toks[-1] == alvo_toks[-1]


def casar_autor(autor, idx, candidatos, aliases=None):
    """(sq_candidato, metodo) ou (None, motivo).

    Match exato por nome civil/urna; depois alias manual; por fim tokens, com
    a trava de primeiro/último nome. Ambiguidade em qualquer etapa devolve
    None — nunca "chuta": um match errado é pior que match nenhum, porque o
    match nenhum aparece no log e o errado aparece no relatório.
    """
    aliases = aliases if aliases is not None else {}
    a = norm(autor)
    if a in idx:
        return idx[a], "exato"
    if a in aliases:
        alvo = aliases[a]
        if alvo in idx:
            return idx[alvo], "alias"
    toks = a.split()
    if len(toks) < 2:
        return None, "nome curto demais"
    achados = [sq for sq, nome, urna in candidatos
               if _compativel(toks, norm(nome).split())
               or _compativel(toks, norm(urna).split())]
    achados = list(dict.fromkeys(achados))
    if len(achados) == 1:
        return achados[0], "tokens"
    return None, "ambiguo" if achados else "sem correspondencia"
