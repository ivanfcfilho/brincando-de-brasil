#!/usr/bin/env python3
"""A cadeia de certificados que o INEP não envia.

O `download.inep.gov.br` apresenta **só o certificado folha** e omite o
intermediário da RNP que o assina. Isso não é ataque nem bundle local
desatualizado: é servidor mal configurado. O efeito é que todo cliente
honesto recusa a conexão —

    openssl verify: unable to get local issuer certificate (num=20)

— e a saída preguiçosa seria `verify=False`. Um projeto cuja premissa é
proveniência não pode baixar dado oficial por um canal que ele mesmo não
verifica: sem verificação, "veio do INEP" vira uma afirmação sem prova.

A saída correta é **fornecer o elo que falta**, sem afrouxar a confiança.
O próprio certificado folha publica onde encontrá-lo, na extensão AIA:

    CA Issuers - URI:http://secure.globalsign.com/cacert/rnpicpedugr46ovtlsca2025.crt

Esse intermediário é assinado pela **GlobalSign Root R46**, que já está no
armazém de raízes do sistema. Então, ao juntá-lo às raízes locais, a cadeia
fecha e a validação passa a ser genuína: a autenticidade do intermediário
continua sendo provada pela raiz, não por nós. Não se confia em nada novo —
só se entrega ao verificador uma peça que o servidor deveria ter mandado.

O certificado fica **versionado no repositório** (`certs/`), não é buscado em
tempo de execução: material de confiança baixado a cada job é uma porta de
entrada, e um arquivo em git é auditável no code review. Ele vence em
2030-11-19; `--atualizar` rebusca pela AIA quando chegar a hora.

Uso:
    python3.13 pipeline/tls.py --conferir     # a cadeia fecha?
    python3.13 pipeline/tls.py --atualizar    # rebusca o intermediário
"""
import argparse
import os
import ssl
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS = os.path.join(RAIZ, "certs")

# Intermediários que servidores oficiais esquecem de mandar, por host.
EXTRA = {
    "download.inep.gov.br": "rnp-icpedu-gr46-2025.pem",
}

_bundles = {}


def _raizes():
    """As raízes confiáveis do sistema (ou as do certifi, se houver)."""
    caminhos = [ssl.get_default_verify_paths().cafile,
                "/etc/ssl/certs/ca-certificates.crt",
                "/etc/pki/tls/certs/ca-bundle.crt"]
    try:
        import certifi
        caminhos.insert(0, certifi.where())
    except ImportError:
        pass
    for c in caminhos:
        if c and os.path.exists(c):
            return c
    raise RuntimeError("nenhum armazém de raízes encontrado no sistema")


def bundle(host):
    """Caminho de um bundle PEM = raízes do sistema + o elo que falta.

    Devolve None quando o host não precisa de remendo — aí o chamador usa a
    verificação padrão, sem passar nada.
    """
    if host not in EXTRA:
        return None
    if host in _bundles and os.path.exists(_bundles[host]):
        return _bundles[host]
    extra = os.path.join(CERTS, EXTRA[host])
    if not os.path.exists(extra):
        raise RuntimeError(f"falta o intermediário {extra} "
                           f"(rode: python3.13 pipeline/tls.py --atualizar)")
    fd, destino = tempfile.mkstemp(prefix=f"ct-cadeia-{host}-", suffix=".pem")
    with os.fdopen(fd, "wb") as saida:
        for parte in (_raizes(), extra):
            with open(parte, "rb") as f:
                saida.write(f.read())
            saida.write(b"\n")
    _bundles[host] = destino
    return destino


def verificacao(host):
    """O valor de `verify` para o curl_cffi: um bundle nosso, ou True.

    Nunca False. Se um host novo passar a exigir remendo, o download falha
    ruidosamente — e falhar é o comportamento certo.
    """
    return bundle(host) or True


# --------------------------------------------------------------------- conferência

