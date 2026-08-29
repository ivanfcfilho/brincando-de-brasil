// Executa as funções de renderização da landing contra uma resposta REAL da
// API (tests/fixture_consulta.json), sem navegador.
//
// Não substitui olhar a página, mas pega o que mais quebra quando a API muda:
// nome de campo que deixou de existir, e o 'undefined' que aparece na tela.
//
//   node tests/test_landing.cjs
const fs = require('fs');
const path = require('path');
const raiz = path.dirname(__dirname);

const html = fs.readFileSync(path.join(raiz, 'landing', 'index.html'), 'utf8');
let js = html.slice(html.indexOf('<script>') + 8, html.indexOf('</script>'));

const elemento = () => ({
  textContent: '', innerHTML: '', style: {}, hidden: false, className: '',
  appendChild() {}, addEventListener() {}, classList: { add() {} },
  scrollIntoView() {}, focus() {}, setCustomValidity() {}, reportValidity() {},
  get value() { return ''; }, set value(v) {},
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

const corte = js.lastIndexOf('})();');
js = js.slice(0, corte) + 'global.__render = render;\n' + js.slice(corte);
eval(js);

const dados = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixture_consulta.json'), 'utf8'));
global.__render(dados);
const saida = registro.verdict.innerHTML;

const testes = [
  ['nome do deputado',        /Rodrigo Valadares/],
  ['sigla do partido',        /UNIÃO/],
  ['origem dos votos',        /De onde vieram os votos/],
  ['destino do dinheiro',     /Para onde foi o dinheiro/],
  ['distância em km',         /\d+ km/],
  ['valor em reais',          /R\$ [\d.]+/],
  ['ressalva do centroide',   /centroides de território/],
  ['ressalva da sede',        /sede do favorecido/],
  ['ressalva do CEP',         /não o bairro nem a seção eleitoral/],
  ['proveniência (sha256)',   /sha256 [0-9a-f]{16}/],
  // A regra editorial vale para o texto da tela, não só para o pipeline.
  ['nenhuma inferência',      /Emenda para outro município é legal/],
  // A base não traz gênero; supor pelo nome erraria com metade das pessoas.
  ['texto sem gênero suposto', /votação total do parlamentar/],
];

let falhas = 0;
for (const [nome, re] of testes) {
  const ok = re.test(saida);
  if (!ok) falhas++;
  console.log(`  ${ok ? 'ok   ' : 'FALHA'} ${nome}`);
}
if (/undefined|NaN|\[object/.test(saida)) {
  console.log('  FALHA há undefined/NaN/[object] no HTML gerado');
  console.log('        ' + saida.match(/.{0,70}(undefined|NaN|\[object).{0,70}/)[0]);
  falhas++;
} else {
  console.log('  ok    nenhum undefined/NaN no HTML');
}
console.log(falhas ? `\n${falhas} FALHAS` : '\nTUDO OK');
process.exit(falhas ? 1 : 0);
