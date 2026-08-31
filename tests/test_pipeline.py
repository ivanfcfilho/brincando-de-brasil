#!/usr/bin/env python3
"""Testes do pipeline. Rodar: python3.13 -m unittest discover -s tests -v

Cada teste de casamento de nomes é uma REGRESSÃO de erro que já aconteceu
neste projeto, com o nome real do caso. Não são exemplos inventados: são as
atribuições falsas que chegaram a entrar no banco antes da trava.
"""
import os
import shutil
import subprocess
import unittest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "pipeline"))
from nomes import (_compativel, casar_autor, chave_municipio, indice_por_nome,
                   norm, parse_valor)
from xlsx import _coluna, numero
import api


class TestNormalizacao(unittest.TestCase):
    def test_acento_e_caixa(self):
        self.assertEqual(norm("São Paulo"), "SAO PAULO")

    def test_pontuacao_vira_espaco(self):
        # 'MARIO NEGROMONTE JR.' (CGU) x 'MARIO NEGROMONTE JR' (TSE)
        self.assertEqual(norm("MARIO NEGROMONTE JR."), norm("MARIO NEGROMONTE JR"))

    def test_espaco_duplicado(self):
        self.assertEqual(norm("  A   B  "), "A B")

    def test_valor_brasileiro(self):
        self.assertEqual(parse_valor("1.234,56"), 1234.56)
        self.assertEqual(parse_valor(""), 0.0)
        self.assertEqual(parse_valor("lixo"), 0.0)


class TestChaveMunicipio(unittest.TestCase):
    """TSE, IBGE e CGU grafam o mesmo município de formas diferentes."""

    def test_apostrofo(self):
        self.assertEqual(chave_municipio("Alta Floresta D'Oeste"),
                         chave_municipio("ALTA FLORESTA D OESTE"))

    def test_preposicao(self):
        self.assertEqual(chave_municipio("Amparo do São Francisco"),
                         chave_municipio("AMPARO DE SAO FRANCISCO"))

    def test_acento(self):
        self.assertEqual(chave_municipio("Poço Redondo"),
                         chave_municipio("POCO REDONDO"))

    def test_nao_colapsa_municipios_distintos(self):
        # Camacan x Camaçari são vizinhos na Bahia e não podem virar um só.
        self.assertNotEqual(chave_municipio("Camacan"), chave_municipio("Camaçari"))
        self.assertNotEqual(chave_municipio("Embu das Artes"),
                            chave_municipio("Embu-Guaçu"))


class TestCompatibilidadeDeNomes(unittest.TestCase):
    """A trava de primeiro/último nome. Os casos FALSOS são reais: chegaram a
    entrar no banco e atribuíam a emenda de uma pessoa a outra."""

    FALSOS = [
        ("EDUARDO BRAGA", "CARLOS EDUARDO BRAGA MENEZES"),   # senador AM x suplente MG
        ("KATIA ABREU", "CRISTIANE KATIA SIMONI ABREU"),     # senadora TO x suplente SP
        ("JESUS RODRIGUES", "ESLEY RODRIGUES DE JESUS TEIXEIRA"),
        ("EDSON SANTOS", "EDSON MATOS DOS SANTOS JUNIOR"),
        ("ASSIS CARVALHO", "FRANCISCO DE ASSIS CARVALHO ARTEN"),
        ("JOSE SILVA", "JOSE DA SILVA SANTOS"),              # ambíguo de verdade
    ]
    VERDADEIROS = [
        ("JOVAIR ARANTES", "JOVAIR DE OLIVEIRA ARANTES"),
        ("LUIZ CARLOS HAULY", "LUIZ CARLOS JORGE HAULY"),
        ("EVANDRO MILHOMEN", "EVANDRO COSTA MILHOMEN"),
        ("LEONARDO PICCIANI", "LEONARDO CARNEIRO MONTEIRO PICCIANI"),
    ]

    def test_rejeita_pessoas_diferentes(self):
        for autor, alvo in self.FALSOS:
            with self.subTest(autor=autor):
                self.assertFalse(_compativel(norm(autor).split(), norm(alvo).split()),
                                 f"{autor} não é {alvo}")

    def test_aceita_mesma_pessoa(self):
        for autor, alvo in self.VERDADEIROS:
            with self.subTest(autor=autor):
                self.assertTrue(_compativel(norm(autor).split(), norm(alvo).split()))


