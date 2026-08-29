// Navegação padronizada do Brincando de Brasil.
//
// Uma página entra no site com UMA linha:
//     <script src="/menu.js" defer></script>
// e ganha a mesma barra superior e o mesmo menu lateral colapsável de todas
// as outras — mesma ordem, mesmas cores, mesmo comportamento. É a única
// fonte da navegação: link novo se adiciona aqui, nunca página a página.
(function () {
  'use strict';

  // O mapa do site. Duas prateleiras, de propósito: a versão simples
  // (qualquer pessoa que sabe ler) e a versão científica (quem quer fontes,
  // estudos e detalhe técnico).
  var SIMPLES = [
    ['/', 'Início'],
    ['/dinheiro.html', 'Ideia #01 · Seu dinheiro'],
    ['/propostas/educacao.html', 'Ideia #02 · Educação'],
  ];
  var CIENTIFICO = [
    ['/propostas/voto-distrital.html', 'Dossiê do voto distrital'],
    ['/propostas/educacao.html', 'Dossiê da educação'],
  ];
  var SECOES = {
    '/': [
      ['#comoassim', 'Como assim, "brincando"?'],
      ['#ideias', 'As ideias'],
      ['#regras', 'As regras'],
      ['#placar', 'O placar'],
    ],
    '/dinheiro.html': [
      ['#buscar', 'Digitar o CEP'],
      ['#entenda', 'Entenda em 3 passos'],
      ['#metodo', 'Como a gente calcula'],
      ['#propostas', 'As propostas'],
      ['#doutrina', 'Nossas regras'],
    ],
    '/propostas/educacao.html': [
      ['#logica', 'A arquitetura lógica'],
      ['#pilares', 'Os 4 pilares'],
      ['#antifragilidade', 'Vulnerabilidades e correções'],
      ['#reforma-ideb', 'O Ideb ajustado'],
    ],
  };

  var aqui = location.pathname === '/index.html' ? '/' : location.pathname;

  var css = [
    '.bb-topo{position:sticky;top:0;z-index:900;display:flex;align-items:center;gap:1rem;',
    '  padding:.6rem 1rem;background:rgba(11,15,20,.96);backdrop-filter:blur(8px);',
    '  border-bottom:1px solid #1E2935;font-family:Archivo,"Helvetica Neue",Arial,sans-serif}',
    '.bb-topo .bb-abrir{display:flex;flex-direction:column;justify-content:center;gap:4px;',
    '  width:40px;height:36px;padding:0 9px;background:none;border:1px solid #1E2935;',
    '  border-radius:3px;cursor:pointer}',
    '.bb-topo .bb-abrir span{display:block;height:2px;background:#F5D90A;border-radius:1px}',
    '.bb-topo .bb-abrir:hover,.bb-topo .bb-abrir:focus-visible{border-color:#F5D90A}',
    '.bb-topo .bb-marca{font-weight:900;font-size:.95rem;letter-spacing:-.01em;',
    '  color:#E9EEF4;text-decoration:none;margin-right:auto}',
    '.bb-topo .bb-marca b{color:#F5D90A}',
    '.bb-topo .bb-cta{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-size:.72rem;',
    '  letter-spacing:.06em;text-transform:uppercase;text-decoration:none;font-weight:700;',
    '  color:#0B0F14;background:#F5D90A;border-radius:3px;padding:.42rem .75rem}',
    '.bb-topo .bb-cta:hover{background:#ffe83d}',
    '.bb-veu{position:fixed;inset:0;z-index:950;background:rgba(0,0,0,.55);opacity:0;',
    '  pointer-events:none;transition:opacity .18s}',
    '.bb-aberto .bb-veu{opacity:1;pointer-events:auto}',
    '.bb-menu{position:fixed;top:0;left:0;bottom:0;z-index:1000;width:min(310px,86vw);',
    '  background:#0E141B;border-right:1px solid #1E2935;padding:1.1rem 1.2rem 2rem;',
    '  overflow-y:auto;transform:translateX(-102%);transition:transform .18s ease-out;',
    '  font-family:Archivo,"Helvetica Neue",Arial,sans-serif}',
    '.bb-aberto .bb-menu{transform:none}',
    '@media (prefers-reduced-motion:reduce){.bb-menu,.bb-veu{transition:none}}',
    '.bb-menu .bb-cab{display:flex;align-items:center;justify-content:space-between;',
    '  margin-bottom:1.3rem}',
    '.bb-menu .bb-marca{font-weight:900;font-size:1rem;color:#E9EEF4;text-decoration:none}',
    '.bb-menu .bb-marca b{color:#F5D90A}',
    '.bb-menu .bb-fechar{background:none;border:1px solid #1E2935;border-radius:3px;',
    '  color:#93A1B0;font-size:1rem;line-height:1;width:32px;height:32px;cursor:pointer}',
    '.bb-menu .bb-fechar:hover,.bb-menu .bb-fechar:focus-visible{color:#F5D90A;border-color:#F5D90A}',
    '.bb-menu h2{font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-size:.64rem;',
    '  letter-spacing:.16em;text-transform:uppercase;color:#5C6B7A;margin:1.4rem 0 .5rem;',
    '  font-weight:500}',
    '.bb-menu a.bb-item{display:block;padding:.5rem .6rem;margin:0 -.6rem;border-radius:3px;',
    '  color:#E9EEF4;text-decoration:none;font-size:.92rem;line-height:1.35}',
    '.bb-menu a.bb-item:hover,.bb-menu a.bb-item:focus-visible{background:#111820;color:#F5D90A}',
    '.bb-menu a.bb-atual{color:#F5D90A;background:#111820}',
    '.bb-menu a.bb-sec{display:block;padding:.34rem .6rem .34rem 1.1rem;margin:0 -.6rem;',
    '  color:#93A1B0;text-decoration:none;font-size:.84rem;border-left:2px solid #1E2935}',
    '.bb-menu a.bb-sec:hover,.bb-menu a.bb-sec:focus-visible{color:#F5D90A;border-left-color:#F5D90A}',
    '.bb-menu .bb-cta{display:block;margin-top:1.6rem;text-align:center;',
    '  font-family:"IBM Plex Mono",ui-monospace,Menlo,monospace;font-size:.74rem;',
    '  letter-spacing:.06em;text-transform:uppercase;text-decoration:none;font-weight:700;',
    '  color:#0B0F14;background:#F5D90A;border-radius:3px;padding:.65rem .8rem}',
    '.bb-menu .bb-cta:hover{background:#ffe83d}',
    '.bb-menu .bb-nota{margin-top:1.2rem;font-size:.72rem;color:#5C6B7A;line-height:1.6}',
  ].join('\n');

  function esc(t) {
    return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function lista(pares, classe) {
    return pares.map(function (p) {
      var atual = classe === 'bb-item' && p[0] === aqui;
      return '<a class="' + classe + (atual ? ' bb-atual' : '') + '" href="' + p[0] + '"' +
        (atual ? ' aria-current="page"' : '') + '>' + esc(p[1]) + '</a>';
    }).join('');
  }

  var estilo = document.createElement('style');
  estilo.textContent = css;
  document.head ? document.head.appendChild(estilo) : document.body.appendChild(estilo);

  var secoes = SECOES[aqui] || [];
  var html =
    '<header class="bb-topo">' +
    '<button class="bb-abrir" aria-label="Abrir o menu" aria-expanded="false" aria-controls="bb-menu">' +
    '<span></span><span></span><span></span></button>' +
    '<a class="bb-marca" href="/">Brincando de <b>Brasil</b></a>' +
    '<a class="bb-cta" href="/dinheiro.html#buscar">Buscar por CEP</a>' +
    '</header>' +
    '<div class="bb-veu" hidden></div>' +
    '<aside class="bb-menu" id="bb-menu" aria-label="Menu do site" hidden>' +
    '<div class="bb-cab">' +
    '<a class="bb-marca" href="/">Brincando de <b>Brasil</b></a>' +
    '<button class="bb-fechar" aria-label="Fechar o menu">✕</button>' +
    '</div>' +
    '<h2>Versão simples</h2>' + lista(SIMPLES, 'bb-item') +
    (secoes.length ? '<h2>Nesta página</h2>' + lista(secoes, 'bb-sec') : '') +
    '<h2>Para quem quer ir fundo</h2>' + lista(CIENTIFICO, 'bb-item') +
    '<a class="bb-cta" href="/dinheiro.html#buscar">Buscar por CEP</a>' +
    '<p class="bb-nota">Todo número do site tem link para a fonte oficial do governo.</p>' +
    '</aside>';

  var caixa = document.createElement('div');
  caixa.innerHTML = html;
  var frag = document.createDocumentFragment();
  while (caixa.firstChild) frag.appendChild(caixa.firstChild);
  document.body.insertBefore(frag, document.body.firstChild);

  var topo = document.querySelector('.bb-topo');
  var veu = document.querySelector('.bb-veu');
  var menu = document.getElementById('bb-menu');

  var abrir = topo.querySelector('.bb-abrir');
  var fechar = menu.querySelector('.bb-fechar');

  var sumir = null;
  function alternar(aberto) {
    clearTimeout(sumir);
    menu.hidden = false;
    veu.hidden = false;
    void menu.offsetWidth; // reflow: garante a animação ao reabrir depois de hidden
    document.documentElement.classList.toggle('bb-aberto', aberto);
    abrir.setAttribute('aria-expanded', String(aberto));
    if (aberto) {
      fechar.focus();
    } else {
      abrir.focus();
      // Fechado, o menu sai da ordem de Tab (depois da animação de 180ms).
      sumir = setTimeout(function () { menu.hidden = true; veu.hidden = true; }, 200);
    }
  }
  abrir.addEventListener('click', function () { alternar(true); });
  fechar.addEventListener('click', function () { alternar(false); });
  veu.addEventListener('click', function () { alternar(false); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && document.documentElement.classList.contains('bb-aberto')) {
      alternar(false);
    }
  });
  menu.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a');
    if (a) {
      document.documentElement.classList.remove('bb-aberto');
      abrir.setAttribute('aria-expanded', 'false');
    }
  });
})();
