# Brincando de Brasil — pipeline de dados

Laboratório cívico: propostas para o país fundamentadas em dados abertos
oficiais. Duas ideias, duas perguntas que a pessoa pode fazer com o próprio
CEP:

- **Ideia #01 — para onde foi o dinheiro.** Cruzamento **origem do voto (TSE)
  × destino da emenda (Portal da Transparência)**, com a distância em km entre
  as duas coisas.
- **Aula aberta — como funciona a eleição** (`/como-funciona.html`). Os 7
  cargos, a diferença entre voto majoritário e proporcional, um **simulador
  interativo** da distribuição de cadeiras e, do dado real do TSE, os casos em
  que **mais voto não bastou**.
- **Ideia #02 — como está a escola daqui, e quem responde por ela.** O **Ideb
  do INEP** por município, aberto nas duas parcelas que o compõem, e a
  tradução da rede de ensino para a pergunta prática: *reclamo com quem?*

Para cada deputado federal, o pipeline responde:

> De onde vieram os votos (TSE, urna por urna, agregado por município) e para
> onde foram as emendas parlamentares do mandato (CGU)?

Os dados vivem num **Postgres** e são atualizados por um **job diário** que só
baixa o que mudou. O que se acumula não é o dado bruto repetido, é o **diff**:
"neste dia, este empenho subiu de A para B".

## Estrutura

```
db/schema.sql          proveniência + domínio + mudanças
pipeline/
  fontes.py              registro das fontes: como checar e como baixar
  db.py                  conexão, schema, snapshots, COPY em massa
  nomes.py               normalização e casamento de nomes
  atualizar.py           O JOB: checa, baixa o que mudou, ingere, resume
  ingest_tse.py          votação por município → banco (1× por eleição)
  ingest_emendas.py      emendas + execução → banco, com diff
  ingest_municipios.py   IBGE: ponte TSE↔IBGE + centroides (a distância em km)
  ingest_camara.py       registro da Câmara: id, nome civil e parlamentar
  vincular.py            autor de emenda ↔ deputado, com fila de revisão
  consulta.py            CEP → município → deputados → destino da verba
  educacao.py            CEP → município → Ideb da rede, e quem responde por ela
  sistema.py             o sistema eleitoral explicado com a eleição de 2022
  ingest_ideb.py         Ideb do INEP → banco, em formato longo
  xlsx.py                leitor de .xlsx em streaming, sem dependência nova
  tls.py                 completa a cadeia de certificados que o INEP não envia
  cruzamento.py          relatório por UF (lê do banco)
  api.py                 servidor HTTP: serve a landing e responde por CEP
  estatisticas.py        números nacionais para o dossiê (recalculáveis)
  gerar_dossie.py        gera o dossiê do voto distrital a partir dos dados
  conferir.py            invariantes do banco (roda no fim do job)
landing/index.html     o hub do site: manifesto, regras e as ideias
landing/dinheiro.html  Ideia #01 — a busca por CEP, consumindo a API
landing/escola.html    Ideia #02 — o Ideb da sua cidade, e quem responde por ele
landing/como-funciona.html  a aula: como o voto vira cadeira (com simulador)
landing/propostas/     dossiês das PECs (voto distrital é gerado dos dados)
tests/                 testes; cada caso de nome é uma regressão real
deploy/                systemd service + timer do job diário
data/raw/              dumps oficiais (não versionados, ~850 MB)
certs/                 o intermediário que o servidor do INEP omite (ver tls.py)
relatorio/             relatórios legíveis (Markdown)
```

## Instalação

```bash
pip install psycopg2-binary curl_cffi      # curl_cffi só para o TSE
cp .env.exemplo .env                       # e preencha o CT_DSN
python3.13 pipeline/db.py --init
```

O banco é **dedicado** (role e database próprios). Nada de senha no código: a
credencial vem de `CT_DSN`, no `.env`, que não vai para o git.

## Carga inicial

