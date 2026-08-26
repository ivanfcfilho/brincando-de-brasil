# MEMÓRIA DO PROJETO — retomar daqui

> Contexto de continuidade para a próxima sessão de trabalho.
> Última atualização: 2026-08-26.

## O que este projeto é

"O Código de Transição" — plataforma de pressão por reforma política
(PEC do Voto Distrital Misto + fim das emendas impositivas) via transparência
de dados: cruzamento **origem do voto (TSE) × destino da emenda (Portal da
Transparência)**, consumível por CEP. Landing protótipo em `landing/index.html`
(publicada como Artifact no Claude Code; tema dark + amarelo elétrico).

## Estado atual (feito e validado)

- Pipeline completo rodou com **dados reais**: piloto de Sergipe em
  `relatorio/PILOTO_SE.md` + matriz em `data/out/piloto_SE_deputado_municipio.csv`.
- Dados brutos (~830 MB) já baixados em `data/raw/` (gitignorados):
  `votacao_candidato_munzona_2022.zip` (TSE, nacional) e
  `EmendasParlamentares.zip/.csv` (CGU, snapshot de 25/08/2026).
- Rodar outro estado é imediato: `python3 pipeline/cruzamento.py --uf BA`.

## Decisões e aprendizados que NÃO estão óbvios no código

1. **CDN do TSE bloqueia CLI** (Akamai, fingerprint TLS). Só passa com
   `curl_cffi` + `impersonate="chrome"` (instalado no **python3.13**, não no
   3.10 default). Download por faixas com resume em `pipeline/download_tse.py`.
   O bloqueio é intermitente — se voltar 403, esperar e retomar (tem resume).
2. **70–95% do "destino planejado" das emendas vem como Múltiplo/Sem
   informação.** A visão que resolve é a base `EmendasParlamentares_PorFavorecido.csv`
   (Valor Recebido por município do favorecido). O relatório traz as duas
   visões. Essa opacidade é achado/argumento, não defeito.
3. **Casamento por nome é frágil**: autor da emenda = nome parlamentar;
   TSE = nome civil + urna. Fallback por tokens + `pipeline/aliases.json`
   (caso real: `YANDRA MOURA` → `YANDRA DE ANDRÉ`). O definitivo é casar por
   código de autor da Câmara × SQ_CANDIDATO.
4. **Regra editorial inegociável**: nunca publicar inferência ("desviou") —
   só origem, destino, percentual e link para fonte. É a blindagem jurídica e
   de credibilidade do projeto inteiro (ver seção "doutrina" da landing).
5. **Estratégia** (discutido na sessão): transparência radical no lugar de
   anonimato (anonimato é vedado — CF art. 5º IV — e derrubaria o movimento);
   zero disparo automatizado de WhatsApp (usar click-to-chat enviado pelo
   próprio cidadão); LGPD com opt-in explícito para CEP/contato.

## Próximos passos (em ordem de destrave)

1. **Tabela TSE↔IBGE de municípios + coordenadas** → calcular a distância em
   km entre voto e verba (o número da manchete). Fontes: TSE publica
   correspondência; IBGE tem centroides municipais.
2. **Granularidade por seção eleitoral** (`votacao_secao_{ano}_{UF}.zip` no
   mesmo repositório odsele do TSE) → é o que liga o dado ao CEP.
3. **Casamento por código**: API da Câmara (`dadosabertos.camara.leg.br`,
   id do deputado) × "Código do Autor da Emenda" da base CGU × SQ_CANDIDATO.
4. Rodar todos os 27 estados e ranquear divergências (achar os casos-manchete
   com verificação dupla manual antes de qualquer uso público).
5. API + frontend: a landing (`landing/index.html`) vira o shell da busca real
   por CEP (ViaCEP → município → seção eleitoral → deputados → emendas).

## Como retomar

```bash
cd ~/codigo-de-transicao
# dados já em data/raw/; se faltar:
python3 pipeline/download_emendas.py
python3.13 pipeline/download_tse.py --ano 2022
python3 pipeline/cruzamento.py --uf SE   # ou qualquer UF
```
