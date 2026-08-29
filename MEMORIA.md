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
  execução por favorecido, 1.574 autores, 5.571 municípios com centroide,
  647 nomes parlamentares da Câmara.
- **Distância em km funcionando** (o número da manchete): a consulta devolve,
  por deputado, a distância média do dinheiro até o CEP, ponderada por valor.
- **500 dos 513 eleitos** com autoria de emenda identificada.
- 22 testes (`tests/`) e 13 invariantes (`conferir.py`), rodando no fim do job.
- **Menu + duas propostas.** A landing ganhou navegação fixa e, ao lado da
  manchete, um resumo das duas PECs: Voto Distrital Misto e Novo Pacto
  Educacional (este veio de um HTML do Gemini, em `landing/propostas/`).
- **O dossiê do voto distrital é GERADO dos dados** (`gerar_dossie.py` +
  `estatisticas.py`), não escrito à mão. Números nacionais novos e fortes:
  mediana de **360 km** entre o centro do voto e o destino do dinheiro;
  em **78%** dos deputados o maior destino de verba não é a maior base;
  mediana de **8 municípios** para somar metade da votação; **94,7%** do
  empenhado sem município e **59,1%** sem deputado identificável.
  As referências acadêmicas do dossiê **ainda precisam ser conferidas**.
- **A landing explica antes de mostrar**: três cartões (o que é emenda, que
  cargo é esse, para onde o dinheiro "deveria" ir) e uma ponte, depois do
  resultado, ligando o dado ao argumento da PEC. Jargão de orçamento traduzido,
  com teste que falha se voltar.
- **A landing consome a API e roda local**: `python3.13 pipeline/api.py` e
  abrir `http://127.0.0.1:8000`. Saiu de dados simulados para dados reais;
  o mapa de calor falso deu lugar a "de onde vieram os votos" × "para onde foi
  o dinheiro", ambos com a distância em km.
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
4. **A Câmara é a peça que faltava.** `dadosabertos.camara.leg.br` traz nome
   civil E nome parlamentar na mesma linha, e diz quem está em exercício.
   Isso liga os casos em que TSE e CGU divergem ('DEPUTADO DAL' × 'DAL
   BARRETO') e resolve homônimo eleito×suplente. Subiu de 459 para 500/513.
   Cuidado: a API devolve 100 itens por página para sempre, repetindo
   registros — paginar por `rel=next` e deduplicar por id, senão é laço
   infinito (e bloqueio por excesso de requisição). E ela discrimina por
   cliente igual ao TSE: `urllib` estoura, `curl_cffi` responde em 0,2 s.
5. **Uma chave, uma verdade.** As colunas de texto `UF`/`Município` da CGU
   discordam do `Código Município IBGE` em algumas linhas. Usar as duas juntas
   colocava a mesma linha em duas classes e as parcelas somavam mais que o
   total. Tudo que é município ou UF vem da tabela `municipio`, por código.
6. **`mudanca` guarda uma TRANSIÇÃO, não um fato.** Guardar só o snapshot de
   destino fez um `--forcar` apagar o histórico real (o diff do snapshot 3
   contra um banco que já É o snapshot 3 dá vazio). Agora grava o par
   (anterior → novo). Custou o histórico da transição 2→3, que não dá para
   recuperar: o arquivo do snapshot 2 foi sobrescrito.
7. **O fallback por tokens produzia atribuição FALSA.** O piloto casava contra
   51 nomes de uma UF; com as 27 UFs + suplentes o universo virou 4.708 e
   `EDUARDO BRAGA` passou a casar com `CARLOS EDUARDO BRAGA MENEZES`. A trava
   que resolve: **primeiro e último nome têm que coincidir** (`nomes.py`,
   `_compativel`). Custou 14 vínculos (473 → 459 de 513) e eliminou os falsos.
   Todo vínculo por token entra na fila de `vincular.py` para olho humano.
8. **Reclassificação ≠ movimentação.** No feed diário, pares simétricos
   (+R$ X em Brasília, −R$ X em São Caetano) são o mesmo empenho reetiquetado
   na fonte. Ler como "transferiu a verba" seria acusação falsa. É a armadilha
   editorial mais perigosa que apareceu até agora.
9. **~99% da variação em valor não tem deputado identificado** (relator,
   bancada, comissão). O resumo separa isso em vez de esconder — é argumento
   da PEC, não defeito.
10. **Regra editorial inegociável**: nunca publicar inferência ("desviou") —
   só origem, destino, percentual e link para a fonte. Vale também para peça
   de campanha e anúncio.
11. **Estratégia**: transparência radical no lugar de anonimato (anonimato é
   vedado — CF art. 5º IV); zero disparo automatizado de WhatsApp (click-to-chat
   enviado pelo próprio cidadão); LGPD com opt-in explícito para CEP/contato.

## Tensões abertas entre o master plan e o que os dados sustentam

- "O seu bairro pagou X em impostos" — **não existe** com granularidade de CEP
  no Brasil. Precisa sair da jornada ou virar outra coisa.
- "a 500 km de distância" — **resolvido**, com uma ressalva que precisa ir para
  o ar junto do número: a distância é entre CENTROIDES DE TERRITÓRIO (IBGE),
  não entre as sedes. Em município grande a diferença chega a dezenas de km.
- CEP → **seção eleitoral** não tem fonte pública limpa; hoje o CEP resolve
  só município. Prometer bairro sem `votacao_secao` seria inventar.
- Anúncio político pago na internet por terceiros é restrito (Lei 9.504/97
  art. 57-C). A "tática dos 5%" precisa de parecer antes do orçamento de mídia.

## Próximos passos (em ordem de destrave)

1. **Percorrer a fila de `vincular.py`** (47 vínculos) e os 13 eleitos sem
   autoria — pré-requisito de qualquer publicação.
2. Granularidade por seção eleitoral (`votacao_secao_<ano>_<UF>.zip`) → CEP real.
3. Coordenada da SEDE municipal (hoje é o centroide do território).
4. A API é de desenvolvimento (`http.server`): para expor publicamente, falta
   servidor de produção, limite de requisição e cache.

## Como retomar

```bash
cd ~/codigo-de-transicao
python3.13 pipeline/db.py --status        # o que há no banco
python3.13 pipeline/atualizar.py          # o ciclo diário
python3.13 pipeline/consulta.py --cep 49010-000
python3.13 pipeline/conferir.py           # 13 invariantes
python3.13 -m unittest discover -s tests  # 21 testes
```
