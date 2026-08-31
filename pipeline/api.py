#!/usr/bin/env python3
"""Servidor HTTP: serve a landing e responde a consulta por CEP.

Biblioteca padrão apenas — nenhum framework. O que a plataforma faz é uma
pergunta e uma resposta; não precisa de mais que isso para rodar local.

    python3.13 pipeline/api.py            # http://127.0.0.1:8000
    python3.13 pipeline/api.py --porta 9000

Rotas:
    GET /                      a landing
    GET /api/consulta?cep=…    para onde foi a emenda de quem tem voto aqui
    GET /api/educacao?cep=…    como está a escola daqui, e quem responde por ela
    GET /api/sistema?uf=…      como o voto virou cadeira naquele estado, em 2022
    GET /api/saude             o que há no banco e de quando é
"""
import argparse
import json
import os
import sys
import threading
import traceback
from datetime import date, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
from consulta import municipio_por_cep, proveniencia, resolver_municipio, responder
from educacao import retrato
from sistema import CADEIRAS, retrato as retrato_sistema

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANDING = os.path.join(RAIZ, "landing")

# O site pode viver na raiz de um domínio ou sob um prefixo de caminho
# (ex.: /brincandodebrasil), atrás de um nginx que já hospeda outra coisa.
#
# As ROTAS não mudam: o nginx tira o prefixo antes de repassar
# (`proxy_pass http://127.0.0.1:PORTA/` com a barra no fim). O que muda é o
# HTML que sai daqui — todo link do site é de raiz (`/escola.html`,
# `fetch('/api/…')`) e, sob prefixo, apontaria para fora da aplicação.
# Por isso a reescrita acontece na saída, num lugar só.
PREFIXO = ""

# Páginas estáticas servidas por rota fixa. Lista explícita em vez de servir o
# diretório inteiro: sem isso, qualquer arquivo que caia em landing/ vai ao ar
# sem ninguém decidir, e ../ vira travessia de diretório.
PAGINAS = {
    "/": "index.html",
    "/index.html": "index.html",
    "/dinheiro.html": "dinheiro.html",
    "/escola.html": "escola.html",
    "/como-funciona.html": "como-funciona.html",
    "/menu.js": "menu.js",
    "/propostas/educacao.html": os.path.join("propostas", "educacao.html"),
    "/propostas/voto-distrital.html": os.path.join("propostas", "voto-distrital.html"),
}

# Uma conexão por thread: conexão de psycopg2 não é segura para compartilhar
# entre threads, e abrir uma por requisição desperdiça o handshake.
_local = threading.local()


def conexao():
    con = getattr(_local, "con", None)
    if con is None or con.closed:
        con = _local.con = bd.conectar()
    return con


class Codificador(json.JSONEncoder):
    """NUMERIC vira string, não float: converter dinheiro para float é
    justamente o que a escolha de NUMERIC no banco evitou."""

    def default(self, o):
        if isinstance(o, Decimal):
            return format(o, "f")
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        return super().default(o)


