-- Esquema do banco "O Código de Transição" — PostgreSQL 18.
--
-- Três camadas, nesta ordem de importância:
--
--   1. PROVENIÊNCIA (fonte, checagem, snapshot) — de qual arquivo oficial,
--      baixado quando, com qual hash, veio cada número. É o que sustenta a
--      regra editorial "todo número rastreável à fonte". Sem isso o banco é
--      só um cache; com isso ele é evidência.
--   2. DOMÍNIO (municipio, deputado, voto_municipio, autor, emenda,
--      emenda_favorecido) — o estado atual, substituído a cada snapshot.
--   3. MUDANÇA (mudanca) — o diff entre snapshots. É o que transforma o job
--      diário em conteúdo ("neste dia, este empenho subiu de A para B") em
--      vez de só frescor de dado.
--
-- Valores monetários são NUMERIC(18,2), nunca float: centavo que "anda"
-- por arredondamento binário vira número errado publicado, e um número
-- errado destrói a credibilidade de todos os certos.

CREATE EXTENSION IF NOT EXISTS cube;
CREATE EXTENSION IF NOT EXISTS earthdistance;  -- distância voto ↔ verba
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;        -- casamento aproximado de nomes

-- ---------------------------------------------------------------- proveniência

CREATE TABLE IF NOT EXISTS fonte (
    id            TEXT PRIMARY KEY,
    descricao     TEXT NOT NULL,
    url           TEXT NOT NULL,
    periodicidade TEXT NOT NULL CHECK (periodicidade IN ('diaria','eleicao'))
);

-- Registro de TODA verificação, inclusive as que não acharam mudança:
-- "nós olhamos e nada mudou" também é afirmação que precisa de prova.
CREATE TABLE IF NOT EXISTS checagem (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte_id      TEXT NOT NULL REFERENCES fonte(id),
    checado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    etag          TEXT,
    last_modified TEXT,
    tamanho       BIGINT,
    mudou         BOOLEAN NOT NULL,
    erro          TEXT
);
CREATE INDEX IF NOT EXISTS ix_checagem_fonte ON checagem(fonte_id, checado_em DESC);

CREATE TABLE IF NOT EXISTS snapshot (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fonte_id      TEXT NOT NULL REFERENCES fonte(id),
    baixado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    publicado_em  TEXT,               -- Last-Modified declarado pelo servidor
    etag          TEXT,
    tamanho       BIGINT,
    sha256        TEXT NOT NULL,      -- identidade do arquivo oficial
    arquivo       TEXT NOT NULL,
    ingerido_em   TIMESTAMPTZ,
    linhas        BIGINT,
    UNIQUE (fonte_id, sha256)
);
CREATE INDEX IF NOT EXISTS ix_snapshot_fonte ON snapshot(fonte_id, baixado_em DESC);

-- ------------------------------------------------------------------- domínio

