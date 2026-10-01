"""Tela de Produção: campo de nomes sem memória e lista de resultados só após clicar em extrair."""
import os
import time
from unittest import mock, skipUnless

from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import TestCase
from django.urls import reverse

from .services import scraper_service
from .tests_unidade import ScraperFalso, _ServidorUmaPorVez
from .tests_unidade_logada import AME


class CampoSemMemoriaTests(TestCase):
    def test_textarea_dos_nomes_nao_deixa_o_navegador_lembrar(self):
        User.objects.create_user('medico', password='senha123')
        self.client.login(username='medico', password='senha123')
        html = self.client.get(reverse('siresp_app:producao_home')).content.decode('utf-8')
        trecho = html[html.index('<textarea id="lote-nomes"'):]
        trecho = trecho[:trecho.index('>')]
        self.assertIn('autocomplete="off"', trecho)
        self.assertIn("document.getElementById('lote-nomes').value = '';", html)   # e a tela zera ao abrir
        # a lista de resultados só é retomada se o lote ainda estiver rodando
        self.assertIn('if (!data.rodando && !loteIniciadoAqui)', html)


@skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1', 'defina RUN_BROWSER_TESTS=1 para rodar no Chrome')
class LoteNaTelaTests(StaticLiveServerTestCase):
    server_thread_class = _ServidorUmaPorVez

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        o = Options()
        o.add_argument('--headless=new')
        o.add_argument('--window-size=1400,1000')
        cls.b = webdriver.Chrome(options=o)

    @classmethod
    def tearDownClass(cls):
        cls.b.quit()
        super().tearDownClass()

    def setUp(self):
        from selenium.webdriver.support.ui import WebDriverWait
        self.WebDriverWait = WebDriverWait
        self.user = User.objects.create_user('medico', password='senha123')
        scraper_service._SCRAPERS.clear()
        self.addCleanup(scraper_service._SCRAPERS.clear)
        self.addCleanup(self._parar)
        sc = ScraperFalso(aguardando=False)
        sc.logado = True
        sc.unidade_atual = AME
        scraper_service._SCRAPERS[self.user.id] = sc
        self.b.get(self.live_server_url + '/login/')
        self.client.force_login(self.user)
        self.b.add_cookie({'name': 'sessionid', 'value': self.client.cookies['sessionid'].value, 'path': '/'})

    def _parar(self):
        try:
            self.b.get('about:blank')
        except Exception:
            pass
        time.sleep(1)

    def abrir(self):
        self.b.get(self.live_server_url + reverse('siresp_app:producao_home'))
        self.WebDriverWait(self.b, 10).until(
            lambda d: 'Logado' in d.find_element('id', 'status-text').text)

    def digitar_periodo_e_nomes(self, nomes):
        self.b.find_element('id', 'data-ini').send_keys('01082026')
        self.b.find_element('id', 'data-fim').send_keys('31082026')
        self.b.find_element('id', 'lote-nomes').send_keys('\n'.join(nomes))

    def test_lote_antigo_nao_reaparece_e_o_campo_nao_lembra(self):
        busca = lambda u, n, o: [{'nome': n, 'crm': '1', 'codigo': '1'}]
        dados = [{'Especialidade': 'CARDIOLOGIA', 'Oferta_N': '10'}]
        alvo = 'siresp_app.services.lote_service.scraper_service'
        with mock.patch(alvo + '.listar_medicos', side_effect=busca), \
                mock.patch(alvo + '.extrair_producao', return_value=dados):
            self.abrir()
            progresso = self.b.find_element('id', 'lote-progresso')
            self.assertIn('d-none', progresso.get_attribute('class'))      # nada de histórico antes do clique
            self.digitar_periodo_e_nomes(['ANA LIMA', 'BRUNO DIAS'])
            self.WebDriverWait(self.b, 10).until(lambda d: d.find_element('id', 'btn-lote').is_enabled())
            self.b.execute_script('arguments[0].click();', self.b.find_element('id', 'btn-lote'))
            self.WebDriverWait(self.b, 20).until(
                lambda d: 'finalizado' in d.find_element('id', 'lote-resumo').text)
            self.assertEqual(len(self.b.find_elements('css selector', '#lote-itens tr')), 2)   # aparece após o clique

            # volta à tela (recarregar): o resultado antigo e os nomes digitados não voltam
            self.b.refresh()
            self.WebDriverWait(self.b, 10).until(
                lambda d: 'Logado' in d.find_element('id', 'status-text').text)
            time.sleep(3)                                                   # dá tempo da tela consultar o servidor
            self.assertIn('d-none', self.b.find_element('id', 'lote-progresso').get_attribute('class'))
            self.assertEqual(len(self.b.find_elements('css selector', '#lote-itens tr')), 0)
            self.assertEqual(self.b.find_element('id', 'lote-nomes').get_attribute('value'), '')

    def test_lote_em_andamento_e_retomado_ao_reabrir_a_tela(self):
        def devagar(u, m, i, f):
            time.sleep(1.2)
            return [{'Especialidade': 'CARDIOLOGIA', 'Oferta_N': '10'}]

        busca = lambda u, n, o: [{'nome': n, 'crm': '1', 'codigo': '1'}]
        alvo = 'siresp_app.services.lote_service.scraper_service'
        with mock.patch(alvo + '.listar_medicos', side_effect=busca), \
                mock.patch(alvo + '.extrair_producao', side_effect=devagar):
            self.abrir()
            self.digitar_periodo_e_nomes(['ANA LIMA', 'BRUNO DIAS', 'CARLA MELO'])
            self.WebDriverWait(self.b, 10).until(lambda d: d.find_element('id', 'btn-lote').is_enabled())
            self.b.execute_script('arguments[0].click();', self.b.find_element('id', 'btn-lote'))
            self.WebDriverWait(self.b, 10).until(
                lambda d: 'em andamento' in d.find_element('id', 'lote-resumo').text)
            self.b.refresh()                                                # abre a tela com o lote rodando
            self.WebDriverWait(self.b, 10).until(
                lambda d: 'em andamento' in d.find_element('id', 'lote-resumo').text)   # retomado
            self.WebDriverWait(self.b, 25).until(
                lambda d: 'finalizado' in d.find_element('id', 'lote-resumo').text)     # e mostra o final
            self.assertEqual(len(self.b.find_elements('css selector', '#lote-itens tr')), 3)
