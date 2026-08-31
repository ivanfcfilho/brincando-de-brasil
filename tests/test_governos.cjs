// O comparador entre governos (landing/governos.js), que a home e a página
// /presidentes.html compartilham.
//
// Testado à parte porque é o componente que leva o dado mais delicado do site
// para a PRIMEIRA página, onde chega gente que não vai ler nenhuma ressalva
// longa. As duas coisas que este teste protege:
//   1. a ordem é cronológica, nunca do maior para o menor — ordenar por valor
//      transformaria o gráfico num ranking de presidentes;
//   2. a legenda que separa "aconteceu no país" de "o presidente causou"
//      continua na tela.
//
//   node tests/test_governos.cjs
const fs = require('fs');
const path = require('path');
const raiz = path.dirname(__dirname);

const alvos = {};
function elemento(id) {
  return {
    id, className: '', innerHTML: '', textContent: '', dataset: {},
    style: {}, hidden: false,
    appendChild(f) { this.filhos = (this.filhos || []).concat([f]); },
    addEventListener(ev, fn) { this['on' + ev] = fn; },
    setAttribute() {}, getAttribute() { return null; },
    closest() { return null; },
  };
}
global.document = {
  head: elemento('head'), body: elemento('body'),
  getElementById: (id) => (alvos[id] = alvos[id] || elemento(id)),
  createElement: (tag) => {
    const e = elemento(tag);
    if (tag === 'div') {
      Object.defineProperty(e, 'textContent', {
        set(t) { this._t = String(t); },
        get() { return this._t || ''; },
      });
      Object.defineProperty(e, 'innerHTML', {
        get() {
          return (this._t || '').replace(/&/g, '&amp;')
            .replace(/</g, '&lt;').replace(/>/g, '&gt;');
        },
        set(v) { this._h = v; },
      });
    }
    return e;
  },
};
global.window = {};

const dados = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'fixture_presidentes.json'), 'utf8'));

global.fetch = () => Promise.resolve({
  ok: true, json: () => Promise.resolve(dados),
});

eval(fs.readFileSync(path.join(raiz, 'landing', 'governos.js'), 'utf8'));

let falhas = 0;
function ok(nome, cond, det) {
  if (!cond) falhas++;
  console.log(`  ${cond ? 'ok  ' : 'FALHA'} ${nome}${det && !cond ? ' — ' + det : ''}`);
}

ok('o componente se publica em window.BB.governos',
   !!(global.window.BB && global.window.BB.governos));

const alvo = elemento('alvo');
global.window.BB.governos.montar(alvo, { compacto: true });

setTimeout(function () {
  // O componente escreve num filho criado por createElement; juntamos tudo.
  const html = (alvo.filhos || []).map(function (f) {
    return (f._h || f.innerHTML || '');
  }).join('\n');

  ok('desenhou alguma coisa', html.length > 200, `${html.length} chars`);

  const nomes = dados.presidentes.map(function (p) { return p.nome; });
  nomes.forEach(function (n) {
    ok('aparece ' + n, html.indexOf(n) >= 0);
  });

  // A ORDEM É O TESTE MAIS IMPORTANTE DESTE ARQUIVO.
  const posicoes = nomes.map(function (n) { return html.indexOf(n); });
  const cronologica = posicoes.every(function (p, i) {
    return i === 0 || p > posicoes[i - 1];
  });
  ok('ordem cronológica, não do maior para o menor (senão vira ranking)',
     cronologica, posicoes.join(','));

  ok('a legenda separa "aconteceu" de "causou"',
     /não é a mesma coisa que o que o presidente causou/.test(html));
  ok('a legenda explica por que não ordena', /criaria um ranking/.test(html));
  ok('cada indicador tem explicação em português simples',
     /Quanto os preços subiram|Quanto a economia/.test(html));
  ok('link para a fonte oficial', /ver na fonte oficial/.test(html));
  // "Sem dado" só aparece num indicador que tenha lacuna. A inflação (a aba
  // inicial) cobre os oito governos; o PIB começa em 1996 e deixa Collor e
  // Itamar de fora. Trocamos de aba para checar que a ausência é MOSTRADA em
  // vez de a linha ser omitida — sumir com o governo seria reescrever a
  // história por conveniência de layout.
  const abas = alvo.filhos[0];
  abas.onclick({ target: { closest: () => ({ dataset: { s: 'pib' } }) } });
  const htmlPib = (alvo.filhos || []).map(function (f) {
    return (f._h || f.innerHTML || '');
  }).join('\n');
  ok('período sem dado é mostrado, não escondido', /sem dado/.test(htmlPib));
  ok('mesmo sem dado, o governo continua na lista',
     htmlPib.indexOf('Fernando Collor') >= 0 && htmlPib.indexOf('Itamar') >= 0);

  ok('sem undefined', !/undefined/.test(html));
  ok('sem NaN', !/NaN/.test(html));

  console.log(falhas ? `\n${falhas} FALHA(S)` : '\nTUDO OK');
  process.exit(falhas ? 1 : 0);
}, 0);