```bash
python3.13 pipeline/atualizar.py --fonte tse_munzona_2022   # baixa se faltar
python3.13 pipeline/ingest_tse.py --uf TODAS                # ~9 min
python3.13 pipeline/ingest_municipios.py                    # IBGE + centroides
python3.13 pipeline/ingest_camara.py                        # registro da Câmara
python3.13 pipeline/atualizar.py                            # emendas + diff
python3.13 pipeline/vincular.py                             # + fila de revisão
python3.13 pipeline/atualizar.py --fonte inep_ideb_anos_iniciais   # Ideb (3 fontes)
python3.13 pipeline/atualizar.py --fonte inep_ideb_anos_finais
python3.13 pipeline/atualizar.py --fonte inep_ideb_ensino_medio
python3.13 pipeline/conferir.py                             # invariantes
```

A ordem importa: `ingest_municipios` precisa do TSE já carregado (para casar os
códigos), e `ingest_emendas` precisa dos municípios (para resolver o código
IBGE do favorecido, de onde sai a distância).

## Ver funcionando

```bash
python3.13 pipeline/api.py          # http://127.0.0.1:8000
```

Abra `http://127.0.0.1:8000` e digite um CEP. A página explica primeiro o que é
uma emenda parlamentar e que cargo é esse, e só então mostra, para cada deputado
eleito com voto naquele município: de onde vieram os votos, para onde foi o
dinheiro, a distância em km entre as duas coisas, links para a fonte oficial de
cada emenda e o `sha256` do arquivo que gerou cada número.

**A página é didática e persuasiva, e o argumento é estrutural.** Ela diz, com
todas as letras, que ninguém listado quebrou regra alguma: o deputado é eleito
pelo estado inteiro, não deve o mandato a nenhuma cidade e por isso o dinheiro
não tem endereço. É desenho, não desvio — e é isso que o voto distrital misto
muda. Persuadir pelo mecanismo é o que a regra editorial permite; insinuar
desvio é o que ela proíbe, e o que derrubaria o projeto.

Termos de orçamento aparecem traduzidos: "empenhado" vira *reservado no
orçamento*, "execução" vira *já pago*, "múltiplo/sem informação" vira *sem
cidade informada*. Há um teste que falha se o jargão voltar à tela.

Rotas: `/` (landing), `/dinheiro.html`, `/escola.html`,
`/propostas/voto-distrital.html`, `/propostas/educacao.html`,
`/api/consulta?cep=…`, `/api/educacao?cep=…`, `/api/sistema?uf=…`,
`/api/saude`.

**A aula — como funciona a eleição.** `/como-funciona.html` é a porta de
entrada do site: quem não entende a regra do voto não entende o resto. Ela tem
os 7 cargos (com abas para eleição geral e municipal), a diferença entre
majoritário e proporcional, um **simulador** em que se arrastam votos entre
quatro partidos e as cadeiras mudam de mão ao vivo, e o dado real do estado
que o leitor escolher.

O fato que sustenta a página: **119 candidatos a deputado federal tiveram mais
votos que alguém eleito do próprio estado, em 2022, e não foram eleitos** —
invariante em `conferir.py`. No RS, Giovani Feltes (MDB) teve 91.887 votos e
ficou de fora; Franciane Bayer (Republicanos) entrou com 40.555. Não é fraude:
é o voto proporcional, em que a cadeira é do PARTIDO antes de ser do candidato.

Duas travas editoriais, ambas testadas:

- **'Suplente' não quer dizer 'não está na Câmara'.** A situação é a da
  apuração de 2022; suplente assume quando um titular sai (ministério,
  cassação, licença). Orlando Silva (PC do B/SP) teve 108.059 votos, ficou
  suplente na apuração **e exerce mandato hoje**. A página diz sempre "não foi
  eleito na apuração de 2022" e marca quem assumiu depois.
- **O quociente eleitoral não é calculado com os nossos dados.** O quociente
  oficial usa votos válidos, que incluem o **voto de legenda**, ausente da base
  `votacao_candidato_munzona`. Um quociente calculado sem a legenda daria um
  número menor com cara de oficial. Por isso a mecânica é ensinada por uma
  eleição fictícia de números redondos, e o dado real entra só onde é exato.

