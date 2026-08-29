#!/usr/bin/env python3
"""Gera o dossiê da PEC do Voto Distrital Misto a partir dos dados.

Nenhum número empírico é digitado à mão: todos vêm de estatisticas.py, que lê
o mesmo banco da busca por CEP. Rodar de novo depois de uma atualização
regenera a página com os números novos e o sha256 do snapshot que os produziu.

    python3.13 pipeline/gerar_dossie.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db as bd
from estatisticas import stats

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(RAIZ, "landing", "propostas", "_base.html")
SAIDA = os.path.join(RAIZ, "landing", "propostas", "voto-distrital.html")


def brl_bi(v):
    return f"R$ {float(v):.1f} bilhões".replace(".", ",")


def pc(v):
    """Percentual com vírgula decimal. O Decimal do Postgres vira '94.7' em
    Python, e ponto decimal em página brasileira lê como erro."""
    return f"{float(v):.1f}".replace(".", ",") + "%"


def corpo(s):
    d, c, disp = s["distancia"], s["coincidencia"], s["dispersao"]
    pct_sem_mun = pc(s["opacidade"]["pct_sem_municipio"])
    pct_sem_autor = pc(s["sem_autor"]["pct"])
    pct_nao_coincide = 100 - 100 * c["coincidem"] / c["com_os_dois"]
    fontes = "".join(
        f"<li><strong>{f['arquivo'].split('/')[-1]}</strong> — sha256 "
        f"<code>{f['sha256'][:24]}…</code>, baixado em "
        f"{f['baixado_em']:%d/%m/%Y}</li>" for f in s["fontes"])

    return f"""
