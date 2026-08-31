#!/usr/bin/env python3
"""O sistema eleitoral brasileiro, explicado com a eleição que de fato houve.

Existe porque explicação de sistema eleitoral costuma ser texto de manual, e
texto de manual não convence ninguém. Aqui cada afirmação sobre o voto
proporcional é conferível na eleição de 2022 do estado de quem lê.

O fato central que esta camada expõe: **119 candidatos a deputado federal
tiveram mais votos que alguém eleito do próprio estado e não foram eleitos.**
Isso não é fraude nem erro de apuração — é o desenho do voto proporcional,
em que a cadeira é ganha primeiro pelo PARTIDO e só depois distribuída entre
os candidatos dele. Quem não sabe disso acha que foi roubo; quem sabe passa a
discutir a regra, que é a conversa que interessa.

DUAS ARMADILHAS EDITORIAIS, as duas checadas em `conferir.py`:

  1. **'SUPLENTE' não quer dizer 'não está na Câmara'.** A situação vem da
     apuração de 2022. Suplente assume quando um titular sai — vira ministro,
     é cassado, licencia-se, morre. Orlando Silva (PC do B/SP) teve 108.059
     votos, ficou como suplente na apuração E exerce mandato hoje. Escrever
     "não se elegeu, mas está lá" está certo; escrever "não é deputado"
     seria falso sobre uma pessoa real. A página usa sempre "não foi eleito
     na apuração de 2022".
  2. **Não se publica quociente eleitoral calculado aqui.** O quociente
     oficial é `votos válidos ÷ cadeiras`, e votos válidos incluem os votos
     de LEGENDA (na sigla, sem candidato). A base `votacao_candidato_munzona`
     só traz voto nominal. Calcular o quociente sem a legenda daria um número
     menor que o verdadeiro, com cara de oficial. Então a mecânica é ensinada
     por uma eleição de mentirinha, com números redondos e assumidamente
     fictícios, e o dado real entra só onde é exato.

Uso:
    python3.13 pipeline/sistema.py --uf SE
    python3.13 pipeline/sistema.py --cep 49010-000
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
from consulta import municipio_por_cep, proveniencia, resolver_municipio

# Cadeiras de cada estado na Câmara. Número constitucional (CF art. 45 e LC
# 78/93), digitado da Constituição e não derivado do dado — é o que faz dele
# uma conferência de verdade, e não um espelho do próprio banco.
CADEIRAS = {
    "AC": 8, "AL": 9, "AP": 8, "AM": 8, "BA": 39, "CE": 22, "DF": 8,
    "ES": 10, "GO": 17, "MA": 18, "MT": 8, "MS": 8, "MG": 53, "PA": 17,
    "PB": 12, "PR": 30, "PE": 25, "PI": 10, "RJ": 46, "RN": 8, "RS": 31,
    "RO": 8, "RR": 8, "SC": 16, "SP": 70, "SE": 8, "TO": 8,
}

UF_NOME = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco",
    "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima",
    "SC": "Santa Catarina", "SP": "São Paulo", "SE": "Sergipe",
    "TO": "Tocantins",
}


def panorama(con, uf):
    """Quantos concorreram, quantos entraram e por qual caminho."""
    r = bd.um(con, """
        SELECT COUNT(*) FILTER (WHERE situacao = 'ELEITO POR QP')    AS por_quociente,
               COUNT(*) FILTER (WHERE situacao = 'ELEITO POR MEDIA') AS por_sobra,
               COUNT(*) FILTER (WHERE situacao = 'SUPLENTE')         AS nao_eleitos,
               COUNT(*)                                              AS total
        FROM deputado WHERE uf = %s
    """, (uf,))
    d = dict(r)
    d["eleitos"] = d["por_quociente"] + d["por_sobra"]
    d["cadeiras"] = CADEIRAS.get(uf)
    d["uf"] = uf
    d["uf_nome"] = UF_NOME.get(uf, uf)
    return d


def paradoxo(con, uf, limite=5):
    """Os casos em que mais voto não bastou, no estado.

    Compara cada não eleito com o eleito MENOS votado do mesmo estado. É a
    forma mais curta de mostrar que a cadeia 'mais voto → eleito' não vale
    no proporcional, sem precisar de nenhuma conta do quociente.
    """
    with con.cursor() as cur:
        cur.execute("""
            WITH v AS (
                SELECT d.sq_candidato, d.uf, d.nome_urna, d.partido, d.situacao,
                       d.id_camara, vt.total_votos
                FROM deputado d
                JOIN vw_votos_totais vt ON vt.sq_candidato = d.sq_candidato
                WHERE d.uf = %s
            ), piso AS (
                SELECT nome_urna, partido, total_votos
                FROM v WHERE situacao LIKE 'ELEITO%%'
                ORDER BY total_votos ASC LIMIT 1
            )
            SELECT v.nome_urna, v.partido, v.total_votos, v.id_camara,
                   p.nome_urna AS eleito_nome, p.partido AS eleito_partido,
                   p.total_votos AS eleito_votos
            FROM v, piso p
            WHERE v.situacao = 'SUPLENTE' AND v.total_votos > p.total_votos
            ORDER BY v.total_votos DESC
            LIMIT %s
        """, (uf, limite))
        return [dict(r) for r in cur.fetchall()]


def por_partido(con, uf, limite=8):
    """Votos NOMINAIS somados por partido, e quantas cadeiras o partido levou.

    'Nominais' é literal e a página precisa dizer isso: não entram os votos
    de legenda. Serve para mostrar a ordem de grandeza e a relação entre
    tamanho do partido e cadeiras — não para recalcular a distribuição.
    """
    with con.cursor() as cur:
        cur.execute("""
            SELECT d.partido,
                   SUM(vt.total_votos)                                AS votos,
                   COUNT(*) FILTER (WHERE d.situacao LIKE 'ELEITO%%') AS cadeiras,
                   COUNT(*)                                           AS candidatos
            FROM deputado d
            JOIN vw_votos_totais vt ON vt.sq_candidato = d.sq_candidato
            WHERE d.uf = %s
            GROUP BY 1 ORDER BY votos DESC LIMIT %s
        """, (uf, limite))
        return [dict(r) for r in cur.fetchall()]


def campeao_puxador(con, uf):
    """O mais votado do estado — o 'puxador de legenda' do livro-texto.

    Ele é o exemplo concreto de para que serve o voto proporcional: a votação
    excedente dele não é desperdiçada, ela conta para o partido e ajuda a
    eleger companheiros de chapa muito menos votados.
    """
    r = bd.um(con, """
        SELECT d.nome_urna, d.partido, d.situacao, d.id_camara, vt.total_votos
        FROM deputado d
        JOIN vw_votos_totais vt ON vt.sq_candidato = d.sq_candidato
        WHERE d.uf = %s ORDER BY vt.total_votos DESC LIMIT 1
    """, (uf,))
    return dict(r) if r else None


def nacional(con):
    """Os números do país inteiro, para a abertura da página."""
    r = bd.um(con, """
        SELECT COUNT(*) FILTER (WHERE situacao LIKE 'ELEITO%')       AS eleitos,
               COUNT(*) FILTER (WHERE situacao = 'ELEITO POR MEDIA') AS por_sobra,
               COUNT(*)                                              AS candidatos
        FROM deputado
    """)
    d = dict(r)
    d["mais_voto_sem_vaga"] = bd.um(con, """
        WITH v AS (
            SELECT d.uf, d.situacao, vt.total_votos
            FROM deputado d
            JOIN vw_votos_totais vt ON vt.sq_candidato = d.sq_candidato
        ), piso AS (
            SELECT uf, MIN(total_votos) AS m FROM v
            WHERE situacao LIKE 'ELEITO%' GROUP BY 1
        )
        SELECT COUNT(*) AS c FROM v JOIN piso p ON p.uf = v.uf
        WHERE v.situacao = 'SUPLENTE' AND v.total_votos > p.m
    """)["c"]
    return d


def retrato(con, uf):
    return {"uf": uf, "uf_nome": UF_NOME.get(uf, uf),
            "panorama": panorama(con, uf),
            "paradoxo": paradoxo(con, uf),
            "partidos": por_partido(con, uf),
            "puxador": campeao_puxador(con, uf),
            "nacional": nacional(con),
            "fontes": proveniencia(con)}


def imprimir(r):
    p = r["panorama"]
    print(f"\n{r['uf_nome']} ({r['uf']}) — eleição de 2022 para deputado federal")
    print(f"  {p['total']} candidatos disputaram {p['cadeiras']} cadeiras")
    print(f"  {p['por_quociente']} entraram pelo quociente do partido, "
          f"{p['por_sobra']} pelas sobras")
    if r["puxador"]:
        x = r["puxador"]
        print(f"  mais votado: {x['nome_urna']} ({x['partido']}) "
              f"{x['total_votos']:,} votos".replace(",", "."))
    print(f"\n  não foram eleitos, mesmo com mais votos que o eleito menos votado:")
    for c in r["paradoxo"]:
        marca = " [assumiu depois]" if c["id_camara"] else ""
        print(f"    {c['nome_urna'][:24]:24s} ({c['partido']:>12s}) "
              f"{c['total_votos']:>9,}{marca}".replace(",", "."))
    if r["paradoxo"]:
        c = r["paradoxo"][0]
        print(f"    ... enquanto {c['eleito_nome']} ({c['eleito_partido']}) "
              f"entrou com {c['eleito_votos']:,}".replace(",", "."))
    print(f"\n  no país: {r['nacional']['mais_voto_sem_vaga']} candidatos tiveram mais "
          f"voto que algum eleito do próprio estado e não foram eleitos")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uf")
    ap.add_argument("--cep")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    con = bd.conectar()
    uf = (args.uf or "").upper()
    if args.cep:
        nome, uf_cep, _, cod = municipio_por_cep(args.cep)
        uf = resolver_municipio(con, cod_ibge=cod, nome=nome, uf=uf_cep)["uf"]
    if uf not in CADEIRAS:
        return ap.error("informe --uf (sigla) ou --cep")
    r = retrato(con, uf)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        imprimir(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
