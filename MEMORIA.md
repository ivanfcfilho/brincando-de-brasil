# MEMÓRIA DO PROJETO — retomar daqui

> Contexto de continuidade para a próxima sessão de trabalho.
> Última atualização: 2026-08-29.

## O que este projeto é

"O Código de Transição" — plataforma de pressão por reforma política
(PEC do Voto Distrital Misto + fim das emendas impositivas) via transparência
de dados: cruzamento **origem do voto (TSE) × destino da emenda (CGU)**,
consumível por CEP. Landing protótipo em `landing/index.html`.

## Estado atual

Saiu de "scripts que leem ZIP e cospem Markdown" para **banco + job diário**:

- **Postgres 18** (container `nexus-postgres-18`, porta 5433), banco e role
  dedicados `codigo_transicao`. Credencial em `.env` (`CT_DSN`), fora do git.
- Carregado: 4.708 deputados (513 eleitos + 4.195 suplentes), 1,96 M linhas de
  voto por município, 94 mil emendas (destino planejado), 821 mil linhas de
  execução por favorecido, 1.574 autores.
- **Job diário** (`pipeline/atualizar.py`) roda checagem por `ETag` (~1 KB),
  baixa só o que mudou, ingere e resume o diff. Rodou de verdade: detectou a
  republicação da CGU de 29/08, ingeriu e gerou 67 mil mudanças.
- **Consulta por CEP** funcionando ponta a ponta (`pipeline/consulta.py`).
- `cruzamento.py` agora lê do banco, não dos ZIPs — relatório e plataforma
  usam a mesma verdade.
- systemd service + timer em `deploy/`.

## Decisões e aprendizados que NÃO estão óbvios no código

1. **CDN do TSE bloqueia CLI** (Akamai, fingerprint TLS). Só passa com
   `curl_cffi` + `impersonate="chrome"`. Tudo roda em **python3.13** (é onde
   `curl_cffi` está instalado). Download por faixas com resume; se voltar 403,
   esperar e retomar.
2. **A CGU republica quase todo dia** e o servidor responde `HEAD` com `ETag`
   e `Last-Modified` — por isso o job diário é barato. Já se pagou na
   primeira execução (arquivo local de 25/08 estava 2 MB defasado).
3. **Existe `Código do Autor da Emenda`** e ele é estável — é a ponte boa. O
   nome não é (89 dos 1.573 autores têm mais de uma grafia). O vínculo
   cod_autor → sq_candidato é persistido na tabela `autor`.
4. **O fallback por tokens produzia atribuição FALSA.** O piloto casava contra
   51 nomes de uma UF; com as 27 UFs + suplentes o universo virou 4.708 e
   `EDUARDO BRAGA` passou a casar com `CARLOS EDUARDO BRAGA MENEZES`. A trava
   que resolve: **primeiro e último nome têm que coincidir** (`nomes.py`,
   `_compativel`). Custou 14 vínculos (473 → 459 de 513) e eliminou os falsos.
   Todo vínculo por token entra na fila de `vincular.py` para olho humano.
5. **Reclassificação ≠ movimentação.** No feed diário, pares simétricos
   (+R$ X em Brasília, −R$ X em São Caetano) são o mesmo empenho reetiquetado
   na fonte. Ler como "transferiu a verba" seria acusação falsa. É a armadilha
   editorial mais perigosa que apareceu até agora.
6. **~99% da variação em valor não tem deputado identificado** (relator,
   bancada, comissão). O resumo separa isso em vez de esconder — é argumento
   da PEC, não defeito.
7. **Regra editorial inegociável**: nunca publicar inferência ("desviou") —
   só origem, destino, percentual e link para a fonte. Vale também para peça
   de campanha e anúncio.
8. **Estratégia**: transparência radical no lugar de anonimato (anonimato é
   vedado — CF art. 5º IV); zero disparo automatizado de WhatsApp (click-to-chat
   enviado pelo próprio cidadão); LGPD com opt-in explícito para CEP/contato.

## Tensões abertas entre o master plan e o que os dados sustentam

- "O seu bairro pagou X em impostos" — **não existe** com granularidade de CEP
  no Brasil. Precisa sair da jornada ou virar outra coisa.
- "a 500 km de distância" — depende da tabela `municipio` com coordenadas, que
  está criada e vazia. É o próximo destrave, e é barato.
- CEP → **seção eleitoral** não tem fonte pública limpa; hoje o CEP resolve
  só município. Prometer bairro sem `votacao_secao` seria inventar.
- Anúncio político pago na internet por terceiros é restrito (Lei 9.504/97
  art. 57-C). A "tática dos 5%" precisa de parecer antes do orçamento de mídia.

## Próximos passos (em ordem de destrave)

1. **Popular `municipio`** (lista IBGE + correspondência TSE + coordenadas) →
   a distância em km, que é o número da manchete.
2. **Percorrer a fila de `vincular.py`** (69 vínculos) — pré-requisito de
   qualquer publicação.
3. **Casar autoria por id da Câmara** (`dadosabertos.camara.leg.br`) ×
   `Código do Autor` × SQ_CANDIDATO — tira o nome do circuito de vez.
4. Granularidade por seção eleitoral (`votacao_secao_<ano>_<UF>.zip`) → CEP real.
5. API HTTP sobre `consulta.py`; a landing vira o shell da busca.

## Como retomar

```bash
cd ~/codigo-de-transicao
python3.13 pipeline/db.py --status        # o que há no banco
python3.13 pipeline/atualizar.py          # o ciclo diário
python3.13 pipeline/consulta.py --cep 49010-000
```
