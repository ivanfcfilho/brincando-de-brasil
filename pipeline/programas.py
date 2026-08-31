#!/usr/bin/env python3
"""O que cada governo fez: programas e leis, cada um com o ato que o criou.

Esta é a única parte do site escrita à mão, e por isso é a que precisa de mais
cuidado. A regra que a torna aceitável: **nada entra sem o instrumento legal**
— número da lei, da lei complementar ou da emenda constitucional — e cada
item aponta para o texto no Planalto, onde qualquer pessoa confere em dois
cliques.

`--conferir` baixa TODAS as páginas do Planalto e checa se a ementa contém o
que afirmamos. Uma URL quebrada ou um número de lei trocado aparece como
falha, e não como texto bonito no ar.

O que esta lista NÃO faz:
  - não diz se o programa foi bom, deu certo ou custou caro;
  - não é exaustiva (nenhuma lista de 8 governos caberia numa tela);
  - não credita o resultado do país ao programa.
É um índice de "o que foi criado no mandato", para quem quiser ir ler.

    python3.13 pipeline/programas.py            # lista
    python3.13 pipeline/programas.py --conferir # valida contra o Planalto
"""
import argparse
import gzip
import re
import sys
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (compatible; brincando-de-brasil/1.0)",
      "Accept-Encoding": "gzip"}

# (presidente, nome do programa, ato, url no Planalto, palavra que a ementa
#  precisa conter, uma linha de explicação em português simples)
PROGRAMAS = [
 ("collor", "Código de Defesa do Consumidor", "Lei 8.078/1990",
  "https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm", "consumidor",
  "Criou os direitos do consumidor: troca, garantia, propaganda enganosa."),
 ("collor", "Programa Nacional de Desestatização", "Lei 8.031/1990",
  "https://www.planalto.gov.br/ccivil_03/leis/l8031.htm", "Desestatiza",
  "Deu início às privatizações de empresas estatais."),
 ("collor", "Bloqueio da poupança (Plano Collor)", "Lei 8.024/1990",
  "https://www.planalto.gov.br/ccivil_03/leis/l8024.htm", "cruzado",
  "Reteve depósitos e poupança na tentativa de conter a hiperinflação."),
 ("collor", "Estatuto da Criança e do Adolescente", "Lei 8.069/1990",
  "https://www.planalto.gov.br/ccivil_03/leis/l8069.htm", "Criança e do Adolescente",
  "O ECA: regras de proteção a crianças e adolescentes."),

 ("itamar", "Plano Real", "Lei 9.069/1995",
  "https://www.planalto.gov.br/ccivil_03/leis/l9069.htm", "Real",
  "A moeda que acabou com a hiperinflação, lançada em julho de 1994."),
 ("itamar", "Lei de Licitações", "Lei 8.666/1993",
  "https://www.planalto.gov.br/ccivil_03/leis/l8666cons.htm", "licitaç",
  "Definiu como o governo compra e contrata. Valeu por quase 30 anos."),

 ("fhc", "Lei de Responsabilidade Fiscal", "Lei Complementar 101/2000",
  "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp101.htm", "gestão fiscal",
  "Limitou gasto e endividamento de prefeitos e governadores."),
 ("fhc", "Lei de Diretrizes e Bases da Educação", "Lei 9.394/1996",
  "https://www.planalto.gov.br/ccivil_03/leis/l9394.htm", "diretrizes e bases",
  "A lei que organiza toda a educação brasileira."),
 ("fhc", "Fundef (dinheiro para o ensino fundamental)", "Emenda Constitucional 14/1996",
  "https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc14.htm", "ensino fundamental",
  "Fundo que passou a distribuir a verba da educação por aluno matriculado."),
 ("fhc", "Estatuto da Cidade", "Lei 10.257/2001",
  "https://www.planalto.gov.br/ccivil_03/leis/leis_2001/l10257.htm", "política urbana",
  "Regras de uso do solo urbano e plano diretor das cidades."),

 ("lula12", "Bolsa Família", "Lei 10.836/2004",
  "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2004/lei/l10.836.htm", "Bolsa Fam",
  "Transferência mensal de renda para famílias pobres, com condição de escola e vacina."),
 ("lula12", "ProUni", "Lei 11.096/2005",
  "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2005/lei/l11096.htm", "PROUNI",
  "Bolsas em faculdades privadas para alunos de escola pública."),
 ("lula12", "Lei Maria da Penha", "Lei 11.340/2006",
  "https://www.planalto.gov.br/ccivil_03/_ato2004-2006/2006/lei/l11340.htm", "violência doméstica",
  "Criou mecanismos para coibir a violência doméstica contra a mulher."),
 ("lula12", "Fundeb", "Emenda Constitucional 53/2006",
  "https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc53.htm", "educação básica",
  "Ampliou o Fundef para toda a educação básica, da creche ao ensino médio."),
 ("lula12", "Minha Casa, Minha Vida", "Lei 11.977/2009",
  "https://www.planalto.gov.br/ccivil_03/_ato2007-2010/2009/lei/l11977.htm", "Minha Casa",
  "Financiamento de casa própria com subsídio para renda baixa."),

 ("dilma", "Lei de Acesso à Informação", "Lei 12.527/2011",
  "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2011/lei/l12527.htm", "acesso a informações",
  "Obrigou o governo a entregar dado público a quem pedir. É ela que sustenta este site."),
 ("dilma", "Lei de Cotas nas universidades federais", "Lei 12.711/2012",
  "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2012/lei/l12711.htm", "ingresso nas universidades",
  "Reservou vagas em universidades federais por escola pública, renda e raça."),
 ("dilma", "Mais Médicos", "Lei 12.871/2013",
  "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2013/lei/l12871.htm", "Mais Médicos",
  "Levou médicos para cidades do interior e periferias."),
 ("dilma", "Marco Civil da Internet", "Lei 12.965/2014",
  "https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2014/lei/l12965.htm", "Internet",
  "Definiu direitos e deveres de quem usa e de quem fornece internet."),

 ("temer", "Teto de gastos", "Emenda Constitucional 95/2016",
  "https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc95.htm", "Novo Regime Fiscal",
  "Congelou o gasto federal por 20 anos, corrigido só pela inflação."),
 ("temer", "Reforma trabalhista", "Lei 13.467/2017",
  "https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2017/lei/l13467.htm", "Consolidação das Leis do Trabalho",
  "Mudou a CLT: negociado sobre o legislado, trabalho intermitente, fim da contribuição sindical obrigatória."),
 ("temer", "Reforma do ensino médio", "Lei 13.415/2017",
  "https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2017/lei/l13415.htm", "ensino médio",
  "Reorganizou o ensino médio em itinerários e ampliou a carga horária."),
 ("temer", "Lei Geral de Proteção de Dados", "Lei 13.709/2018",
  "https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm", "dados pessoais",
  "A LGPD: regras sobre o que empresas podem fazer com seus dados."),

 ("bolsonaro", "Reforma da Previdência", "Emenda Constitucional 103/2019",
  "https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc103.htm", "previd",
  "Idade mínima para aposentadoria e mudança no cálculo do benefício."),
 ("bolsonaro", "Auxílio Emergencial", "Lei 13.982/2020",
  "https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2020/lei/l13982.htm", "emergência",
  "Pagamento mensal durante a pandemia para informais e desempregados."),
 ("bolsonaro", "Novo marco do saneamento", "Lei 14.026/2020",
  "https://www.planalto.gov.br/ccivil_03/_ato2019-2022/2020/lei/l14026.htm", "saneamento",
  "Abriu à iniciativa privada a água e o esgoto antes só de estatais."),
 ("bolsonaro", "Autonomia do Banco Central", "Lei Complementar 179/2021",
  "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp179.htm", "Banco Central",
  "Deu mandato fixo ao presidente do BC, desligado do mandato presidencial."),

 ("lula3", "Novo Bolsa Família", "Lei 14.601/2023",
  "https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2023/lei/l14601.htm", "Bolsa Fam",
  "Recriou o programa com valor por criança e piso por família."),
 ("lula3", "Arcabouço fiscal (no lugar do teto)", "Lei Complementar 200/2023",
  "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp200.htm", "regime fiscal",
  "Substituiu o teto de gastos por uma regra que cresce conforme a receita."),
 ("lula3", "Reforma tributária", "Emenda Constitucional 132/2023",
  "https://www.planalto.gov.br/ccivil_03/constituicao/emendas/emc/emc132.htm", "tribut",
  "Juntou cinco impostos sobre consumo em dois. A transição vai até 2033."),
 ("lula3", "Pé-de-Meia", "Lei 14.818/2024",
  "https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2024/lei/l14818.htm", "ensino médio",
  "Poupança para o aluno do ensino médio público que não abandona a escola."),
]