A conta do simulador implementa a regra brasileira de verdade (quociente
eleitoral → quociente partidário → sobras pelas **maiores médias**) e é testada
em `tests/test_como_funciona.cjs`, inclusive por um invariante aleatorizado:
as cadeiras distribuídas somam sempre as vagas, em 1.140 combinações.

**Ideia #02 — a escola da sua cidade.** `/escola.html` responde, para o
município do CEP e para cada etapa de ensino: o Ideb mais recente, a **conta
que o produz** (`nota do Saeb × taxa de aprovação`), a última meta com prazo e
se foi cumprida, a posição entre as cidades do estado e a série desde 2005.

O ângulo que organiza a página não é estatístico, é cívico: **a rede de ensino
diz qual político responde pela escola.** Do 1º ao 9º ano a escola costuma ser
da prefeitura; o ensino médio é quase todo do estado. Cobrar o político errado
é o mesmo que não cobrar, e essa informação não está em lugar nenhum onde o
cidadão olha.

A conta aparece aberta porque o Ideb divulgado é um número só, e um número só
esconde a pergunta. `ideb = nota × fluxo` — confirmado no próprio dado, em
**284.969 medições, com 0 divergências** (é invariante em `conferir.py`). Duas
cidades com o mesmo Ideb podem ter chegado lá por caminhos opostos: uma
ensinando mais, outra aprovando mais. É essa brecha que o dossiê da educação
propõe fechar, e agora ela é visível no dado de qualquer cidade.

**Os dossiês.** A landing tem um menu e, ao lado da manchete, um resumo das duas
PECs. O dossiê do voto distrital é **gerado dos dados**
(`python3.13 pipeline/gerar_dossie.py`): nenhum número empírico é digitado à
mão, e a página é regerada junto com o banco. Os números nacionais que ele
usa saem de `estatisticas.py` e podem ser recalculados por qualquer pessoa:

| Medida | Valor |
|---|---|
| Distância mediana entre o centro do voto e o destino do dinheiro | **360 km** |
| Deputados cujo maior destino de verba **não** é sua maior base de votos | **78%** |
| Municípios que somam metade da votação de um deputado (mediana) | **8** |
| Do empenhado que não informa município | **94,7%** (R$ 161,5 bi) |
| Do empenhado sem deputado individual identificável | **59,1%** (R$ 100,7 bi) |

As **referências acadêmicas** do dossiê ainda precisam ser conferidas contra os
originais antes de qualquer uso público — a regra de verificação dupla vale
também para nós, e a página diz isso na própria seção de procedência.

## Uso diário

```bash
python3.13 pipeline/atualizar.py            # o ciclo (checa → baixa → ingere → resume)
python3.13 pipeline/atualizar.py --dry-run  # só checa (custa ~1 KB)
python3.13 pipeline/atualizar.py --resumo 7 # o que mudou na semana
python3.13 pipeline/consulta.py --cep 49010-000
python3.13 pipeline/educacao.py --cep 49010-000   # o Ideb daquele município
python3.13 pipeline/sistema.py --uf RS             # como o voto virou cadeira lá
python3.13 pipeline/tls.py --conferir             # a cadeia do INEP fecha?
python3.13 pipeline/cruzamento.py --uf SE
python3.13 pipeline/conferir.py             # invariantes (sai != 0 se falhar)
python3.13 -m unittest discover -s tests    # testes (inclui a landing, via node)
```

`conferir.py` existe porque um bug real passou silencioso: o ZIP do TSE traz
agregados nacionais (`_BR.csv`, `_BRASIL.csv`) além das 27 UFs, e ler um deles
carimbou uma única UF em **91% das linhas de voto**. Nada quebrou — só as
consultas por estado passaram a devolver quase nada. Erro que não grita é o
perigoso, então as afirmações do projeto sobre os próprios dados (513
deputados, bancada de cada UF, UF do voto = UF do deputado) viraram teste que
roda em todo ciclo.

