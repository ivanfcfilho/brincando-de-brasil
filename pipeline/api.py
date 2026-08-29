#!/usr/bin/env python3
"""Servidor HTTP: serve a landing e responde a consulta por CEP.

Biblioteca padrão apenas — nenhum framework. O que a plataforma faz é uma
pergunta e uma resposta; não precisa de mais que isso para rodar local.

    python3.13 pipeline/api.py            # http://127.0.0.1:8000
    python3.13 pipeline/api.py --porta 9000

Rotas:
    GET /                      a landing
    GET /api/consulta?cep=…    a resposta, em JSON
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

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANDING = os.path.join(RAIZ, "landing")

# Páginas estáticas servidas por rota fixa. Lista explícita em vez de servir o
# diretório inteiro: sem isso, qualquer arquivo que caia em landing/ vai ao ar
# sem ninguém decidir, e ../ vira travessia de diretório.
PAGINAS = {
    "/": "index.html",
    "/index.html": "index.html",
    "/dinheiro.html": "dinheiro.html",
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
                with open(os.path.join(LANDING, PAGINAS[rota.path]), "rb") as f:
                    return self._enviar(200, f.read(), "text/html; charset=utf-8")
            if rota.path == "/api/saude":
                return self._json(200, self.saude())
            if rota.path == "/api/consulta":
                return self._json(*self.consulta(parse_qs(rota.query)))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    con = bd.conectar()
    n = bd.um(con, "SELECT COUNT(*) AS c FROM deputado WHERE situacao LIKE 'ELEITO%'")["c"]
    muni = bd.contar(con, "municipio")
    con.close()
    if not n or not muni:
        sys.exit("banco vazio — rode a carga inicial (ver README)")

    print(f"banco: {n} deputados eleitos, {muni} municípios")
    print(f"http://{args.host}:{args.porta}  (ctrl+c para parar)", flush=True)
    ThreadingHTTPServer((args.host, args.porta), Handler).serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nencerrado")