<body>
  <div class="container" style="padding-top:3rem">
    <a href="/" style="color:var(--accent-gold);font-family:monospace;
       font-size:.8rem;text-decoration:none">&larr; Brincando de Brasil</a>
    &nbsp;&middot;&nbsp;
    <a href="/dinheiro.html" style="color:var(--accent-gold);font-family:monospace;
       font-size:.8rem;text-decoration:none">busca por CEP &rarr;</a>
    <div class="tag" style="margin-top:1.5rem">Dossiê Acadêmico e Legislativo</div>
    <h1 class="hero-title">O Mandato sem Endereço:<br>Fundamentação da PEC do
      Voto Distrital Misto</h1>
    <p class="hero-subtitle">
      Proposta de Emenda à Constituição alicerçada em teoria dos sistemas
      eleitorais, evidência comparada (Alemanha e Nova Zelândia) e na medição
      direta, município a município, do descolamento entre a origem do voto e o
      destino do orçamento no Brasil.
    </p>
  </div>

  <!-- ============ EVIDÊNCIA PRÓPRIA ============ -->
  <div class="container">
    <div class="section-header">
      <h2 class="section-title">A Evidência Brasileira</h2>
      <p class="section-desc">
        Os números abaixo não vêm da literatura: foram calculados dos arquivos
        oficiais do TSE e da CGU pelo código deste repositório, e podem ser
        recalculados por qualquer pessoa. É a parte da argumentação que não
        depende de acreditar em ninguém.
      </p>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-icon serif">{d['mediana_km']} km</div>
        <h3>É a mediana da distância entre o voto e a verba</h3>
        <p class="summary-text">
          Para cada um dos {d['deputados']} deputados federais eleitos em 2022,
          calculamos o centro de gravidade dos seus votos — a média das
          coordenadas dos municípios onde teve voto, ponderada pelos votos — e a
          distância média até onde o dinheiro das emendas dele efetivamente
          chegou, ponderada por valor.
        </p>
        <details>
          <summary>Expandir método e distribuição</summary>
          <div class="fold-content">
            <p class="academic-p">
              A média nacional é de <strong>{d['media_km']} km</strong>, e os 10%
              mais dispersos superam <strong>{d['p90_km']} km</strong>.
              <strong>{d['acima_500km']} deputados</strong> têm distância média
              acima de 500 km — mais que a distância entre São Paulo e o Rio de
              Janeiro, ida e volta.
            </p>
            <p class="academic-p">
              O cálculo usa apenas a execução financeira (dinheiro que de fato
              saiu e chegou ao favorecido), porque o destino declarado no empenho
              é opaco em {pct_sem_mun} dos casos — ver o
              pilar 03. As distâncias são medidas entre centroides de território
              (malha oficial do IBGE), não entre sedes municipais.
            </p>
            <div class="citation-box">
              <h5>Como reproduzir</h5>
              <ul><li><code>python3.13 pipeline/estatisticas.py</code></li></ul>
            </div>
          </div>
        </details>
      </div>

      <div class="card">
        <div class="card-icon serif">{pct_nao_coincide:.0f}%</div>
        <h3>Dos deputados mandam o grosso da verba para fora da sua maior base</h3>
        <p class="summary-text">
          Em apenas {c['coincidem']} de {c['com_os_dois']} casos o município que
          mais recebeu dinheiro é o mesmo que mais deu votos. Na esmagadora
          maioria, a maior base eleitoral e o maior destino do dinheiro são
          lugares diferentes.
        </p>
        <details>
          <summary>Expandir leitura</summary>
          <div class="fold-content">
            <p class="academic-p">
              Isto <strong>não é indício de irregularidade</strong>. Nada obriga
              a emenda a voltar para a base — mandar tudo para outro estado é
              legal. O número mede exatamente a ausência dessa obrigação: quando
              não há vínculo territorial no mandato, não há razão sistêmica para
              que o dinheiro siga o voto.
            </p>
            <p class="academic-p">
              Boa parte da diferença tem explicação prosaica: fundos estaduais,
              consórcios e fornecedores têm sede em capitais, o que puxa o
              registro do favorecido para lá. Essa ressalva vale para o número e
              está declarada em toda consulta da plataforma.
            </p>
          </div>
        </details>
      </div>

      <div class="card">
        <div class="card-icon serif">{disp['mediana']}</div>
        <h3>Municípios bastam para somar metade da votação de um deputado</h3>
        <p class="summary-text">
          Mediana de {disp['mediana']} municípios (máximo observado:
          {disp['maximo']}). O voto brasileiro é geograficamente concentrado —
          o que derruba o argumento de que distritalizar seria artificial.
        </p>
        <details>
          <summary>Expandir implicação</summary>
          <div class="fold-content">
            <p class="academic-p">
              A defesa mais comum do sistema atual é que a representação já seria
              territorial "na prática", tornando o distrito desnecessário. O dado
              mostra o contrário do que essa defesa supõe: os deputados
              <em>já</em> têm base territorial concentrada, mas essa base não tem
              existência jurídica. Ela é um fato eleitoral sem contrapartida
              institucional — o eleitor não pode cobrá-la, porque formalmente ela
              não existe.
            </p>
            <p class="academic-p">
              O distrito não cria um vínculo territorial onde não havia. Ele
              torna <strong>exigível</strong> um vínculo que já existe de fato.
            </p>
          </div>
        </details>
      </div>

      <div class="card">
        <div class="card-icon serif">{pct_sem_autor}</div>
        <h3>Do orçamento de emendas não tem deputado a quem cobrar</h3>
        <p class="summary-text">
          {brl_bi(s['sem_autor']['bilhoes'])} empenhados desde 2023 vêm de
          relator, bancada ou comissão — instrumentos sem autor individual. Não
          há nome a quem atribuir, logo não há nome a quem responsabilizar.
        </p>
        <details>
          <summary>Expandir</summary>
          <div class="fold-content">
            <p class="academic-p">
              A plataforma não consegue mostrar esse dinheiro em nenhuma busca por
              CEP — não porque falhe, mas porque a informação de autoria não
              existe na fonte. A opacidade é um achado, não um defeito da
              medição: é a maior fatia do orçamento de emendas e a que menos
              admite cobrança eleitoral.
            </p>
          </div>
        </details>
      </div>
    </div>
  </div>

  <!-- ============ PILARES ============ -->
  <div class="container">
    <div class="section-header">
      <h2 class="section-title">Os 4 Pilares da Proposta</h2>
      <p class="section-desc">
        A engrenagem que produz o número acima, e a alteração de arquitetura que
        a desmonta.
      </p>
    </div>

    <div class="grid-2">
      <div class="card">
        <div class="card-icon serif">01.</div>
        <h3>O Voto sem Endereço</h3>
        <p class="summary-text">
          O deputado federal é eleito pelo estado inteiro em lista aberta com
          magnitude altíssima (até 70 cadeiras em SP). Ele não deve o mandato a
          nenhum lugar — e, portanto, não deve satisfação a nenhum.
        </p>
        <details>
          <summary>Expandir Embasamento Científico</summary>
          <div class="fold-content">
            <p class="academic-p">
              Carey e Shugart demonstram que os incentivos ao <strong>voto
              pessoal</strong> variam sistematicamente com o desenho da regra
              eleitoral, e que a combinação lista aberta + alta magnitude de
              distrito produz o caso extremo: o candidato compete não apenas
              contra outros partidos, mas contra os próprios companheiros de
              legenda, por votos espalhados por um território inteiro.
            </p>
            <p class="academic-p">
              A consequência prevista pela teoria — e observada por Ames no caso
              brasileiro — é a busca por recursos particularizáveis, distribuídos
              onde forem eleitoralmente mais rentáveis a cada ciclo, e não onde
              haja compromisso permanente. A verba segue a conveniência porque a
              regra não dá ao território poder de cobrança.
            </p>
            <div class="citation-box">
              <h5>Referências Chave</h5>
              <ul>
                <li><strong>Carey, J. M., &amp; Shugart, M. S. (1995).</strong>
                  <em>Incentives to cultivate a personal vote: A rank ordering of
                  electoral formulas.</em> Electoral Studies, 14(4).</li>
                <li><strong>Ames, B. (2001).</strong> <em>The Deadlock of
                  Democracy in Brazil.</em> University of Michigan Press.</li>
                <li><strong>Nicolau, J. (2017).</strong> <em>Representantes de
                  quem? Os (des)caminhos do seu voto da urna à Câmara dos
                  Deputados.</em> Zahar.</li>
              </ul>
            </div>
          </div>
        </details>
      </div>

      <div class="card">
        <div class="card-icon serif">02.</div>
        <h3>O Distrito com Nome</h3>
        <p class="summary-text">
          Metade da Câmara passa a ser eleita em distritos uninominais; a outra
          metade por lista partidária, preservando a proporcionalidade do
          resultado. É o modelo alemão, em vigor desde 1949.
        </p>
        <details>
          <summary>Expandir Embasamento Científico</summary>
          <div class="fold-content">
            <p class="academic-p">
              O sistema misto de membro proporcional (MMP) resolve o falso dilema
              entre representatividade e responsabilização: o voto de lista
              determina a proporção final de cadeiras de cada partido, enquanto o
              voto distrital determina <em>quem</em> ocupa parte delas. Não se
              troca proporcionalidade por território — obtêm-se os dois.
            </p>
            <p class="academic-p">
              <strong>Prova histórica:</strong> a Nova Zelândia migrou de maioria
              simples para MMP após a Comissão Real de 1986 e dois referendos
              (1992 e 1993), com a primeira eleição sob o novo sistema em 1996 —
              caso raro de mudança de sistema eleitoral decidida em consulta
              popular, e o exemplo mais próximo do que esta PEC propõe fazer.
            </p>
            <div class="citation-box">
              <h5>Referências Chave</h5>
              <ul>
                <li><strong>Shugart, M. S., &amp; Wattenberg, M. P. (orgs., 2001).</strong>
                  <em>Mixed-Member Electoral Systems: The Best of Both Worlds?</em>
                  Oxford University Press.</li>
                <li><strong>Royal Commission on the Electoral System (1986).</strong>
                  <em>Towards a Better Democracy.</em> Wellington, Nova Zelândia.</li>
                <li><strong>Lijphart, A. (1999).</strong> <em>Patterns of
                  Democracy.</em> Yale University Press.</li>
              </ul>
            </div>
          </div>
        </details>
      </div>

      <div class="card">
        <div class="card-icon serif">03.</div>
        <h3>Fim da Emenda Impositiva</h3>
        <p class="summary-text">
          Hoje, {pct_sem_mun} do valor empenhado
          ({brl_bi(s['opacidade']['bilhoes_sem_municipio'])} desde 2023) não
          informa sequer o município de destino. Obrigatoriedade de pagar sem
          obrigatoriedade de dizer para onde.
        </p>
        <details>
          <summary>Expandir Embasamento</summary>
          <div class="fold-content">
            <p class="academic-p">
              O regime impositivo retirou do Executivo a discricionariedade sobre
              o pagamento, mas não criou, em contrapartida, exigência
              proporcional de rastreabilidade. O resultado é medível e está acima:
              a maior parte do dinheiro é obrigatória para quem paga e opaca para
              quem financia.
            </p>
            <p class="academic-p">
              Este número é o mais fácil de verificar de toda a proposta — basta
              abrir a base da CGU. E é o que menos depende de concordar com a
              tese: seja qual for a opinião sobre emendas, um orçamento em que
              nove de cada dez reais não declaram destino não é auditável.
            </p>
            <div class="citation-box">
              <h5>Fonte primária</h5>
              <ul>
                <li><strong>CGU / Portal da Transparência</strong> —
                  <em>Emendas Parlamentares</em>, base completa, campo
                  "Localidade de aplicação do recurso".</li>
                <li><strong>Constituição Federal</strong>, art. 166 e parágrafos
                  (regime das emendas individuais e de bancada).</li>
              </ul>
            </div>
          </div>
        </details>
      </div>

      <div class="card">
        <div class="card-icon serif">04.</div>
        <h3>Cláusula de Barreira Rígida</h3>
        <p class="summary-text">
          Sem barreira, o componente de lista reproduz a fragmentação atual e o
          pedágio de coalizão que trava qualquer pauta — de qualquer campo
          ideológico.
        </p>
        <details>
          <summary>Expandir Embasamento Científico</summary>
          <div class="fold-content">
            <p class="academic-p">
              A literatura sobre sistemas partidários associa fragmentação
              elevada a custos de coordenação que deslocam a disputa do conteúdo
              para o preço do apoio. O patamar alemão de 5% é o parâmetro
              consolidado: alto o bastante para eliminar legendas de aluguel,
              baixo o bastante para não fechar o sistema.
            </p>
            <p class="academic-p">
              É o pilar que torna a proposta legível para os dois campos: nenhuma
              agenda, à esquerda ou à direita, é aprovada hoje sem pagar pedágio
              a quem não disputa conteúdo nenhum.
            </p>
            <div class="citation-box">
              <h5>Referências Chave</h5>
              <ul>
                <li><strong>Duverger, M. (1954).</strong> <em>Political
                  Parties.</em> Wiley.</li>
                <li><strong>Mainwaring, S. (1999).</strong> <em>Rethinking Party
                  Systems in the Third Wave of Democratization: The Case of
                  Brazil.</em> Stanford University Press.</li>
                <li><strong>Bundeswahlgesetz</strong> (Lei Eleitoral Federal
                  alemã) — cláusula de 5%.</li>
              </ul>
            </div>
          </div>
        </details>
      </div>
    </div>
  </div>

  <!-- ============ VULNERABILIDADES ============ -->
  <div class="container">
    <div class="section-header">
      <h2 class="section-title">Auditoria e Correções (Patches)</h2>
      <p class="section-desc">
        Onde este modelo pode falhar, dito por quem o propõe. Uma proposta que
        não lista as próprias vulnerabilidades está escondendo alguma.
      </p>
    </div>

    <div class="patch-card">
      <div class="patch-problem">
        <h4>Vulnerabilidade A: Desenho dos Distritos (gerrymandering)</h4>
        <p>Quem traça o mapa escolhe o vencedor. Se a definição dos distritos
        ficar com o próprio Congresso, a reforma entrega uma ferramenta de
        perpetuação mais eficiente que a atual.</p>
      </div>
      <div class="patch-solution">
        <h4>Correção: delimitação técnica e vinculada</h4>
        <p>Traçado por órgão técnico independente, com critérios objetivos
        fixados na própria Emenda — contiguidade territorial, desvio populacional
        máximo declarado, respeito a limites municipais — e revisão automática a
        cada censo, sem juízo político sobre o mapa.</p>
        <details>
          <summary>Expandir</summary>
          <div class="fold-content">
            <p class="academic-p">
              A experiência comparada mostra que a diferença entre um MMP saudável
              e um MMP capturado está menos na fórmula e mais em quem desenha o
              mapa. Deixar o critério na lei ordinária seria transferir para a
              maioria de plantão exatamente o poder que a reforma quer limitar.
            </p>
          </div>
        </details>
      </div>
    </div>

    <div class="patch-card">
      <div class="patch-problem">
        <h4>Vulnerabilidade B: Paroquialismo</h4>
        <p>Um deputado distrital pode se comportar como vereador federal:
        otimizar para a obra visível no seu distrito e desertar de temas
        nacionais que não rendem voto local.</p>
      </div>
      <div class="patch-solution">
        <h4>Correção: a metade de lista é o contrapeso</h4>
        <p>É exatamente por isso que a proposta é <em>mista</em>. Metade da
        Câmara continua eleita por lista, sem distrito a atender, com incentivo
        preservado para pautas nacionais e temáticas.</p>
        <details>
          <summary>Expandir</summary>
          <div class="fold-content">
            <p class="academic-p">
              O sistema puramente distrital (maioria simples) é o que produz
              paroquialismo sem contrapeso, e não é o que se propõe aqui. A
              crítica é legítima contra o modelo britânico; contra o modelo
              alemão, ela descreve metade do desenho e ignora a outra.
            </p>
          </div>
        </details>
      </div>
    </div>

    <div class="patch-card">
      <div class="patch-problem">
        <h4>Vulnerabilidade C: Minorias geograficamente dispersas</h4>
        <p>Grupos cuja identidade não é territorial — e que hoje elegem
        representantes somando votos espalhados pelo estado — podem perder
        representação se o distrito virar a via principal.</p>
      </div>
      <div class="patch-solution">
        <h4>Correção: a proporcionalidade final é a da lista</h4>
        <p>No MMP, o total de cadeiras de cada partido é determinado pelo voto de
        lista, não pela soma dos distritos vencidos. Candidaturas de base difusa
        continuam viáveis pela lista, com a proporcionalidade nacional preservada
        — que é precisamente o que distingue o modelo alemão do britânico.</p>
      </div>
    </div>
  </div>

  <!-- ============ PROCEDÊNCIA ============ -->
  <div class="container" style="padding-bottom:4rem">
    <div class="section-header">
      <h2 class="section-title">Procedência dos Números</h2>
      <p class="section-desc">
        Toda estatística da seção "A Evidência Brasileira" foi gerada por
        <code>pipeline/estatisticas.py</code> a partir dos arquivos abaixo. A
        página é regenerada junto com os dados; não há número digitado à mão.
      </p>
    </div>
    <div class="citation-box">
      <h5>Snapshots utilizados</h5>
      <ul>{fontes}</ul>
    </div>
    <div class="citation-box" style="margin-top:1rem">
      <h5>Nota de verificação</h5>
      <ul>
        <li>As estatísticas brasileiras são recalculáveis com o repositório e não
          dependem de confiança em terceiros.</li>
        <li>As <strong>referências acadêmicas</strong> desta página foram
          reunidas para fundamentação e <strong>devem ser conferidas contra os
          originais</strong> antes de qualquer uso público — é a regra de
          verificação dupla do projeto, e ela vale também para nós.</li>
      </ul>
    </div>
  </div>
</body>
</html>
"""


def main():
    s = stats(bd.conectar())
    base = open(BASE, encoding="utf-8").read()
    base = base.replace("{{TITULO}}",
                        "PEC do Voto Distrital Misto | Dossiê Acadêmico")
    open(SAIDA, "w", encoding="utf-8").write(base + corpo(s))
    print(f"ok: {SAIDA} ({os.path.getsize(SAIDA)/1024:.0f} KB)")
    print(f"    mediana {s['distancia']['mediana_km']} km · "
          f"{pc(s['opacidade']['pct_sem_municipio'])} sem município · "
          f"{pc(s['sem_autor']['pct'])} sem autor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