-- Ponte TSE ↔ IBGE + coordenadas: a distância em km entre o voto e a verba.
CREATE TABLE IF NOT EXISTS municipio (
    cod_ibge  INTEGER PRIMARY KEY,
    nome      TEXT NOT NULL,
    nome_norm TEXT NOT NULL,
    uf        TEXT NOT NULL,
    cod_tse   INTEGER,
    lat       DOUBLE PRECISION,
    lon       DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS ix_municipio_tse  ON municipio(cod_tse);
CREATE INDEX IF NOT EXISTS ix_municipio_nome ON municipio(uf, nome_norm);
CREATE INDEX IF NOT EXISTS ix_municipio_trgm ON municipio USING gin (nome_norm gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_municipio_geo  ON municipio USING gist (ll_to_earth(lat, lon))
    WHERE lat IS NOT NULL;

CREATE TABLE IF NOT EXISTS deputado (
    sq_candidato TEXT PRIMARY KEY,
    ano_eleicao  INTEGER NOT NULL,
    uf           TEXT NOT NULL,
    nome         TEXT NOT NULL,       -- civil, normalizado
    nome_urna    TEXT NOT NULL,
    partido      TEXT,
    situacao     TEXT,                -- ELEITO POR QP | ELEITO POR MÉDIA | SUPLENTE
    id_camara    INTEGER,             -- dadosabertos.camara.leg.br (a preencher)
    snapshot_id  BIGINT REFERENCES snapshot(id)
);
CREATE INDEX IF NOT EXISTS ix_deputado_uf   ON deputado(uf, ano_eleicao);
CREATE INDEX IF NOT EXISTS ix_deputado_trgm ON deputado USING gin (nome gin_trgm_ops);

CREATE TABLE IF NOT EXISTS voto_municipio (
    sq_candidato      TEXT NOT NULL REFERENCES deputado(sq_candidato),
    ano_eleicao       INTEGER NOT NULL,
    uf                TEXT NOT NULL,
    cod_municipio_tse INTEGER NOT NULL,
    municipio_norm    TEXT NOT NULL,
    votos             BIGINT NOT NULL,
    snapshot_id       BIGINT REFERENCES snapshot(id),
    PRIMARY KEY (sq_candidato, cod_municipio_tse)
);
CREATE INDEX IF NOT EXISTS ix_voto_mun ON voto_municipio(uf, municipio_norm);
CREATE INDEX IF NOT EXISTS ix_voto_tse ON voto_municipio(cod_municipio_tse);

-- Autores de emenda. O 'Código do Autor da Emenda' é estável; o nome não é
-- (89 dos ~1.573 autores aparecem com mais de uma grafia). Por isso o vínculo
-- com o TSE mora aqui, casado uma vez e persistido — e conferido = TRUE marca
-- vínculo checado por humano, que a reingestão nunca sobrescreve.
CREATE TABLE IF NOT EXISTS autor (
    cod_autor    TEXT PRIMARY KEY,
    nome         TEXT NOT NULL,
    nome_norm    TEXT NOT NULL,
    sq_candidato TEXT REFERENCES deputado(sq_candidato),
    metodo_match TEXT,                -- exato | alias | tokens | manual
    conferido    BOOLEAN NOT NULL DEFAULT FALSE,
    vinculado_em TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_autor_sq ON autor(sq_candidato);

-- Visão "destino planejado" (EmendasParlamentares.csv).
CREATE TABLE IF NOT EXISTS emenda (
    chave              TEXT PRIMARY KEY,   -- hash determinístico da chave natural
    codigo_emenda      TEXT,
    ano                INTEGER,
    tipo               TEXT,
    cod_autor          TEXT,
    numero             TEXT,
    localidade         TEXT,
    cod_ibge           INTEGER,
    municipio          TEXT,
    uf                 TEXT,
    cod_funcao         TEXT,
    nome_funcao        TEXT,
    cod_subfuncao      TEXT,
    nome_subfuncao     TEXT,
    cod_acao           TEXT,
    nome_acao          TEXT,
    plano_orcamentario TEXT,
    empenhado          NUMERIC(18,2) NOT NULL DEFAULT 0,
    liquidado          NUMERIC(18,2) NOT NULL DEFAULT 0,
    pago               NUMERIC(18,2) NOT NULL DEFAULT 0,
    rp_inscritos       NUMERIC(18,2) NOT NULL DEFAULT 0,
    rp_cancelados      NUMERIC(18,2) NOT NULL DEFAULT 0,
    rp_pagos           NUMERIC(18,2) NOT NULL DEFAULT 0,
    snapshot_id        BIGINT REFERENCES snapshot(id)
);
CREATE INDEX IF NOT EXISTS ix_emenda_autor ON emenda(cod_autor, ano);
CREATE INDEX IF NOT EXISTS ix_emenda_mun   ON emenda(uf, municipio);
CREATE INDEX IF NOT EXISTS ix_emenda_ibge  ON emenda(cod_ibge);

-- Visão "execução financeira" (EmendasParlamentares_PorFavorecido.csv):
-- quem de fato recebeu, por município do favorecido.
CREATE TABLE IF NOT EXISTS emenda_favorecido (
    chave                TEXT PRIMARY KEY,
    codigo_emenda        TEXT,
    cod_autor            TEXT,
    numero               TEXT,
    tipo                 TEXT,
    ano_mes              TEXT,
    ano                  INTEGER,
    cod_favorecido       TEXT,
    favorecido           TEXT,
    natureza_juridica    TEXT,
    tipo_favorecido      TEXT,
    uf_favorecido        TEXT,
    municipio_favorecido TEXT,
    -- A CGU dá o código IBGE no destino planejado, mas só o nome no
    -- favorecido. Resolvemos na ingestão, com a mesma chave tolerante do
    -- casamento TSE↔IBGE, para que a distância em km seja um join por código.
    cod_ibge_favorecido  INTEGER,
    valor_recebido       NUMERIC(18,2) NOT NULL DEFAULT 0,
    snapshot_id          BIGINT REFERENCES snapshot(id)
);
-- Migrações: este arquivo é reaplicado a cada `db.py --init`, e
-- CREATE TABLE IF NOT EXISTS não alcança tabela que já existe. Toda coluna
-- acrescentada depois da primeira versão precisa aparecer aqui também.
ALTER TABLE emenda_favorecido ADD COLUMN IF NOT EXISTS cod_ibge_favorecido INTEGER;

CREATE INDEX IF NOT EXISTS ix_fav_autor ON emenda_favorecido(cod_autor, ano);
CREATE INDEX IF NOT EXISTS ix_fav_mun   ON emenda_favorecido(uf_favorecido, municipio_favorecido);
CREATE INDEX IF NOT EXISTS ix_fav_ibge  ON emenda_favorecido(cod_ibge_favorecido);

-- -------------------------------------------------------------------- mudança

-- Uma linha aqui é uma TRANSIÇÃO entre dois snapshots, não um fato do
-- snapshot de destino. Guardar só o destino fazia uma reingestão do mesmo
-- arquivo (que produz diff vazio, porque o banco já é aquele estado) apagar
-- o histórico verdadeiro da transição anterior.
CREATE TABLE IF NOT EXISTS mudanca (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    detectado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    snapshot_anterior  BIGINT REFERENCES snapshot(id),
    snapshot_id  BIGINT NOT NULL REFERENCES snapshot(id),
    tabela       TEXT NOT NULL,
    chave        TEXT NOT NULL,
    tipo         TEXT NOT NULL CHECK (tipo IN ('nova','alterada','removida')),
    campo        TEXT,
    valor_antes  NUMERIC(18,2),
    valor_depois NUMERIC(18,2),
    cod_autor    TEXT,
    uf           TEXT,
    municipio    TEXT
);
ALTER TABLE mudanca ADD COLUMN IF NOT EXISTS snapshot_anterior BIGINT
    REFERENCES snapshot(id);

CREATE INDEX IF NOT EXISTS ix_mudanca_data  ON mudanca(detectado_em DESC);
CREATE INDEX IF NOT EXISTS ix_mudanca_par   ON mudanca(snapshot_anterior, snapshot_id);
CREATE INDEX IF NOT EXISTS ix_mudanca_autor ON mudanca(cod_autor, detectado_em DESC);

-- ---------------------------------------------------------------------- vistas
--
-- DROP + CREATE em vez de CREATE OR REPLACE: as vistas usam SELECT *, e
-- acrescentar uma coluna na tabela muda a ordem das colunas da vista, o que
-- o REPLACE recusa.

DROP VIEW IF EXISTS vw_votos_totais CASCADE;
CREATE VIEW vw_votos_totais AS
SELECT sq_candidato, uf, ano_eleicao, SUM(votos) AS total_votos
FROM voto_municipio GROUP BY sq_candidato, uf, ano_eleicao;

DROP VIEW IF EXISTS vw_emenda_deputado CASCADE;
CREATE VIEW vw_emenda_deputado AS
SELECT e.*, a.sq_candidato, d.uf AS uf_deputado, d.nome_urna, d.partido
FROM emenda e
JOIN autor a    ON a.cod_autor = e.cod_autor
JOIN deputado d ON d.sq_candidato = a.sq_candidato;

DROP VIEW IF EXISTS vw_favorecido_deputado CASCADE;
CREATE VIEW vw_favorecido_deputado AS
SELECT f.*, a.sq_candidato, d.uf AS uf_deputado, d.nome_urna, d.partido
FROM emenda_favorecido f
JOIN autor a    ON a.cod_autor = f.cod_autor
JOIN deputado d ON d.sq_candidato = a.sq_candidato;