class TestIndicePorNome(unittest.TestCase):
    """Homônimo entre eleito e suplente: quem exerce o mandato vence."""

    def test_eleito_vence_suplente(self):
        idx = indice_por_nome([
            ("SQ_SUP", "ALEX SANTANA DA SILVA", "ALEX SANTANA", None, False),
            ("SQ_ELE", "ALEX MARCO SANTANA SOUSA", "ALEX SANTANA", None, True),
        ])
        self.assertEqual(idx["ALEX SANTANA"], "SQ_ELE")

    def test_ordem_de_entrada_nao_importa(self):
        idx = indice_por_nome([
            ("SQ_ELE", "ALEX MARCO SANTANA SOUSA", "ALEX SANTANA", None, True),
            ("SQ_SUP", "ALEX SANTANA DA SILVA", "ALEX SANTANA", None, False),
        ])
        self.assertEqual(idx["ALEX SANTANA"], "SQ_ELE")

    def test_dois_eleitos_homonimos_ficam_ambiguos(self):
        idx = indice_por_nome([
            ("SQ_A", "JOAO A", "JOAO SILVA", None, True),
            ("SQ_B", "JOAO B", "JOAO SILVA", None, True),
        ])
        self.assertNotIn("JOAO SILVA", idx)

    def test_nome_parlamentar_da_camara_entra_no_indice(self):
        # 'DEPUTADO DAL' no TSE x 'DAL BARRETO' na CGU: só a Câmara liga.
        idx = indice_por_nome([
            ("SQ_DAL", "ADALBERTO ROSA BARRETO", "DEPUTADO DAL", "DAL BARRETO", True),
        ])
        self.assertEqual(idx["DAL BARRETO"], "SQ_DAL")


class TestCasarAutor(unittest.TestCase):
    CANDS = [("SQ1", "JOVAIR DE OLIVEIRA ARANTES", "JOVAIR"),
             ("SQ2", "CARLOS EDUARDO BRAGA MENEZES", "KAKA MENEZES")]

    def setUp(self):
        self.idx = indice_por_nome(self.CANDS)

    def test_exato(self):
        sq, metodo = casar_autor("JOVAIR", self.idx, self.CANDS)
        self.assertEqual((sq, metodo), ("SQ1", "exato"))

    def test_tokens(self):
        sq, metodo = casar_autor("JOVAIR ARANTES", self.idx, self.CANDS)
        self.assertEqual((sq, metodo), ("SQ1", "tokens"))

    def test_nao_chuta(self):
        sq, _ = casar_autor("EDUARDO BRAGA", self.idx, self.CANDS)
        self.assertIsNone(sq, "match errado é pior que match nenhum")

    def test_alias_manual(self):
        sq, metodo = casar_autor("APELIDO QUALQUER", self.idx, self.CANDS,
                                 {"APELIDO QUALQUER": "JOVAIR"})
        self.assertEqual((sq, metodo), ("SQ1", "alias"))


