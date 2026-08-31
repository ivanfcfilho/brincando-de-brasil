# Instalar no servidor (luisa)

O servidor já hospeda **studiocantare.com** (Django na porta 8000, websocket na
8001) e um site estático em `/inglescomagrazi/`. Nada disso é tocado: o
Brincando de Brasil entra como mais um `location`, na porta **8010**.

Endereço final, até existir DNS próprio:
**https://studiocantare.com/brincandodebrasil/**

## O que já está feito

- código em `/opt/brincandodebrasil` (clone do GitHub);
- `.venv` com `psycopg2-binary`;
- `deploy/deploy.sh` atualiza tudo e **recusa publicar se as invariantes
  falharem**.

## O que precisa de sudo (4 passos)

### 1. Banco de dados

O Postgres 16 do servidor não tem a role do projeto. As quatro extensões que o
schema usa (`cube`, `earthdistance`, `unaccent`, `pg_trgm`) já estão
disponíveis — foi conferido.

```bash
sudo -u postgres psql -c "CREATE ROLE brincando LOGIN PASSWORD 'ESCOLHA_UMA_SENHA';"
sudo -u postgres psql -c "CREATE DATABASE brincando OWNER brincando;"
sudo -u postgres psql -d brincando -c "CREATE EXTENSION IF NOT EXISTS cube; CREATE EXTENSION IF NOT EXISTS earthdistance; CREATE EXTENSION IF NOT EXISTS unaccent; CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

Depois escreva a credencial em `/opt/brincandodebrasil/.env` (o arquivo **não**
vai para o git):

```bash
echo "CT_DSN=postgresql://brincando:ESCOLHA_UMA_SENHA@127.0.0.1:5432/brincando" \
  > /opt/brincandodebrasil/.env
chmod 600 /opt/brincandodebrasil/.env
```

### 2. Carregar os dados

O banco local tem 869 MB (1,96 M linhas de voto, 915 mil de emenda, 320 mil de
Ideb). Duas opções:

**a) restaurar o dump** (mais rápido, ~10 min) — o dump é gerado na máquina de
desenvolvimento e enviado por `scp`:

```bash
pg_restore --no-owner --no-acl -d brincando -U brincando -h 127.0.0.1 \
    /tmp/brincandodebrasil.dump
```

**b) rodar o pipeline no servidor** (mais lento, ~40 min, baixa 850 MB):

```bash
cd /opt/brincandodebrasil
./.venv/bin/pip install curl_cffi
./.venv/bin/python pipeline/db.py --init
# ... e a carga inicial do README, na ordem
```

### 3. O serviço

```bash
sudo cp /opt/brincandodebrasil/deploy/brincandodebrasil.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now brincandodebrasil
systemctl status brincandodebrasil --no-pager
curl -s http://127.0.0.1:8010/api/saude | head -c 200
```

### 4. O nginx

Insira o conteúdo de `deploy/nginx-brincandodebrasil.conf` dentro do bloco
`server { … }` de `/etc/nginx/sites-enabled/studiocantare.com`, **antes** do
`location / {`. Depois:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

`nginx -t` antes do reload não é frescura: uma vírgula errada aí derruba o
studiocantare.com junto.

## Atualizar depois

```bash
ssh kakashi@luisa 'bash /opt/brincandodebrasil/deploy/deploy.sh'
```

## Quando houver DNS próprio

Aí o site sai do subcaminho e vira um `server{}` só dele — o que é melhor,
porque o prefixo deixa de existir:

1. aponte o domínio para o IP do servidor;
2. novo arquivo em `sites-available` com `server_name` do domínio e
   `location / { proxy_pass http://127.0.0.1:8010/; }`;
3. `sudo certbot --nginx -d SEUDOMINIO`;
4. no serviço, **tire** o `--prefixo` do `ExecStart` e recarregue.