def _openssl(*args, entrada=None):
    return subprocess.run(["openssl", *args], input=entrada,
                          capture_output=True, timeout=90)


def conferir(host, tentativas=4):
    """A cadeia fecha com o nosso bundle? Devolve (ok, explicação).

    Com retry pelo mesmo motivo do download: o servidor do INEP derruba a
    conexão de vez em quando, e uma queda dessas não é falha de verificação.
    Reportá-la como se fosse mandaria alguém investigar um problema de
    confiança que não existe — alarme errado gasta a credibilidade do alarme.
    """
    b = bundle(host)
    for tentativa in range(tentativas):
        r = _openssl("s_client", "-connect", f"{host}:443", "-servername", host,
                     "-CAfile", b or _raizes(), entrada=b"")
        for linha in r.stdout.decode("utf8", "replace").splitlines():
            if linha.startswith("    Verify return code:"):
                codigo = linha.split(":", 1)[1].strip()
                return codigo.startswith("0 "), codigo
        if tentativa < tentativas - 1:
            time.sleep(2 ** tentativa)
    erro = r.stderr.decode("utf8", "replace").strip().splitlines()
    return False, ("conexão não completou em "
                   f"{tentativas} tentativas ({erro[-1] if erro else 'sem detalhe'})")


def atualizar(host):
    """Rebusca o intermediário pela AIA do certificado folha e o grava.

    Só grava se o resultado **fechar a cadeia contra as raízes do sistema** —
    do contrário estaríamos versionando um certificado que não prova nada.
    """
    r = _openssl("s_client", "-connect", f"{host}:443", "-servername", host,
                 entrada=b"")
    folha = _openssl("x509", entrada=r.stdout).stdout
    texto = _openssl("x509", "-noout", "-text", entrada=folha).stdout.decode("utf8", "replace")
    url = None
    for linha in texto.splitlines():
        if "CA Issuers - URI:" in linha:
            url = linha.split("URI:", 1)[1].strip()
            break
    if not url:
        return print(f"{host}: o certificado não publica AIA — nada a buscar")

    print(f"{host}: buscando o intermediário em {url}")
    import urllib.request
    with urllib.request.urlopen(url, timeout=60) as resp:   # http:// por desenho
        bruto = resp.read()                                  # (é um certificado,
    # e sua autenticidade é provada pela raiz, não pelo transporte)
    pem = _openssl("x509", "-inform", "DER", entrada=bruto).stdout
    if not pem.startswith(b"-----BEGIN"):
        pem = _openssl("x509", entrada=bruto).stdout
    if not pem.startswith(b"-----BEGIN"):
        return print(f"{host}: não consegui ler o certificado baixado")

    with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f:
        f.write(pem)
        temp = f.name
    v = _openssl("verify", "-CAfile", _raizes(), temp)
    if v.returncode != 0:
        os.unlink(temp)
        return print(f"{host}: o intermediário NÃO fecha contra as raízes do "
                     f"sistema — recusado.\n{v.stdout.decode()}{v.stderr.decode()}")
    os.makedirs(CERTS, exist_ok=True)
    destino = os.path.join(CERTS, EXTRA[host])
    os.replace(temp, destino)
    _bundles.pop(host, None)
    print(f"{host}: gravado em {destino}")
    print(_openssl("x509", "-in", destino, "-noout", "-subject", "-issuer",
                   "-dates").stdout.decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conferir", action="store_true")
    ap.add_argument("--atualizar", action="store_true")
    ap.add_argument("--host", default=None)
    args = ap.parse_args()
    hosts = [args.host] if args.host else list(EXTRA)

    if args.atualizar:
        for h in hosts:
            atualizar(h)
        return 0

    falhou = False
    for h in hosts:
        ok, motivo = conferir(h)
        print(f"{'ok  ' if ok else 'FALHA'} {h}: {motivo}")
        falhou |= not ok
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