Agendamento:

```bash
sudo cp deploy/codigo-transicao-atualizar.{service,timer} /etc/systemd/system/
sudo systemctl enable --now codigo-transicao-atualizar.timer
```

A checagem é um `HEAD`: compara `ETag`/`Last-Modified`/tamanho com o último
snapshot e só baixa se mudou. A votação do TSE de 2022 é estática e por isso
tem periodicidade `eleicao` — o ciclo diário nem a consulta.

## Proveniência

Todo snapshot é identificado pelo **sha256 do arquivo oficial**, com data de
download e o `Last-Modified` declarado pelo servidor. Rebaixar um arquivo
idêntico não cria snapshot nem reingere nada. Toda checagem é registrada,
inclusive as que não acharam mudança — "olhamos e nada mudou" também é uma
afirmação que precisa de prova. Os relatórios trazem o sha256 dos snapshots
que geraram cada número.

## Fontes (oficiais, públicas, sem autenticação)

- **TSE — dados abertos**: `votacao_candidato_munzona_<ano>.zip`.
  O CDN (Akamai) bloqueia fingerprint TLS de linha de comando; o download usa
  `curl_cffi` com impersonation de Chrome e faixas com resume.
- **Portal da Transparência / CGU**: `EmendasParlamentares.zip` — três visões,
  das quais usamos o destino planejado e a execução por favorecido.
- **INEP/MEC — Ideb por município**: `divulgacao_<etapa>_municipios_2023.zip`,
  nas três etapas (anos iniciais, anos finais, ensino médio). O servidor
  apresenta **só o certificado folha** e omite o intermediário da RNP, o que
  faz todo cliente honesto recusar a conexão. A saída aqui **não** foi
  `verify=False`: o certificado folha publica o emissor na extensão AIA, esse
  intermediário é assinado pela GlobalSign Root R46 (já confiável no sistema),
  e `tls.py` só devolve ao verificador o elo que o servidor deveria ter
  mandado. A validação continua ligada e a confiança continua ancorada na
  raiz. O intermediário fica versionado em `certs/`, não é buscado em tempo de
  execução — material de confiança baixado a cada job é porta de entrada.
- **ViaCEP**: CEP → município, na consulta.

## Regras editoriais (inegociáveis)

1. **Nenhuma inferência.** O pipeline nunca escreve "desviou" ou "abandonou":
   publica origem dos votos, destino da verba e o percentual de divergência.
   Emenda destinada a outro município **é legal** — a conclusão é do leitor.
   Isso vale para o material de campanha também: uma peça que afirme o que os
   dados não mostram destrói o projeto inteiro, e a exposição por calúnia é
   pessoal, não da plataforma.
2. **Todo número rastreável à fonte.** Cada valor linka o documento oficial de
   origem, e cada relatório declara o sha256 do snapshot que o gerou.
3. **Verificação dupla antes de publicar.** Um número errado destrói a
   credibilidade de todos os certos. Daí a fila de `vincular.py`.

## Ressalvas metodológicas conhecidas

- **Casamento de autoria.** A base da CGU traz `Código do Autor da Emenda`,
  estável, mas 89 dos ~1.573 autores aparecem com mais de uma grafia de nome —
  e o TSE traz nome civil e de urna. O casamento é por nome exato, com
  fallback por tokens **travado por primeiro e último nome**: sem essa trava,
  `EDUARDO BRAGA` casa com `CARLOS EDUARDO BRAGA MENEZES` e `KATIA ABREU` com
  `CRISTIANE KATIA SIMONI ABREU` — pessoas diferentes. A trava rejeita casos
  genuinamente ambíguos (`JOSE SILVA` × `JOSE DA SILVA SANTOS`): match nenhum
  aparece no log, match errado aparece no relatório. Hoje **459 dos 513
  eleitos** têm autoria identificada, e todo vínculo por token entra na fila de
  revisão de `vincular.py`. Confirmar marca `conferido`, e nenhuma reingestão
  sobrescreve decisão humana.
  O registro da Câmara (`ingest_camara.py`) fecha o resto: ele traz nome civil
  e nome parlamentar na mesma linha, o que liga casos em que o TSE e a CGU
  divergem ('DEPUTADO DAL' × 'DAL BARRETO'), e distingue quem está em
  exercício, o que resolve homônimo entre eleito e suplente (eleito vence:
  quem apresenta emenda é quem exerce o mandato). Com isso, **500 dos 513**.
  Os 13 restantes estão listados por `vincular.py` e são, em boa parte,
  corretos: Marina Silva, Sônia Guajajara e Luiz Marinho assumiram ministérios
  sem exercer o mandato, e Deltan Dallagnol teve o mandato cassado — não têm
  emenda individual, e forçar um casamento aí seria inventar.
