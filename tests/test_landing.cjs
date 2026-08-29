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

// A ferramenta de CEP mora em dinheiro.html; index.html é o hub do site.
const html = fs.readFileSync(path.join(raiz, 'landing', 'dinheiro.html'), 'utf8');
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
  ['destino do dinheiro',     /Para onde o dinheiro foi parar/],
  ['distância em km',         /\d+ km/],
  ['valor em reais',          /R\$ [\d.]+/],

  // Tradução do jargão: sem isto os números são verdadeiros e inúteis.
  ['explica "reservado"',     /Reservado no orçamento/],
  ['explica "já pago"',       /Já pago/],
  ['explica opacidade',       /não diz para qual/],
  ['diz que é legal',         /Mandar emenda para outra cidade é legal/],

  // Persuasão pelo mecanismo, nunca por acusação.
  ['argumento estrutural',    /o mandato não tem endereço/],
  ['liga ao voto distrital',  /voto distrital misto/],
  ['inocenta os listados',    /Nenhum dos nomes acima quebrou regra nenhuma/],

  // Rastreabilidade de verdade.
  ['link para a Câmara',      /camara\.leg\.br\/deputados\/\d+/],
  ['link para a fonte',       /href="https:\/\/[^"]*portaldatransparencia[^"]*"/],
  ['proveniência (sha256)',   /sha256 [0-9a-f]{16}/],

  // Ressalvas visíveis na tela, não só no README.
  ['ressalva do CEP',         /identifica a <b>cidade<\/b>/],
  ['ressalva do centroide',   /centro geográfico/],
  ['ressalva da sede',        /nem sempre é onde a obra acontece/],
  ['ressalva relator/bancada',/não têm autor individual/],
];

// Jargão de orçamento que não pode chegar ao leitor sem tradução.
const jargao = [/destino declarado/i, /\(execução\)/i, /favorecidos sediados/i,
                /ponderada por valor/i, /empenhad[ao]s? \(/i];


let falhas = 0;
for (const [nome, re] of testes) {
  const ok = re.test(saida);
  if (!ok) falhas++;
  console.log(`  ${ok ? 'ok   ' : 'FALHA'} ${nome}`);
}
for (const re of jargao) {
  if (re.test(saida)) {
    console.log(`  FALHA jargão sem tradução na tela: ${re}`);
    falhas++;
  }
}
if (!jargao.some((re) => re.test(saida))) {
  console.log('  ok    nenhum jargão de orçamento sem tradução');
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