def por_presidente():
    fora = {}
    for pid, nome, ato, url, _, texto in PROGRAMAS:
        fora.setdefault(pid, []).append(
            {"nome": nome, "ato": ato, "url": url, "texto": texto})
    return fora


def _ementa(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        b = r.read()
    if b[:2] == b"\x1f\x8b":
        b = gzip.decompress(b)
    # O Planalto serve latin-1, utf-8 E utf-16 conforme a página (a Lei Maria
    # da Penha vem em utf-16 com BOM). Decodificar tudo como latin-1 devolvia
    # "L e i   n º" e reprovava uma lei que estava certa.
    if b[:2] in (b"\xff\xfe", b"\xfe\xff"):
        t = b.decode("utf-16", "replace")
    else:
        try:
            t = b.decode("utf-8")
        except UnicodeDecodeError:
            t = b.decode("latin-1", "replace")
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)[:3000]


def conferir():
    """Baixa cada ato no Planalto e confere se a ementa diz o que afirmamos."""
    falhas = 0
    for pid, nome, ato, url, chave, _ in PROGRAMAS:
        try:
            texto = _ementa(url)
            ok = chave.lower() in texto.lower()
        except Exception as e:
            ok, texto = False, f"{type(e).__name__}: {e}"
        if not ok:
            falhas += 1
        print(f"  {'ok  ' if ok else 'FALHA'} {pid:10s} {ato:34s} {nome[:34]}")
        if not ok:
            print(f"         esperava {chave!r} na ementa; veio: {texto[:110]}")
    print(f"\n{len(PROGRAMAS)} atos, {falhas} falha(s)")
    return 1 if falhas else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conferir", action="store_true")
    args = ap.parse_args()
    if args.conferir:
        return conferir()
    for pid, itens in por_presidente().items():
        print(f"\n{pid}")
        for i in itens:
            print(f"   {i['ato']:34s} {i['nome']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