- **As APIs da Câmara e do TSE discriminam por cliente.** Ambas respondem em
  ~0,2 s a um navegador e estouram o tempo com `urllib`; as duas usam
  `curl_cffi` com impersonation. A da Câmara ainda devolve 100 itens por
  página indefinidamente, repetindo registros: a paginação segue o link
  `rel=next` e deduplica por id, com teto de páginas.
- **Uma chave, uma verdade.** As colunas de texto `UF` e `Município` da CGU
  discordam do `Código Município IBGE` em algumas linhas. Classificar usando
  as duas juntas colocava a mesma linha em duas classes, e as parcelas somavam
  mais que o total. UF e nome de município vêm sempre da tabela `municipio`,
  via código.
- **Distância é entre centroides de território, não entre sedes.** A tabela
  `municipio` casa os 5.570 municípios do TSE com o IBGE (grafia tolerante a
  apóstrofo e preposição, mais 22 apelidos por código para renomeações como
  Boa Saúde→Januário Cicco e Açu→Assú) e guarda o centroide calculado da malha
  oficial. Em município de área grande a diferença para a sede é de dezenas de
  km: Manaus tem centroide a ~50 km do centro da cidade. A distância publicada
  precisa dizer o que mede.
- **Link de emenda: o padrão `/emendas/{codigo}` do Portal devolve 404.** A
  página de detalhe só é alcançável por uma querystring que o próprio servidor
  monta. O que funciona é a consulta com o código no filtro
  (`/emendas/consulta?codigoEmenda=…`), verificada. E 17.810 das 94.463 emendas
  vêm com "Sem informação" no lugar do código: para essas não se gera link
  nenhum. Link morto numa página que promete rastreabilidade é pior que link
  ausente.
- **Um município sem coordenada**: Boa Esperança do Norte (MT) foi criado
  depois de 2022, não está na malha daquele ano e não tem código do TSE.
- **Empenhado ≠ pago.** O relatório usa valor empenhado (compromisso firmado);
  anos recentes têm pagamento em aberto por natureza.
- **Emendas de relator/comissão (RP8/RP9)** não têm autor individual. No
  primeiro diff medido, **~99% da variação em valor não era atribuível a
  nenhum deputado**. Essa opacidade é um argumento da PEC, não um defeito do
  pipeline — e por isso o resumo diário a separa em vez de escondê-la.
- **Destino planejado × execução.** No destino planejado, 70–95% dos empenhos
  vêm como "Múltiplo"/"Sem informação". A segunda visão (*PorFavorecido*)
  mostra quem recebeu, com a ressalva de que a **sede do favorecido não é o
  local de aplicação** — fundos estaduais e ministérios puxam valores para as
  capitais e para Brasília. As duas visões discordam, e a discordância é o
  achado.
- **R$ 378 milhões sem UF de favorecido** (4.975 linhas) aparecem numa classe
  própria, "sem local declarado", em vez de sumir da conta.
- **Armadilha do feed de mudanças: reclassificação não é movimentação.**
  Um par simétrico (`→ BRASILIA +R$ 5.119.961` e `→ SAO CAETANO DO SUL
  −R$ 5.119.961`) é o **mesmo empenho sendo reetiquetado** na fonte, não
  dinheiro trocando de lugar. Ler isso como "o deputado transferiu a verba"
  produziria uma acusação falsa. Nenhum item do feed vai ao ar sem essa
  checagem.