class Handler(BaseHTTPRequestHandler):
    server_version = "codigo-de-transicao"

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}", flush=True)

    @staticmethod
    def _com_prefixo(html):
        """Reescreve os links de raiz do HTML para viverem sob PREFIXO.

        Só toca em caminhos que começam com barra: `href="https://…` e
        `href="#ancora"` passam intactos. O prefixo também é publicado em
        `window.BB_PREFIXO`, porque o menu.js monta os links dele em
        JavaScript e não passa por esta reescrita.
        """
        if not PREFIXO:
            return html
        s = html.decode("utf-8")
        for antes, depois in (('href="/', f'href="{PREFIXO}/'),
                              ('src="/', f'src="{PREFIXO}/'),
                              ("fetch('/", f"fetch('{PREFIXO}/")):
            s = s.replace(antes, depois)
        # Antes do primeiro <script>, para que o menu.js já encontre o valor.
        s = s.replace("<script", f"<script>window.BB_PREFIXO="
                                 f"{json.dumps(PREFIXO)}</script>\n<script", 1)
        return s.encode("utf-8")

    def _enviar(self, codigo, corpo, tipo="application/json; charset=utf-8"):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, codigo, obj):
        self._enviar(codigo, json.dumps(obj, ensure_ascii=False, cls=Codificador))

    def do_GET(self):
        rota = urlparse(self.path)
        try:
            if rota.path in PAGINAS:
                arquivo = PAGINAS[rota.path]
                tipo = ("text/javascript; charset=utf-8" if arquivo.endswith(".js")
                        else "text/html; charset=utf-8")
                with open(os.path.join(LANDING, arquivo), "rb") as f:
                    corpo = f.read()
                if arquivo.endswith(".html"):
                    corpo = self._com_prefixo(corpo)
                return self._enviar(200, corpo, tipo)
            if rota.path == "/api/saude":
                return self._json(200, self.saude())
            if rota.path == "/api/consulta":
                return self._json(*self.consulta(parse_qs(rota.query)))
            if rota.path == "/api/educacao":
                return self._json(*self.educacao(parse_qs(rota.query)))
            if rota.path == "/api/sistema":
                return self._json(*self.sistema(parse_qs(rota.query)))
            self._json(404, {"erro": "rota não encontrada"})
        except Exception as e:
            traceback.print_exc()
            self._json(500, {"erro": f"{type(e).__name__}: {e}"})

    def saude(self):
        con = conexao()
        return {"ok": True,
                "deputados_eleitos": bd.um(
                    con, "SELECT COUNT(*) AS c FROM deputado "
                         "WHERE situacao LIKE 'ELEITO%'")["c"],
                "municipios": bd.contar(con, "municipio"),
                "emendas": bd.contar(con, "emenda"),
                # Cidades com nota medida, não linhas da tabela: o placar fala
                # com o cidadão, e "319 mil medições" não diz nada a ele.
                "municipios_com_ideb": bd.um(
                    con, "SELECT COUNT(DISTINCT cod_ibge) AS c FROM ideb "
                         "WHERE ideb IS NOT NULL")["c"],
                # A home afirma este número em texto corrido. Vindo daqui,
                # ele não pode envelhecer sem alguém perceber.
                "mais_voto_sem_vaga": bd.um(con, """
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
                """)["c"],
                "fontes": proveniencia(con)}

    def consulta(self, q):
        cep = (q.get("cep") or [""])[0]
        limite = min(int((q.get("limite") or ["5"])[0]), 15)
        con = conexao()
        try:
            nome, uf, bairro, cod = municipio_por_cep(cep)
            origem = resolver_municipio(con, cod_ibge=cod, nome=nome, uf=uf)
        except ValueError as e:
            # CEP inexistente é erro do usuário, não do servidor.
            return 400, {"erro": str(e)}
        r = responder(con, origem, bairro, limite)
        r["cep"] = cep
        return 200, r

    def educacao(self, q):
        con = conexao()
        try:
            origem, _ = _municipio_da_query(con, q)
        except ValueError as e:
            return 400, {"erro": str(e)}
        r = retrato(con, origem)
        r["cep"] = (q.get("cep") or [""])[0]
        return 200, r

    def sistema(self, q):
        """UF direta, ou a UF do CEP. A sigla é validada contra a lista das 27
        antes de chegar ao banco: parâmetro de URL é entrada de terceiro."""
        con = conexao()
        uf = (q.get("uf") or [""])[0].upper()
        if not uf and (q.get("cep") or q.get("municipio")):
            try:
                origem, _ = _municipio_da_query(con, q)
                uf = origem["uf"]
            except ValueError as e:
                return 400, {"erro": str(e)}
        if uf not in CADEIRAS:
            return 400, {"erro": "informe uf (sigla de estado) ou cep"}
        return 200, retrato_sistema(con, uf)


def _municipio_da_query(con, q):
    """CEP ou município/UF → a linha de `municipio`. Levanta ValueError com
    mensagem para o usuário quando a entrada é que está errada."""
    cep = (q.get("cep") or [""])[0]
    if cep:
        nome, uf, bairro, cod = municipio_por_cep(cep)
        return resolver_municipio(con, cod_ibge=cod, nome=nome, uf=uf), bairro
    nome = (q.get("municipio") or [""])[0]
    uf = (q.get("uf") or [""])[0]
    if nome and uf:
        return resolver_municipio(con, nome=nome, uf=uf), ""
    raise ValueError("informe cep, ou municipio e uf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--prefixo", default=os.environ.get("BB_PREFIXO", ""),
                    help="caminho onde o site vive (ex.: /brincandodebrasil)")
    args = ap.parse_args()

    global PREFIXO
    PREFIXO = args.prefixo.rstrip("/")
    if PREFIXO and not PREFIXO.startswith("/"):
        PREFIXO = "/" + PREFIXO

    con = bd.conectar()
    n = bd.um(con, "SELECT COUNT(*) AS c FROM deputado WHERE situacao LIKE 'ELEITO%'")["c"]
    muni = bd.contar(con, "municipio")
    con.close()
    if not n or not muni:
        sys.exit("banco vazio — rode a carga inicial (ver README)")

    print(f"banco: {n} deputados eleitos, {muni} municípios")
    if PREFIXO:
        print(f"servindo sob o prefixo {PREFIXO}")
    print(f"http://{args.host}:{args.porta}{PREFIXO or ''}  (ctrl+c para parar)",
          flush=True)
    ThreadingHTTPServer((args.host, args.porta), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nencerrado")
