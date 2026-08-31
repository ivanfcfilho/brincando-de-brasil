#!/usr/bin/env bash
# Atualiza o site no servidor. Idempotente: pode rodar quantas vezes quiser.
#
#   ssh kakashi@luisa 'bash /opt/brincandodebrasil/deploy/deploy.sh'
#
# NÃO precisa de sudo, exceto para reiniciar o serviço — que ele tenta e,
# se não puder, avisa em vez de fingir que deu certo.
set -euo pipefail

RAIZ="${RAIZ:-/opt/brincandodebrasil}"
cd "$RAIZ"

echo "── código"
git fetch --quiet origin
git checkout --quiet master
git pull --quiet --ff-only origin master
echo "   $(git rev-parse --short HEAD) $(git log -1 --pretty=%s)"

echo "── dependências"
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet psycopg2-binary
echo "   $(./.venv/bin/python --version), psycopg2 ok"

echo "── banco"
if ! ./.venv/bin/python pipeline/db.py --status 2>/dev/null | head -3; then
    echo "   AVISO: não consegui falar com o banco (confira CT_DSN no .env)"
    exit 1
fi

echo "── conferindo invariantes antes de publicar"
# Um número errado destrói a credibilidade de todos os certos: se as
# invariantes falham, o deploy PARA em vez de subir dado quebrado.
./.venv/bin/python pipeline/conferir.py

echo "── serviço"
if systemctl restart brincandodebrasil 2>/dev/null; then
    echo "   reiniciado"
elif sudo -n systemctl restart brincandodebrasil 2>/dev/null; then
    echo "   reiniciado (sudo)"
else
    echo "   NÃO reiniciei (precisa de sudo). Rode:"
    echo "     sudo systemctl restart brincandodebrasil"
fi

echo "── conferindo que respondeu"
sleep 2
if curl -fsS --max-time 15 http://127.0.0.1:8010/api/saude >/dev/null; then
    echo "   ok: http://127.0.0.1:8010 respondendo"
else
    echo "   FALHA: o app não respondeu na 8010"
    exit 1
fi
echo "pronto."
