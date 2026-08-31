// A página mais delicada do site: comparação entre governos.
//
// O que este teste protege não é só renderização — é a POSTURA da página.
// Se as ressalvas sumirem numa refatoração, sobra um ranking de presidentes
// com cara de dado oficial, que é exatamente o que o projeto se recusa a
// publicar. Por isso as frases de cautela são testadas como se fossem código.
//
//   node tests/test_presidentes.cjs
const fs = require('fs');
const path = require('path');
const raiz = path.dirname(__dirname);

const html = fs.readFileSync(path.join(raiz, 'landing', 'presidentes.html'), 'utf8');
const ini = html.indexOf('<script>') + 8;
let js = html.slice(ini, html.indexOf('</script>', ini));

const elemento = () => ({
  textContent: '', innerHTML: '', style: {}, hidden: false, className: '',
  value: '', dataset: {},
  appendChild() {}, addEventListener() {}, classList: { add() {}, remove() {} },
  scrollIntoView() {}, focus() {}, setAttribute() {}, getAttribute() { return null; },
  querySelectorAll() { return []; }, querySelector() { return null; },
  closest() { return null; },
});
const registro = {};
global.document = {
  getElementById: (id) => (registro[id] = registro[id] || elemento()),
  createElement: () => ({
    set textContent(t) { this._t = String(t); },
    get innerHTML() {
      return (this._t || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    },
  }),
};
global.window = { matchMedia: () => ({ matches: true }) };
global.fetch = () => Promise.reject(new Error('sem rede no teste'));
global.setTimeout = (f) => f();

// A tabela usa a lista de indicadores do componente compartilhado
// (window.BB.governos.ORDEM) — carregamos o componente antes da página,
// exatamente como o navegador faz.
eval(fs.readFileSync(path.join(raiz, 'landing', 'governos.js'), 'utf8'));

const corte = js.lastIndexOf('})();');
// O comparador de barras saiu daqui para landing/governos.js (compartilhado
// com a home) e tem teste próprio, tests/test_governos.cjs. O que sobrou nesta
// página — e é o que este arquivo cobre — é a tabela completa, a lista de
// programas e as ressalvas.
js = js.slice(0, corte)
   + 'global.__D = function(d){ D = d; atual = series()[0]; '
   + 'pintaTabela(); pintaProgramas(); pintaFontes(); };\n'
   + js.slice(corte);
eval(js);

const dados = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixture_presidentes.json'), 'utf8'));
global.__D(dados);

const tabela = registro['tab'].innerHTML;
const govs = registro['govs'].innerHTML;
const estatico = html;

let falhas = 0;
function ok(nome, cond, det) {
  if (!cond) falhas++;
  console.log(`  ${cond ? 'ok  ' : 'FALHA'} ${nome}${det && !cond ? ' — ' + det : ''}`);
}

// ---- a ressalva, que é o coração da página ----
ok('diz "aconteceu no país", não "o presidente causou"',
   /aconteceu no país durante o mandato/.test(estatico));
ok('avisa que não tem ranking', /não tem nota, não tem ranking/.test(estatico));
ok('avisa sobre fatores fora de Brasília', /não passam por Brasília/.test(estatico));
ok('avisa que política demora a aparecer', /decidida no anterior/.test(estatico));
// \s+ em vez de espaço: o HTML quebra linha no meio da frase.
ok('explica por que não tem segurança',
   /não\s+publica\s+série\s+de\s+homicídios/.test(estatico));
ok('explica por que PIB per capita ficou fora', /sem corrigir a inflação/.test(estatico));

// ---- os oito governos ----
['Fernando Collor','Itamar Franco','Fernando Henrique','Lula','Dilma','Michel Temer','Jair Bolsonaro']
  .forEach(function(n){ ok('aparece '+n, tabela.indexOf(n) >= 0); });

// ---- números formatados em português, sem lixo ----
ok('inflação da hiperinflação aparece', /1\.518|963/.test(tabela));
ok('sem undefined na tabela', !/undefined/.test(tabela));
ok('sem NaN na tabela', !/NaN/.test(tabela));

// ---- "sem dado" é mostrado, não escondido ----
// O IPCA (primeiro indicador) tem dado para os oito governos, então a lacuna
// só aparece noutro. O PIB começa em 1996 e deixa Collor e Itamar de fora —
// é ali que a página tem que dizer "sem dado" em vez de omitir a linha.
const faltamPib = dados.presidentes.filter(function (p) {
  return p.indicadores.pib == null;
}).map(function (p) { return p.nome; });
ok('Collor e Itamar aparecem sem dado de PIB (a série começa em 1996)',
   faltamPib.length === 2, faltamPib.join(', '));
// (a representação de "sem dado" nas barras é do componente compartilhado e
//  está coberta em tests/test_governos.cjs; aqui basta a tabela)
ok('célula vazia na tabela vira travessão', /—/.test(tabela));

// ---- auditabilidade: quais anos entraram em cada número ----
ok('a tabela mostra os anos usados no title', /anos usados: \d{4}/.test(tabela));

// ---- programas com o ato legal ----
ok('programas listados', /Bolsa Fam/.test(govs) && /Plano Real/.test(govs));
ok('cada programa cita o ato', /Lei 10\.836\/2004|Emenda Constitucional 95\/2016/.test(govs));
ok('link para o Planalto', /planalto\.gov\.br/.test(govs));
ok('sem undefined nos programas', !/undefined/.test(govs));

console.log(falhas ? `\n${falhas} FALHA(S)` : '\nTUDO OK');
process.exit(falhas ? 1 : 0);
