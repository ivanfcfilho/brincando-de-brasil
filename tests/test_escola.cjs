// Executa a renderização de escola.html contra uma resposta REAL da API
// (tests/fixture_educacao.json), sem navegador.
//
// O que este teste protege, além de campo renomeado e 'undefined' na tela:
// a página promete ENSINAR, e o que ensina é a parte que some primeiro numa
// refatoração. Se a conta (nota × aprovação) ou a frase que diz qual político
// responde pela escola sumirem, sobra um número bonito que não ensina nada —
// e o projeto inteiro existe para o contrário disso.
//
//   node tests/test_escola.cjs
const fs = require('fs');
const path = require('path');
const raiz = path.dirname(__dirname);

const html = fs.readFileSync(path.join(raiz, 'landing', 'escola.html'), 'utf8');
// O primeiro </script> do arquivo fecha o include de /menu.js; o bloco que
// interessa é o inline, que vem depois.
const ini = html.indexOf('<script>') + 8;
let js = html.slice(ini, html.indexOf('</script>', ini));

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

const dados = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixture_educacao.json'), 'utf8'));
global.__render(dados);
const saida = registro.saida.innerHTML;

const testes = [
  ['nome da cidade',           /Aracaju\/SE/],
  ['as três etapas',           /Do 1º ao 5º ano[\s\S]*Do 6º ao 9º ano[\s\S]*Ensino médio/],
  ['o Ideb com uma decimal',   /Ideb 2023/],

  // A lição cívica. Sem ela a página vira placar; com ela vira endereço de
  // cobrança — que é a razão de a Ideia #02 existir.
  ['quem responde',            /Quem responde por esta escola/],
  ['aponta o prefeito',        /prefeito\(a\) e vereadores/],
  ['aponta o governador',      /governador\(a\) e deputados estaduais/],

  // A conta aberta. O Ideb divulgado é um número só; a página existe para
  // mostrar as duas parcelas que o compõem.
  ['mostra a conta',           /a conta:/],
  ['a nota da prova',          /de nota na prova/],
  ['a taxa de aprovação',      /de alunos aprovados/],
  ['a multiplicação',          /×/],

  // A meta é um compromisso com prazo: é o que torna o número cobrável.
  ['presta contas da meta',    /A meta oficial para/],
  ['diz se cumpriu',           /cumpriu|não cumpriu/],

  // Comparação em português, não em jargão estatístico.
  ['posição no estado',        /Entre as cidades do SE/],
  ['explica a mediana',        /Cidade do meio no estado/],

  // Linguagem simples: o teste falha se o jargão voltar para a tela.
  ['sem "percentil"',          /percentil/, true],
  ['sem "indicador de rendimento"', /indicador de rendimento/i, true],
  ['sem "VL_OBSERVADO"',       /VL_OBSERVADO/, true],
  ['sem undefined',            /undefined/, true],
  ['sem NaN',                  /NaN/, true],
];

let falhas = 0;
for (const [nome, regex, proibido] of testes) {
  const achou = regex.test(saida);
  const ok = proibido ? !achou : achou;
  if (!ok) falhas++;
  console.log(`  ${ok ? 'ok  ' : 'FALHA'} ${nome}`);
}

// A etapa sem medição não pode sumir da tela: "não existe rede municipal de
// ensino médio aqui" é informação, e apagá-la faria a página mentir por
// omissão para as cidades pequenas.
const semMedicao = { medido: false, titulo: 'Teste', rede: 'Municipal', uf: 'SE' };
global.__render({ municipio: 'Teste', uf: 'SE', etapas: [semMedicao] });
const vazio = registro.saida.innerHTML;
const okVazio = /não divulgou nota/.test(vazio) && !/undefined/.test(vazio);
console.log(`  ${okVazio ? 'ok  ' : 'FALHA'} etapa sem medição é explicada, não escondida`);
if (!okVazio) falhas++;

console.log(falhas ? `\n${falhas} FALHA(S)` : '\nTUDO OK');
process.exit(falhas ? 1 : 0);
