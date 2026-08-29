# Brincando de Brasil — pipeline de dados

Laboratório cívico: propostas para o país fundamentadas em dados abertos
oficiais. A Ideia #01 é o cruzamento **origem do voto (TSE) × destino da
emenda (Portal da Transparência)** — a métrica central de "O Seu Dinheiro
Não Chegou no Seu Bairro".

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
  cruzamento.py          relatório por UF (lê do banco)
  api.py                 servidor HTTP: serve a landing e responde por CEP
  estatisticas.py        números nacionais para o dossiê (recalculáveis)
  gerar_dossie.py        gera o dossiê do voto distrital a partir dos dados
  conferir.py            invariantes do banco (roda no fim do job)
landing/index.html     o hub do site: manifesto, regras e as ideias
landing/dinheiro.html  Ideia #01 — a busca por CEP, consumindo a API
landing/propostas/     dossiês das PECs (voto distrital é gerado dos dados)
tests/                 testes; cada caso de nome é uma regressão real
deploy/                systemd service + timer do job diário
data/raw/              dumps oficiais (não versionados, ~800 MB)
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

Rotas: `/` (landing), `/propostas/voto-distrital.html`,
`/propostas/educacao.html`, `/api/consulta?cep=…`, `/api/saude`.

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

## Próximos passos

- [ ] Percorrer a fila de `vincular.py` (47 vínculos) antes de qualquer publicação
- [ ] Granularidade por seção eleitoral (`votacao_secao_<ano>_<UF>.zip`) → CEP real
- [ ] Coordenada da SEDE municipal (hoje é o centroide do território)
- [ ] Servidor de produção, limite de requisição e cache (`api.py` é de
      desenvolvimento: `http.server` da biblioteca padrão)
