# O Código de Transição — estudo piloto

Prova de conceito do cruzamento **origem do voto × destino da emenda**, a
métrica central da plataforma "O Seu Dinheiro Não Chegou no Seu Bairro".

Para cada deputado federal eleito no estado piloto, o pipeline responde:

> De onde vieram os votos (TSE, urna por urna, agregado por município) e para
> onde foram as emendas parlamentares do mandato (Portal da Transparência)?

## Estrutura

```
landing/index.html   protótipo da landing page (busca por CEP, dados simulados)
pipeline/
  download_tse.py      votação por município/zona (TSE dados abertos)
  download_emendas.py  base de emendas parlamentares (CGU dados abertos)
  cruzamento.py        o cruzamento e o relatório
data/raw/            dumps oficiais (não versionados — ~800 MB)
data/out/            matriz deputado × município (CSV)
relatorio/           relatório legível do piloto (Markdown)
```

## Como rodar

```bash
pip install curl_cffi              # só para o download do TSE (ver abaixo)
python3.13 pipeline/download_tse.py --ano 2022
python3 pipeline/download_emendas.py
python3 pipeline/cruzamento.py --uf SE
```

O CDN do TSE (Akamai) bloqueia fingerprint TLS de ferramentas de linha de
comando; `download_tse.py` usa `curl_cffi` com impersonation de Chrome e
download por faixas com resume. O restante do pipeline é stdlib pura.

## Fontes (oficiais, públicas, sem autenticação)

- **TSE — dados abertos**: `votacao_candidato_munzona_<ano>.zip`
  (votos nominais por candidato, município e zona).
- **Portal da Transparência / CGU**: `EmendasParlamentares.zip`
  (autor, ano, município IBGE de destino, valores empenhado/liquidado/pago).

## Regras editoriais (inegociáveis)

1. **Nenhuma inferência.** O pipeline nunca escreve "desviou" ou "abandonou":
   publica origem dos votos, destino da verba e o percentual de divergência.
   Emenda destinada a outro município **é legal** — a conclusão é do leitor.
2. **Todo número rastreável à fonte.** Na plataforma real, cada valor linka o
   documento oficial de origem.
3. **Verificação dupla antes de publicar.** Um número errado destrói a
   credibilidade de todos os certos.

## Ressalvas metodológicas conhecidas (piloto)

- **Casamento por nome.** O autor da emenda vem como nome parlamentar; o TSE
  traz nome civil e nome de urna. O casamento é por nome normalizado com
  fallback por tokens; homônimos ambíguos são descartados e logados. A versão
  de produção deve casar por código do autor (Câmara) × SQ_CANDIDATO (TSE).
- **Municípios por nome, não por código.** O TSE usa código próprio, as
  emendas usam IBGE. O piloto casa por nome normalizado dentro da UF; a versão
  real precisa da tabela de correspondência TSE↔IBGE.
- **Empenhado ≠ pago.** O relatório usa valor empenhado (compromisso firmado);
  anos recentes têm pagamento em aberto por natureza.
- **Emendas de relator/comissão (RP8/RP9)** não têm autor individual — não
  aparecem no cruzamento. Essa opacidade é, em si, um dos argumentos da PEC.
- **Licenças e suplências**: deputado licenciado pode ter emendas em nome do
  titular; casos sem match ficam listados no log para revisão manual.
- **Apelidos** (`pipeline/aliases.json`): nomes parlamentares que não batem
  com o civil nem com o de urna são mapeados manualmente
  (ex.: `YANDRA MOURA` → `YANDRA DE ANDRÉ`).
- **Destino planejado × execução.** No destino planejado, 70–95% dos empenhos
  vêm como "Múltiplo"/"Sem informação" — essa opacidade é um achado do piloto,
  não um defeito dele. Por isso o relatório traz uma segunda visão pela base
  *PorFavorecido* (quem de fato recebeu, por município), com a ressalva de que
  a sede do favorecido não é necessariamente o local de aplicação (fundos
  estaduais e ministérios puxam valores para capitais e para Brasília).

## Próximos passos

- [ ] Tabela TSE↔IBGE de municípios + coordenadas (distância em km do voto à verba)
- [ ] Granularidade por seção eleitoral (`votacao_secao_<ano>_<UF>.zip`) → CEP
- [ ] API pública + frontend (a landing em `landing/` vira o shell real)
- [ ] Validação da metodologia por terceiros antes de qualquer publicação