- **Licenças e suplências**: deputado licenciado pode ter emendas em nome do
  titular. Suplentes estão carregados (4.195), e são justamente onde o
  casamento por nome mais erra.

### Ressalvas do Ideb (Ideia #02)

- **As redes não somam.** `REDE` vale 'Municipal', 'Estadual', 'Federal' ou
  'Pública', e **'Pública' já é o agregado das outras três**. Somar todas conta
  o mesmo aluno mais de uma vez. Toda consulta escolhe uma: a página usa
  municipal nos anos iniciais e finais, estadual no ensino médio, que é onde
  está a quase totalidade das matrículas de cada etapa (5.433 municípios têm
  rede municipal medida nos anos iniciais, contra 3.482 com estadual; no
  ensino médio é 5.559 estadual contra 103 municipal).
- **Ausência não é zero.** Rede sem alunos suficientes não é divulgada e vem
  como `-`. Vira NULL, nunca 0 — um "Ideb zero" inventado entraria em toda
  média como medição real e puxaria o número nacional para baixo.
- **A meta acabou em 2021.** O INEP projetou metas até 2021 e não publicou
  projeção para 2023. Por isso a medição mais recente aparece sem meta, e a
  página mostra **separadamente** o último acerto de contas com uma meta real
  — que é a informação cobrável, porque meta é compromisso com prazo.
- **O ano mais recente varia por município.** A consulta usa a última medição
  COM valor, não 2023 fixo: rede pequena pode não ter sido divulgada no último
  ciclo, e fixar o ano devolveria vazio justamente para as cidades menores.
- **Ideb não mede esforço da prefeitura.** O que mais explica a nota de uma
  escola, em qualquer país, é a renda das famílias. A página publica valor,
  meta e comparação — e diz isso com todas as letras. Ler "Ideb baixo" como
  "o prefeito fez corpo mole" é exatamente a inferência que a regra editorial
  nº 1 proíbe.
- **A comparação usa mediana, não média.** A cidade do meio da fila é o que a
  frase "como estou perto dos vizinhos" quer dizer; uma cidade muito boa ou
  muito ruim entorta a média.
- **O que NÃO deu para fazer: cruzar emenda com Ideb.** A tentação óbvia era
  correlacionar dinheiro de emenda de educação com resultado. Não sai com
  honestidade: só **8,9%** do valor empenhado na função Educação (R$ 1,18 bi de
  R$ 13,27 bi) traz código de município no destino planejado, e a visão de
  execução por favorecido **não tem função orçamentária** — o join por
  `codigo_emenda` explode em produto cartesiano (o código não é único em
  `emenda`: a tentativa devolveu 100 milhões de linhas e "R$ 42 trilhões").
  Além disso, emenda é uma fração mínima do gasto educacional de um município
  perto do FUNDEB, então até uma correlação bem medida diria pouco. Fica como
  ressalva registrada, não como número publicado.

## Próximos passos

- [ ] Percorrer a fila de `vincular.py` (47 vínculos) antes de qualquer publicação
- [ ] Granularidade por seção eleitoral (`votacao_secao_<ano>_<UF>.zip`) → CEP real
- [ ] Coordenada da SEDE municipal (hoje é o centroide do território)
- [ ] Servidor de produção, limite de requisição e cache (`api.py` é de
      desenvolvimento: `http.server` da biblioteca padrão)
- [ ] Gasto municipal em educação por aluno (SIOPE/FNDE) — é a fonte que
      tornaria o cruzamento dinheiro × resultado defensável, no lugar da
      emenda parlamentar, que não sustenta a conta
- [ ] Ideb por ESCOLA (o INEP publica), para descer do município ao bairro
- [ ] Conferir a validade do intermediário em `certs/` no job (vence em
      2030-11-19; `python3.13 pipeline/tls.py --atualizar` rebusca pela AIA)
