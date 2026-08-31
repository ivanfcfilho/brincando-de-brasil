#!/usr/bin/env python3
"""Leitor de .xlsx em streaming, só com a biblioteca padrão.

O INEP publica o Ideb em .xlsx e .ods dentro de um .zip. Ler isso custaria
uma dependência nova (openpyxl); aqui não custa, porque .xlsx é um zip de XML
e a planilha tem uma forma simples: uma aba, cabeçalho fixo, ~15 mil linhas.

Duas armadilhas que este módulo resolve, e que são o motivo dele existir:

  1. **A célula vazia não aparece no XML.** As linhas são esparsas: uma linha
     com 122 colunas pode trazer 30 elementos `<c>`. Quem lê por posição de
     elemento desalinha a planilha inteira e carimba o valor de uma coluna na
     outra. Por isso cada célula é endereçada pela sua referência (`r="D12"`),
     nunca pela ordem em que apareceu.
  2. **Texto mora em outro arquivo.** Célula com `t="s"` guarda um índice para
     `sharedStrings.xml`, não o texto. Ler o índice como valor produziria
     "município 4213" — número plausível, e por isso perigoso.

Uso:
    from xlsx import linhas
    for linha in linhas(caminho_xlsx, cabecalho=10):
        linha["CO_MUNICIPIO"]
"""
import xml.etree.ElementTree as ET
import zipfile

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _coluna(ref):
    """'AB12' → 27 (índice 0). A referência é a única fonte de posição."""
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n - 1


def _textos(z):
    """sharedStrings.xml → lista. Um `<si>` pode ter vários `<t>` (trechos com
    formatação diferente); concatenar todos é o que dá o texto da célula."""
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    raiz = ET.parse(z.open("xl/sharedStrings.xml")).getroot()
    return ["".join(t.text or "" for t in si.iter(NS + "t")) for si in raiz]


def _primeira_planilha(z):
    nomes = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet")]
    if not nomes:
        raise ValueError("nenhuma planilha no arquivo")
    return sorted(nomes)[0]


def celulas(caminho_ou_arquivo):
    """Gera dicionários {índice_da_coluna: valor_texto}, uma por linha."""
    with zipfile.ZipFile(caminho_ou_arquivo) as z:
        ss = _textos(z)
        with z.open(_primeira_planilha(z)) as planilha:
            for evento, el in ET.iterparse(planilha, events=("end",)):
                if el.tag != NS + "row":
                    continue
                linha = {}
                for c in el.findall(NS + "c"):
                    v = c.find(NS + "v")
                    if v is None or v.text is None:
                        continue
                    if c.get("t") == "s":
                        idx = int(v.text)
                        valor = ss[idx] if idx < len(ss) else ""
                    elif c.get("t") == "inlineStr":
                        valor = "".join(t.text or "" for t in c.iter(NS + "t"))
                    else:
                        valor = v.text
                    linha[_coluna(c.get("r", "A1"))] = valor
                yield linha
                el.clear()


def linhas(caminho, cabecalho):
    """Gera dicionários {nome_da_coluna: valor}, a partir da linha `cabecalho`
    (1-based, como o Excel mostra). Colunas sem nome são descartadas."""
    nomes = None
    for i, linha in enumerate(celulas(caminho), start=1):
        if i < cabecalho:
            continue
        if i == cabecalho:
            nomes = {j: n.strip() for j, n in linha.items() if n and n.strip()}
            continue
        yield {n: linha.get(j, "") for j, n in nomes.items()}


def numero(v):
    """Texto do INEP → float ou None.

    O INEP marca ausência com '-' (e às vezes '', '*' ou 'ND'). Devolver 0
    para esses casos seria inventar um município com Ideb zero, que entraria
    em toda média como se fosse medição real. Ausente tem que ficar ausente.
    """
    if v is None:
        return None
    t = str(v).strip().replace(",", ".")
    if t in ("", "-", "--", "*", "ND", "NA"):
        return None
    try:
        return float(t)
    except ValueError:
        return None
