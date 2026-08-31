// Comparador entre governos — componente compartilhado.
//
// Mora aqui, e não dentro de cada página, porque ele aparece em DUAS: na home
// (versão compacta) e em /presidentes.html (versão completa). Duas cópias do
// mesmo gráfico divergem na primeira correção que alguém faz só de um lado —
// e num site cujo argumento é rastreabilidade, dois números diferentes para a
// mesma coisa em páginas diferentes é o pior defeito possível.
//
// Uso:
//   <script src="/governos.js" defer></script>
//   BB.governos.montar(document.getElementById('alvo'), { compacto: true });
(function () {
  'use strict';

  // Mesmo mecanismo do menu.js: o site pode viver sob um prefixo de caminho.
  var PREFIXO = (window.BB_PREFIXO || '').replace(/\/$/, '');

  // A ordem é editorial: começa pelo que a pessoa sente no bolso, no
  // supermercado, antes do que ela lê no jornal.
  // Os indicadores em temas. Viraram dezesseis, e dezesseis botões numa
  // fileira só é uma lista, não uma escolha: a pessoa varre tudo e não sabe
  // por onde começar. Em cinco temas ela escolhe primeiro o ASSUNTO — que é
  // como a pergunta nasce na cabeça dela ("e a saúde?") — e só depois o
  // indicador. De quebra, as três medidas de desemprego passam a aparecer
  // lado a lado, onde a diferença entre elas fica óbvia.
  var GRUPOS = [
    { id: 'economia', nome: 'Economia', series: ['ipca', 'pib'] },
    { id: 'trabalho', nome: 'Trabalho',
      series: ['desemprego', 'desemprego_pme', 'desemprego_pme_antiga'] },
    { id: 'renda', nome: 'Renda e pobreza',
      series: ['fome', 'pobreza', 'gini', 'gini_pnad_antiga'] },
    { id: 'saude', nome: 'Saúde',
      series: ['mortalidade_menores5', 'mortalidade_neonatal',
               'mortalidade_materna', 'esperanca_vida',
               'mortalidade_infantil', 'mortalidade_infantil_antiga'] },
    { id: 'educacao', nome: 'Educação', series: ['ideb_anos_iniciais'] }
  ];

  var ORDEM = GRUPOS.reduce(function (a, g) { return a.concat(g.series); }, []);

  // O ANO NO NOME DA ABA NÃO É ENFEITE.
  //
  // Três pesquisas diferentes já mediram desemprego no Brasil, e duas já
  // mediram desigualdade. Elas não se emendam: a "taxa de desemprego aberto"
  // dos anos 1990 dá 6% onde a medida de hoje daria o dobro, porque conta
  // gente diferente. Se as abas se chamassem só "Desemprego", alguém leria a
  // primeira e a última em sequência e concluiria que o desemprego dobrou —
  // conclusão falsa, tirada de dado verdadeiro. O período no nome é o que
  // impede isso, e é por isso que ele aparece antes mesmo de a pessoa clicar.
  var CURTO = {
    ipca: 'Inflação',
    pib: 'Crescimento (PIB)',
    desemprego: 'Desemprego (2012→)',
    desemprego_pme: 'Desemprego nas metrópoles (2003–15)',
    desemprego_pme_antiga: 'Desemprego nas metrópoles (1995–02)',
    fome: 'Fome',
    pobreza: 'Pobreza',
    gini: 'Desigualdade (2012→)',
    gini_pnad_antiga: 'Desigualdade (1995–2011)',
    mortalidade_menores5: 'Morte de crianças até 5 anos',
    mortalidade_neonatal: 'Morte de recém-nascidos',
    mortalidade_materna: 'Morte de mães no parto',
    esperanca_vida: 'Expectativa de vida (até 2018)',
    mortalidade_infantil: 'Mortalidade infantil (2000–2018)',
    mortalidade_infantil_antiga: 'Mortalidade infantil (1990–2009)',
    ideb_anos_iniciais: 'Ideb'
  };

  // Uma frase por indicador, em português de gente, para quem não sabe o que
  // é "IPCA" nem "quociente". Sem isso o gráfico é bonito e mudo.
  var EXPLICA = {
    ipca: 'Quanto os preços subiram, em média, a cada ano do mandato.',
    pib: 'Quanto a economia do país cresceu, em média, a cada ano.',
    desemprego: 'De cada 100 pessoas procurando trabalho, quantas não acharam.',
    fome: 'De cada 100 pessoas, quantas viviam em lares que passaram por falta real de comida (insegurança alimentar grave).',
    pobreza: 'De cada 100 pessoas, quantas viviam abaixo da linha de pobreza.',
    gini: 'Desigualdade de renda, de 0 a 1: quanto mais perto de 1, mais a renda do país está concentrada em poucos.',
    esperanca_vida: 'Quantos anos, em média, viveria quem nascesse naquele ano. Vem da projeção da população do IBGE — modelo, não contagem —, e por isso para em 2018, antes da covid.',
    desemprego_pme: 'De cada 100 pessoas procurando trabalho nas seis maiores regiões metropolitanas, quantas não acharam. Não é o país inteiro.',
    desemprego_pme_antiga: 'A medida antiga, mais estreita: de cada 100 pessoas que procuraram trabalho na semana da entrevista, nas seis maiores regiões metropolitanas, quantas não acharam.',
    gini_pnad_antiga: 'A mesma ideia de desigualdade, mas medida na pesquisa antiga e só entre quem tinha alguma renda — por isso o número é mais alto que o da linha de cima.',
    mortalidade_menores5: 'De cada mil crianças nascidas vivas, quantas morreram antes de completar 5 anos.',
    mortalidade_neonatal: 'De cada mil bebês nascidos vivos, quantos morreram nos primeiros 27 dias.',
    mortalidade_materna: 'De cada 100 mil crianças nascidas vivas, quantas mães morreram por causa da gravidez, do parto ou do pós-parto.',
    mortalidade_infantil_antiga: 'De cada mil bebês nascidos vivos, quantos morriam antes de completar 1 ano.',
    mortalidade_infantil: 'De cada mil bebês nascidos vivos, quantos morriam antes de completar 1 ano.',
    ideb_anos_iniciais: 'A nota das escolas municipais do 1º ao 5º ano (a cidade do meio do país).'
  };

  // Um indicador em que MENOS é melhor não pode ser pintado igual a um em que
  // mais é melhor — mas a página também não dá nota. A cor aqui serve só para
  // indicar a direção do indicador, e a legenda diz isso com todas as letras.
  var MENOS_E_MELHOR = { ipca: true, desemprego: true,
                         desemprego_pme: true, desemprego_pme_antiga: true,
                         fome: true, pobreza: true, gini: true,
                         gini_pnad_antiga: true,
                         mortalidade_menores5: true,
                         mortalidade_neonatal: true,
                         mortalidade_materna: true,
                         mortalidade_infantil: true,
                         mortalidade_infantil_antiga: true };

  var CSS = [
    '.bbg{--bbg-linha:#1E2935;--bbg-painel:#111820;--bbg-painel2:#0E141B;',
    '  --bbg-tinta:#E9EEF4;--bbg-dim:#93A1B0;--bbg-fraco:#5C6B7A;--bbg-volt:#F5D90A;',
    '  --bbg-azul:#5AB2FF;--bbg-alerta:#FF5C5C;',
    '  --bbg-mono:"IBM Plex Mono",ui-monospace,Menlo,monospace}',
    '.bbg-temas{display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.7rem;',
    '  padding-bottom:.7rem;border-bottom:1px solid var(--bbg-linha)}',
    '.bbg-temas button{background:transparent;border:0;border-bottom:2px solid transparent;',
    '  color:var(--bbg-fraco);font-family:var(--bbg-mono);font-size:.75rem;',
    '  letter-spacing:.08em;text-transform:uppercase;padding:.35rem .1rem;',
    '  margin-right:.9rem;cursor:pointer}',
    '.bbg-temas button[aria-selected="true"]{color:var(--bbg-volt);',
    '  border-bottom-color:var(--bbg-volt);font-weight:700}',
    '.bbg-temas button:hover:not([aria-selected="true"]){color:var(--bbg-tinta)}',
    '.bbg-abas{display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:1.1rem}',
    '.bbg-abas button{background:var(--bbg-painel);border:1px solid var(--bbg-linha);',
    '  color:var(--bbg-dim);font-family:var(--bbg-mono);font-size:.73rem;',
    '  letter-spacing:.05em;padding:.5rem .8rem;border-radius:3px;cursor:pointer;',
    '  transition:border-color .15s,color .15s}',
    '.bbg-abas button[aria-selected="true"]{background:var(--bbg-volt);color:#0B0F14;',
    '  border-color:var(--bbg-volt);font-weight:700}',
    '.bbg-abas button:hover:not([aria-selected="true"]){border-color:var(--bbg-volt);',
    '  color:var(--bbg-tinta)}',
    '.bbg-exp{font-size:.92rem;color:var(--bbg-dim);margin-bottom:.2rem}',
    '.bbg-obs{font-family:var(--bbg-mono);font-size:.7rem;color:var(--bbg-fraco);',
    '  margin-bottom:1.1rem;line-height:1.7}',
    '.bbg-obs a{color:var(--bbg-dim)}',
    '.bbg-lista{list-style:none;margin:0;padding:0}',
    '.bbg-lista li{display:grid;grid-template-columns:180px 1fr 118px;gap:.9rem;',
    '  align-items:center;padding:.42rem 0;border-top:1px solid var(--bbg-linha)}',
    '.bbg-lista li:first-child{border-top:0}',
    '@media (max-width:720px){.bbg-lista li{grid-template-columns:1fr auto;',
    '  gap:.25rem .8rem;padding:.7rem 0}',
    '  .bbg-trilho{grid-column:1/-1;order:3}}',
    '.bbg-quem{font-weight:700;font-size:.93rem;line-height:1.15;color:var(--bbg-tinta)}',
    '.bbg-quem i{display:block;font-style:normal;font-family:var(--bbg-mono);',
    '  font-size:.65rem;color:var(--bbg-fraco);margin-top:.15rem;letter-spacing:.03em}',
    '.bbg-trilho{height:20px;background:var(--bbg-painel2);',
    '  border:1px solid var(--bbg-linha);border-radius:3px;overflow:hidden}',
    '.bbg-trilho b{display:block;height:100%;background:var(--bbg-volt);width:0;',
    '  transition:width .45s cubic-bezier(.22,1,.36,1)}',
    '.bbg-trilho b.bbg-inv{background:var(--bbg-azul)}',
    '.bbg-trilho b.bbg-neg{background:var(--bbg-alerta)}',
    '.bbg-trilho.bbg-vazio{border-style:dashed;background:transparent}',
    '.bbg-val{font-family:var(--bbg-mono);font-size:1rem;text-align:right;',
    '  color:var(--bbg-tinta);white-space:nowrap}',
    '@media (max-width:720px){.bbg-val{text-align:right;font-size:1.05rem}}',
    '.bbg-val small{display:block;font-size:.63rem;color:var(--bbg-fraco);',
    '  letter-spacing:.04em;margin-top:.1rem}',
    '.bbg-val.bbg-sem{color:var(--bbg-fraco);font-size:.76rem}',
    '.bbg-legenda{margin-top:1rem;font-family:var(--bbg-mono);font-size:.68rem;',
    '  color:var(--bbg-fraco);line-height:1.8}',
    '.bbg-proc{font-family:var(--bbg-mono);font-size:.66rem;color:var(--bbg-fraco);',
    '  line-height:1.7;margin-top:.9rem;padding-top:.7rem;',
    '  border-top:1px dashed var(--bbg-linha)}',
    '.bbg-proc b{color:var(--bbg-dim);font-weight:600}',
    '.bbg-erro{color:var(--bbg-alerta);font-size:.92rem}'
  ].join('\n');

  var cssPosto = false;
  function porCss() {
    if (cssPosto) return;
    cssPosto = true;
    var e = document.createElement('style');
    e.textContent = CSS;
    (document.head || document.body).appendChild(e);
  }

  function esc(t) {
    var d = document.createElement('div');
    d.textContent = t == null ? '' : t;
    return d.innerHTML;
  }

  // Inflação de 963% e PIB de 4% não cabem na mesma régua de casas decimais.
  function casas(v) {
    var a = Math.abs(Number(v));
    return a >= 100 ? 0 : (a >= 10 ? 1 : 2);
  }
  function nfmt(v) {
    if (v == null) return '—';
    var c = casas(v);
    return Number(v).toLocaleString('pt-BR',
      { minimumFractionDigits: c, maximumFractionDigits: c });
  }
  function periodo(p) {
    return p.inicio.slice(0, 4) + '–' + (p.fim ? p.fim.slice(0, 4) : 'hoje');
  }

  function montar(alvo, opcoes) {
    opcoes = opcoes || {};
    porCss();
    alvo.className = (alvo.className || '') + ' bbg';
    alvo.innerHTML = '<p class="bbg-obs">carregando os dados do IBGE…</p>';

    fetch(PREFIXO + '/api/presidentes')
      .then(function (r) {
        return r.json().then(function (j) { return { ok: r.ok, corpo: j }; });
      })
      .then(function (r) {
        if (!r.ok) throw new Error(r.corpo.erro || 'erro');
        desenhar(alvo, r.corpo, opcoes);
      })
      .catch(function () {
        alvo.innerHTML = '<p class="bbg-erro">Não consegui carregar os dados '
          + 'agora. Se você está rodando local, suba a API com '
          + '<b>python3.13 pipeline/api.py</b>.</p>';
      });
  }

  // "2020-12-08T11:58:19" → "08/12/2020"
  function dataBR(t) {
    if (!t) return '';
    var m = String(t).match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? m[3] + '/' + m[2] + '/' + m[1] : '';
  }

  function desenhar(alvo, D, opcoes) {
    var disponiveis = ORDEM.filter(function (s) { return D.series[s]; });
    // Na home entram só os quatro que qualquer pessoa reconhece; a página
    // completa mostra todos.
    var lista = opcoes.compacto
      ? disponiveis.filter(function (s) {
          return ['ipca', 'pib', 'desemprego', 'ideb_anos_iniciais'].indexOf(s) >= 0;
        })
      : disponiveis;
    // Só entram os temas que sobraram com algum indicador — a versão compacta
    // e uma série que falte no banco não podem deixar uma aba de tema vazia.
    var temas = GRUPOS.map(function (g) {
      return { id: g.id, nome: g.nome,
               series: g.series.filter(function (s) { return lista.indexOf(s) >= 0; }) };
    }).filter(function (g) { return g.series.length; });

    var atual = lista[0];
    function temaDe(s) {
      for (var i = 0; i < temas.length; i++) {
        if (temas[i].series.indexOf(s) >= 0) return temas[i];
      }
      return temas[0];
    }

    var linhaTemas = document.createElement('div');
    linhaTemas.className = 'bbg-temas';
    linhaTemas.setAttribute('role', 'tablist');
    var abas = document.createElement('div');
    abas.className = 'bbg-abas';
    abas.setAttribute('role', 'tablist');
    var corpo = document.createElement('div');
    alvo.innerHTML = '';
    if (temas.length > 1) alvo.appendChild(linhaTemas);
    alvo.appendChild(abas);
    alvo.appendChild(corpo);

    function pinta() {
      var tema = temaDe(atual);
      linhaTemas.innerHTML = temas.map(function (g) {
        return '<button type="button" role="tab" data-g="' + g.id + '"'
          + ' aria-selected="' + (g.id === tema.id) + '">'
          + esc(g.nome) + '</button>';
      }).join('');

      abas.innerHTML = tema.series.map(function (s) {
        return '<button type="button" role="tab" data-s="' + s + '"'
          + ' aria-selected="' + (s === atual) + '">'
          + esc(CURTO[s] || D.series[s].nome) + '</button>';
      }).join('');

      var s = D.series[atual];
      var vals = D.presidentes.map(function (p) {
        var r = p.indicadores[atual];
        return r ? Number(r.valor) : null;
      }).filter(function (v) { return v != null; });
      var max = Math.max.apply(null, vals.map(Math.abs).concat([0])) || 1;
      var inv = !!MENOS_E_MELHOR[atual];

      var linhas = D.presidentes.map(function (p) {
        var r = p.indicadores[atual];
        var quem = '<div class="bbg-quem">' + esc(p.nome)
          + '<i>' + esc(p.partido) + ' · ' + periodo(p) + '</i></div>';
        if (!r) {
          return '<li>' + quem
            + '<div class="bbg-trilho bbg-vazio"></div>'
            + '<div class="bbg-val bbg-sem">sem dado<small>a série não '
            + 'alcança este período</small></div></li>';
        }
        var v = Number(r.valor);
        var larg = Math.abs(v) / max * 100;
        var rot = r.modo === 'inicio_fim'
          ? nfmt(r.de) + ' → ' + nfmt(r.para)
          : nfmt(v);
        var classe = v < 0 ? 'bbg-neg' : (inv ? 'bbg-inv' : '');
        return '<li>' + quem
          + '<div class="bbg-trilho"><b class="' + classe + '" style="width:'
          + larg.toFixed(1) + '%"></b></div>'
          + '<div class="bbg-val">' + rot + '<small>'
          + (r.completo ? esc(r.cobertura) : 'só ' + esc(r.cobertura))
          + '</small></div></li>';
      }).join('');

      corpo.innerHTML =
        '<p class="bbg-exp">' + esc(EXPLICA[atual] || '') + '</p>'
        + '<p class="bbg-obs">' + esc(s.observacao || '')
        + (s.url ? ' <a href="' + esc(s.url) + '" target="_blank" '
                 + 'rel="noopener">ver na fonte oficial →</a>' : '')
        + '</p>'
        + '<ul class="bbg-lista">' + linhas + '</ul>'
        + (s.fonte_oficial
            ? '<p class="bbg-proc"><b>Fonte, nas palavras do IBGE:</b> '
              + esc(s.fonte_oficial)
              + (s.atualizada_em
                  ? '<br><b>Tabela ' + esc(s.tabela_sidra || '')
                    + ' atualizada pelo IBGE em ' + esc(dataBR(s.atualizada_em))
                    + '.</b>'
                  : '')
              + '</p>'
            : '')
        + '<p class="bbg-legenda">Em ordem cronológica, nunca do maior para o '
        + 'menor: ordenar por valor criaria um ranking, e '
        + (inv ? 'neste indicador número menor é o desejável. '
               : 'neste indicador número maior é o desejável. ')
        + 'A barra mostra tamanho, não mérito — o que aconteceu no país durante '
        + 'o mandato não é a mesma coisa que o que o presidente causou.</p>';
    }

    abas.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('button');
      if (!b || !b.dataset.s) return;
      atual = b.dataset.s;
      pinta();
    });
    linhaTemas.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('button');
      if (!b || !b.dataset.g) return;
      for (var i = 0; i < temas.length; i++) {
        if (temas[i].id === b.dataset.g) { atual = temas[i].series[0]; break; }
      }
      pinta();
    });
    pinta();
  }

  window.BB = window.BB || {};
  window.BB.governos = { montar: montar, CURTO: CURTO, ORDEM: ORDEM };
})();