class TestCentroide(unittest.TestCase):
    def setUp(self):
        from ingest_municipios import centroide
        self.centroide = centroide

    def test_quadrado(self):
        quadrado = {"type": "Polygon",
                    "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
        lon, lat = self.centroide(quadrado)
        self.assertAlmostEqual(lon, 1.0, places=6)
        self.assertAlmostEqual(lat, 1.0, places=6)

    def test_ponderado_por_area_nao_por_vertice(self):
        """Média de vértices puxaria o ponto para onde o contorno tem mais
        detalhe — num município de litoral recortado, para o mar."""
        denso = ([[0, 0]] + [[x / 100, 0] for x in range(1, 100)]
                 + [[1, 0], [1, 1], [0, 1], [0, 0]])
        lon, lat = self.centroide({"type": "Polygon", "coordinates": [denso]})
        self.assertAlmostEqual(lat, 0.5, places=3)

    def test_multipolygon_usa_maior_anel(self):
        geom = {"type": "MultiPolygon", "coordinates": [
            [[[0, 0], [0.1, 0], [0.1, 0.1], [0, 0.1], [0, 0]]],      # ilhota
            [[[10, 10], [12, 10], [12, 12], [10, 12], [10, 10]]],    # continente
        ]}
        lon, lat = self.centroide(geom)
        self.assertAlmostEqual(lon, 11.0, places=6)


class TestPrefixo(unittest.TestCase):
    """O site precisa funcionar na raiz de um domínio E sob um prefixo de
    caminho (`/brincandodebrasil`), porque o servidor de produção já hospeda
    outro site. Todo link interno é de raiz; sob prefixo, sem reescrita, eles
    apontariam para fora da aplicação e a página abriria quebrada."""

    HTML = (b'<script src="/menu.js"></script>'
            b'<a href="/escola.html">a</a>'
            b'<a href="https://gov.br/x">fora</a>'
            b'<a href="#ancora">ancora</a>'
            b"<script>fetch('/api/saude')</script>")

    def setUp(self):
        self._antes = api.PREFIXO

    def tearDown(self):
        api.PREFIXO = self._antes

    def test_sem_prefixo_nada_muda(self):
        api.PREFIXO = ""
        self.assertEqual(api.Handler._com_prefixo(self.HTML), self.HTML)

    def test_com_prefixo_reescreve_so_o_que_e_da_raiz(self):
        api.PREFIXO = "/brincandodebrasil"
        saida = api.Handler._com_prefixo(self.HTML).decode()
        self.assertIn('src="/brincandodebrasil/menu.js"', saida)
        self.assertIn('href="/brincandodebrasil/escola.html"', saida)
        self.assertIn("fetch('/brincandodebrasil/api/saude')", saida)
        # Link externo e âncora não podem ser tocados: prefixar um domínio de
        # terceiro quebraria a rastreabilidade à fonte oficial, que é a
        # promessa central do projeto.
        self.assertIn('href="https://gov.br/x"', saida)
        self.assertIn('href="#ancora"', saida)

    def test_publica_o_prefixo_para_o_menu(self):
        # O menu.js monta os links em JavaScript e não passa pela reescrita:
        # sem esta variável, a navegação inteira apontaria para a raiz.
        api.PREFIXO = "/brincandodebrasil"
        saida = api.Handler._com_prefixo(self.HTML).decode()
        self.assertIn('window.BB_PREFIXO="/brincandodebrasil"', saida)


class TestPlanilhaIdeb(unittest.TestCase):
    """O leitor de .xlsx do Ideb. Os dois casos abaixo são as armadilhas que
    fariam a planilha ser lida errada SEM levantar exceção — o tipo de erro
    que este projeto trata como o mais perigoso."""

    def test_coluna_pela_referencia_e_nao_pela_ordem(self):
        # Célula vazia não aparece no XML: numa linha esparsa, quem conta
        # elementos desalinha a planilha inteira e carimba o valor de uma
        # coluna na outra. A posição TEM que vir da referência.
        self.assertEqual(_coluna("A1"), 0)
        self.assertEqual(_coluna("D12"), 3)
        self.assertEqual(_coluna("Z1"), 25)
        self.assertEqual(_coluna("AA1"), 26)
        self.assertEqual(_coluna("DR14517"), 121)   # a última coluna do arquivo

    def test_ausencia_nao_vira_zero(self):
        # O INEP marca rede não divulgada com '-'. Virar 0.0 criaria um
        # município com "Ideb zero" que entra em toda média como se fosse
        # medição real.
        self.assertIsNone(numero("-"))
        self.assertIsNone(numero(""))
        self.assertIsNone(numero("ND"))
        self.assertIsNone(numero(None))
        self.assertEqual(numero("5.9"), 5.9)
        self.assertEqual(numero("5,9"), 5.9)        # planilha em pt-BR
        self.assertEqual(numero("0"), 0.0)          # zero medido é zero


class TestLanding(unittest.TestCase):
    """A renderização da landing roda em Node contra uma resposta real da API
    (tests/fixture_consulta.json). Se o Node não existir, o teste é pulado —
    o pipeline não depende dele para rodar."""

    def test_render_com_dados_reais(self):
        node = shutil.which("node") or shutil.which("nodejs")
        if not node:
            self.skipTest("node não instalado")
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "test_landing.cjs")
        r = subprocess.run([node, script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_render_como_funciona_e_a_conta_das_cadeiras(self):
        """Inclui a matemática do simulador — a única conta que o site FAZ,
        em vez de só mostrar. Errar ali seria ensinar errado."""
        node = shutil.which("node") or shutil.which("nodejs")
        if not node:
            self.skipTest("node não instalado")
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "test_como_funciona.cjs")
        r = subprocess.run([node, script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_render_presidentes_e_as_ressalvas(self):
        """Inclui as frases de cautela como se fossem código: sem elas a
        página vira um ranking de presidentes com cara de dado oficial."""
        node = shutil.which("node") or shutil.which("nodejs")
        if not node:
            self.skipTest("node não instalado")
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "test_presidentes.cjs")
        r = subprocess.run([node, script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_render_escola_com_dados_reais(self):
        node = shutil.which("node") or shutil.which("nodejs")
        if not node:
            self.skipTest("node não instalado")
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "test_escola.cjs")
        r = subprocess.run([node, script], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
