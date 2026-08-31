# MEMÓRIA DO PROJETO — retomar daqui

> Contexto de continuidade para a próxima sessão de trabalho.
> Última atualização: 2026-08-30.

## O que este projeto é

"Brincando de Brasil" — hub cívico que ensina política com dado oficial,
consumível **por CEP**. Duas ferramentas no ar:

- **Ideia #01** (`landing/dinheiro.html`): origem do voto (TSE) × destino da
  emenda (CGU), com a distância em km.
- **Aula aberta** (`landing/como-funciona.html`): como o voto vira cadeira,
  com simulador interativo. É a porta de entrada nova do site.
- **Ideia #02** (`landing/escola.html`): o **Ideb do INEP** da cidade, aberto
  na conta que o produz, e **qual político responde por aquela escola**.

O eixo editorial mudou de "plataforma de pressão" para **"ensinar política de
um jeito fácil"**: o site é onde a pessoa vê o dado da vida dela e entende o
mecanismo. A proposta de reforma continua, mas como destino, não como porta.

## No ar

**https://studiocantare.com/brincandodebrasil/** (servidor "luisa",
`kakashi@89.167.115.24`, alias `sshluisa`). Repo público:
**github.com/ivanfcfilho/brincando-de-brasil**.

- Postgres 16 do servidor, banco/role `brincando`, senha gerada NO servidor e
  gravada em `~/brincandodebrasil/.env` (chmod 600, fora do git).
- Serviços: `brincandodebrasil` (site, porta 8010) e
  `brincandodebrasil-atualizar.timer` (job diário, 09:00 SP). Os dois
  `enabled`, sobem no boot.
- Convive com studiocantare.com (Django na 8000, ws na 8001) e
  `/inglescomagrazi/`. Backup do nginx foi movido para `/etc/nginx/backups/`:
  arquivo `.bak` dentro de `sites-enabled/` É CARREGADO pelo nginx e gera
  "conflicting server name".
- Os dados foram levados por `deploy/exportar_dados.py` +
  `importar_dados.py` (COPY em texto), não por `pg_dump` — dev roda PG18 e o
  servidor PG16, e o pg_dump se recusa a falar com servidor mais novo.

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
- 26 testes (`tests/`) e 19 invariantes (`conferir.py`), rodando no fim do job.
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
- **IDEIA #02 NO AR: Ideb por município (INEP).** 319.699 linhas, 3 etapas ×
  4 redes × 2005–2023, **5.570 dos 5.571 municípios** com nota medida e
  **zero órfãos** (todo código do INEP casa com a tabela `municipio`).
  `/escola.html` + `/api/educacao?cep=…` + `pipeline/educacao.py`.
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
11. **O INEP omite o intermediário do próprio certificado.** `download.inep.
   gov.br` manda só a folha; todo cliente honesto recusa (`unable to get local
   issuer certificate`). NÃO se resolveu com `verify=False` — num projeto de
   proveniência, canal não verificado torna "veio do INEP" uma afirmação sem
   prova. A folha publica o emissor na extensão **AIA**; esse intermediário é
   assinado pela **GlobalSign Root R46**, já confiável no sistema. `tls.py`
   só entrega ao verificador o elo que o servidor deveria ter mandado — a
   validação segue LIGADA e ancorada na raiz. O .pem fica **versionado em
   `certs/`**, não baixado em runtime (material de confiança buscado a cada
   job é porta de entrada). Vence em 2030-11-19; `tls.py --atualizar` rebusca.
   O servidor do INEP também derruba conexão sem padrão — a checagem tem retry.
12. **`ideb = nota × fluxo`, e essa é a notícia.** O índice divulgado é um
   número só e esconde a pergunta: `nota` é o Saeb (0–10) e `fluxo` é a taxa
   de aprovação (0–1). Confirmado no dado em **284.969 medições com 0
   divergências** — e virou invariante, porque a planilha tem 122 colunas com
   o ano no NOME da coluna: um desalinhamento de uma casa não levantaria
   exceção nenhuma, só produziria números plausíveis e errados. Aprovar sem
   ensinar sobe o Ideb, e agora dá para VER isso na cidade de quem lê — é a
   ponte empírica que faltava para o dossiê da educação.
13. **A rede de ensino é a aula de política.** 1º ao 9º ano = prefeitura;
   ensino médio = estado. Quase ninguém sabe, e cobrar o político errado é o
   mesmo que não cobrar. Foi o achado mais didático do projeto até agora, e
   custou zero cálculo — estava na coluna `REDE` o tempo todo.
14. **Cruzar emenda com Ideb NÃO se sustenta — e quase virou número.** Só 8,9%
   do empenhado na função Educação tem município no destino planejado, e a
   visão por favorecido não tem função orçamentária. O join por `codigo_emenda`
   (que não é único em `emenda`) **explodiu em produto cartesiano**: 100 mi de
   linhas, "R$ 42 trilhões". Se tivesse ido para a tela sem conferência de
   ordem de grandeza, era manchete falsa. Emenda também é fração mínima do
   gasto educacional perto do FUNDEB. A fonte certa é o SIOPE/FNDE.
15. **'SUPLENTE' no TSE ≠ 'não está na Câmara'.** A situação é a da APURAÇÃO
   de 2022; suplente assume se um titular sai. Orlando Silva (PC do B/SP) tem
   108.059 votos, situação SUPLENTE e `id_camara` preenchido — ele exerce
   mandato. Quase publiquei "não se elegeu" de um deputado em exercício. O
   `id_camara` virou o sinal de "assumiu depois" na tela, e a página só usa
   "não foi eleito na apuração de 2022". Conferido no arquivo bruto: zero
   candidatos com situação ambígua, então o dado está certo — a leitura é que
   era perigosa.
16. **Não dá para calcular o quociente eleitoral com a base atual.** Ele usa
   votos VÁLIDOS, que incluem voto de LEGENDA, e `votacao_candidato_munzona`
   só traz nominal. Um quociente sem legenda sai menor e com cara de oficial.
   Por isso o simulador da página usa eleição fictícia de números redondos, e
   o dado real só aparece onde é exato (quem teve mais voto e não entrou).
17. **Estratégia**: transparência radical no lugar de anonimato (anonimato é
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

0. **Gasto municipal em educação por aluno (SIOPE/FNDE)** — é o que torna o
   cruzamento dinheiro × resultado defensável. Hoje o site mostra o dinheiro
   (Ideia #01) e o resultado (Ideia #02) lado a lado, mas não os liga, porque
   a emenda parlamentar não sustenta a conta (ver aprendizado 14).
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
python3.13 pipeline/educacao.py --cep 49010-000
python3.13 pipeline/sistema.py --uf RS
python3.13 pipeline/conferir.py           # 17 invariantes
python3.13 -m unittest discover -s tests  # 25 testes
python3.13 pipeline/api.py                # e abrir /escola.html
```
