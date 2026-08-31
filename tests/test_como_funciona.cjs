// Testa a página que ENSINA a regra eleitoral — em dois níveis.
//
//  1. A MATEMÁTICA do simulador. É a única parte do site em que a página faz
//     uma conta em vez de mostrar um dado do governo. Se ela errar, o site
//     ensina errado, o que é pior que não ensinar. Os casos abaixo foram
//     resolvidos na mão pela regra brasileira (quociente eleitoral, quociente
//     partidário e sobras pelas maiores médias).
//  2. A RENDERIZAÇÃO contra uma resposta real da API (fixture_sistema.json),
//     incluindo a ressalva de que "não foi eleito" ≠ "não está na Câmara" —
//     a frase que impede a página de mentir sobre uma pessoa real.
//
//   node tests/test_como_funciona.cjs
const fs = require('fs');
const path = require('path');
const raiz = path.dirname(__dirname);

const html = fs.readFileSync(path.join(raiz, 'landing', 'como-funciona.html'), 'utf8');
const ini = html.indexOf('<script>') + 8;
let js = html.slice(ini, html.indexOf('</script>', ini));

const elemento = () => ({
  textContent: '', innerHTML: '', style: {}, hidden: false, className: '',
  value: '10', dataset: {},
  appendChild() {}, addEventListener() {}, classList: { add() {}, remove() {} },
  scrollIntoView() {}, focus() {}, setCustomValidity() {}, reportValidity() {},
  setAttribute() {}, getAttribute() { return null; },
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
global.encodeURIComponent = (s) => String(s);

const corte = js.lastIndexOf('})();');
js = js.slice(0, corte)
   + 'global.__distribuir = distribuir;\nglobal.__renderReal = renderReal;\n'
   + js.slice(corte);
eval(js);

let falhas = 0;
function ok(nome, cond, detalhe) {
  if (!cond) falhas++;
  console.log(`  ${cond ? 'ok  ' : 'FALHA'} ${nome}${detalhe && !cond ? ' — ' + detalhe : ''}`);
}

// ---------------------------------------------------------------- a conta
// Caso resolvido na mão:
//   total 100.000 ÷ 10 cadeiras → quociente 10.000
//   direto: A=4 B=2 C=1 D=1 (8 cadeiras); sobram 2
//   1ª sobra: maiores médias → A (48000/5 = 9600) vence B (27000/3 = 9000)
//   2ª sobra: B (9000) vence A (48000/6 = 8000)
//   final: A=5 B=3 C=1 D=1
let r = global.__distribuir([48000, 27000, 15000, 10000], 10);
ok('quociente eleitoral = total ÷ cadeiras', r.qe === 10000, `deu ${r.qe}`);
ok('distribuição bate com a conta feita à mão',
   JSON.stringify(r.cadeiras) === JSON.stringify([5, 3, 1, 1]),
   `deu ${JSON.stringify(r.cadeiras)}`);

// A soma das cadeiras SEMPRE tem que fechar com as vagas — em qualquer
// entrada. É o invariante que pega erro de arredondamento do quociente.
let todasFecham = true, pior = null;
for (let vagas = 2; vagas <= 20; vagas++) {
  for (let t = 0; t < 60; t++) {
    const v = [0, 1, 2, 3].map(() => Math.floor(Math.random() * 60000 / 1000) * 1000);
    if (v.reduce((a, b) => a + b, 0) === 0) continue;
    const d = global.__distribuir(v, vagas);
    const soma = d.cadeiras.reduce((a, b) => a + b, 0);
    if (soma !== vagas) { todasFecham = false; pior = { v, vagas, soma }; }
  }
}
ok('as cadeiras distribuídas somam sempre o total de vagas', todasFecham,
   JSON.stringify(pior));

// Partido sem voto nenhum não pode ganhar cadeira.
r = global.__distribuir([50000, 0, 0, 0], 5);
ok('partido com zero voto não ganha cadeira',
   r.cadeiras[1] === 0 && r.cadeiras[2] === 0 && r.cadeiras[3] === 0,
   JSON.stringify(r.cadeiras));
ok('partido único leva todas as vagas', r.cadeiras[0] === 5, JSON.stringify(r.cadeiras));

// Empate perfeito reparte igual.
r = global.__distribuir([10000, 10000, 10000, 10000], 8);
ok('empate perfeito reparte igual',
   JSON.stringify(r.cadeiras) === JSON.stringify([2, 2, 2, 2]),
   JSON.stringify(r.cadeiras));

// Sem voto nenhum não quebra e não inventa cadeira.
r = global.__distribuir([0, 0, 0, 0], 10);
ok('eleição sem votos não quebra',
   r.cadeiras.reduce((a, b) => a + b, 0) === 0, JSON.stringify(r.cadeiras));

// ---------------------------------------------------------------- a tela
const dados = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixture_sistema.json'), 'utf8'));
global.__renderReal(dados);
const saida = registro['saida-real'].innerHTML;

const testes = [
  ['nome do estado por extenso', /Sergipe/],
  ['quantas cadeiras', /8<\/b> cadeiras/],
  ['o mais votado do estado', /mais votado do estado/],
  ['o confronto', /teve mais votos e NÃO foi eleito/],
  ['e o outro lado', /teve menos votos e FOI eleito/],
  ['a diferença em votos', /Diferença de/],
  ['diz que os dois seguiram a regra', /seguiram a regra/],

  // A ressalva que impede a página de mentir sobre uma pessoa real.
  ['explica o que é suplente', /assume a vaga se um/],
  ['diz que não foi eleito ≠ fora da Câmara', /não que ela esteja/],

  ['sem undefined', /undefined/, true],
  ['sem NaN', /NaN/, true],
];
for (const [nome, regex, proibido] of testes) {
  const achou = regex.test(saida);
  ok(nome, proibido ? !achou : achou);
}

// O número da manchete tem que vir do banco, não do HTML.
ok('manchete recebe o número nacional do banco',
   registro['nac-paradoxo'].textContent === '119',
   `deu "${registro['nac-paradoxo'].textContent}"`);

// Estado sem nenhum caso não pode renderizar vazio nem quebrar.
global.__renderReal({
  uf: 'XX', uf_nome: 'Estado Teste',
  panorama: { total: 10, cadeiras: 8, por_quociente: 8, por_sobra: 0 },
  paradoxo: [], partidos: [], puxador: null, nacional: {},
});
const vazio = registro['saida-real'].innerHTML;
ok('estado sem caso é explicado, não fica em branco',
   /nenhum candidato não/.test(vazio) && !/undefined/.test(vazio));

console.log(falhas ? `\n${falhas} FALHA(S)` : '\nTUDO OK');
process.exit(falhas ? 1 : 0);
