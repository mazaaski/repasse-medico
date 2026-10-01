"""Seleção de unidade no login do SIRESP (servidor e tela)."""
import os
import threading
import time
from unittest import mock, skipUnless

from django.contrib.auth.models import User
from django.core.servers.basehttp import WSGIServer
from django.core.signals import request_finished, request_started
from django.test import TransactionTestCase, LiveServerTestCase
from django.test.testcases import LiveServerThread
from django.urls import reverse

from .models import ConfiguracaoLogin, LogAuditoria, SessaoSiresp
from .services import scraper_service
from .tests_util import AguardaThreads

UNIDADES = [
    {'valor': '2206_AME SAO JOSE DO RIO PRETO',
     'texto': '6056148 - AME SAO JOSE DO RIO PRETO - Administrador Unidade Reg'},
    {'valor': '9239_AME SAO JOSE RIO PRETO - ALCOOL-DROGAS',
     'texto': '6056148 - AME SAO JOSE RIO PRETO - ALCOOL-DROGAS - Administrador Unidade Reg'},
    {'valor': '2191_HOSP EST JOAO PAULO II',
     'texto': '6236596 - HOSP EST JOAO PAULO II - Administrador Unidade Reg'},
]


class _Driver:
    current_url = 'https://siresp/principal.php'


class ScraperFalso:
    """Imita SirespScraper o bastante para o serviço e as views."""

    def __init__(self, aguardando=True, recusa=False, resultado_final=None):
        self.driver = _Driver()
        self.logado = False
        self.captcha_disponivel = False
        self.captcha_imagem_b64 = None
        self.captcha_id = 0
        self.aguardando_unidade = aguardando
        self.unidades_disponiveis = list(UNIDADES) if aguardando else []
        self.recusa = recusa
        self.resultado_final = resultado_final or {'ok': True, 'mensagem': 'Login concluído.'}
        self.escolhida = None
        self.chamadas_escolher = 0
        self.recebeu_preferida = None

    def enviar_captcha(self, texto):
        return {'ok': True}

    def continuar_login_apos_captcha(self, cpf_pri, cpf_ult, rg_pri, rg_ult, unidade_preferida=''):
        self.recebeu_preferida = unidade_preferida
        self.aguardando_unidade = True
        return {'ok': False, 'aguardando_unidade': True, 'unidades': list(UNIDADES),
                'mensagem': 'Selecione a unidade para continuar.', 'captcha_novo': False}

    def escolher_unidade(self, valor):
        self.chamadas_escolher += 1
        if self.recusa:
            return {'ok': False, 'mensagem': 'Unidade inválida.'}
        self.escolhida = valor
        self.aguardando_unidade = False
        return {'ok': True}

    def concluir_login(self):
        if self.resultado_final.get('ok'):
            self.logado = True
        return self.resultado_final

    def fechar(self):
        self.driver = None


def _esperar(cond, segundos=5):
    fim = time.time() + segundos
    while time.time() < fim:
        if cond():
            return True
        time.sleep(0.05)
    return False


class UnidadeServidorTests(AguardaThreads, TransactionTestCase):
    # TransactionTestCase: as threads de fundo do login precisam enxergar/gravar dados commitados
    def setUp(self):
        self.user = User.objects.create_user('medico', password='senha123')
        self.client.login(username='medico', password='senha123')
        scraper_service._SCRAPERS.clear()
        self.addCleanup(scraper_service._SCRAPERS.clear)

    def _sessao(self, **kw):
        sc = ScraperFalso(**kw)
        scraper_service._SCRAPERS[self.user.id] = sc
        return sc

    def test_status_expoe_a_lista_de_unidades(self):
        cfg = ConfiguracaoLogin.get_para(self.user)
        cfg.unidade_preferida = '2191_HOSP EST JOAO PAULO II'
        cfg.save()
        self._sessao()
        r = self.client.get(reverse('siresp_app:producao_status_login')).json()
        self.assertEqual(r['estado'], 'aguardando_unidade')
        self.assertFalse(r['logado'])
        self.assertEqual([u['valor'] for u in r['unidades']], [u['valor'] for u in UNIDADES])
        self.assertEqual(r['sugerida'], '2206_AME SAO JOSE DO RIO PRETO')
        self.assertEqual(r['preferida'], '2191_HOSP EST JOAO PAULO II')

    def test_captcha_enviado_pausa_na_unidade_e_repassa_a_preferida(self):
        cfg = ConfiguracaoLogin.get_para(self.user)
        cfg.unidade_preferida = '2191_HOSP EST JOAO PAULO II'
        cfg.cpf_ultimos = '123'
        cfg.save()
        sc = self._sessao(aguardando=False)
        r = scraper_service.enviar_captcha_e_continuar(self.user, 'abc')
        self.assertTrue(r['ok'])
        self.assertTrue(_esperar(lambda: SessaoSiresp.objects.filter(
            usuario_web=self.user, mensagem='Selecione a unidade.').exists()))
        self.assertEqual(sc.recebeu_preferida, '2191_HOSP EST JOAO PAULO II')
        self.assertEqual(SessaoSiresp.objects.get(usuario_web=self.user).status, 'aguardando')

    def test_escolher_unidade_conclui_o_login(self):
        sc = self._sessao()
        r = self.client.post(reverse('siresp_app:producao_escolher_unidade'),
                             data={'valor': UNIDADES[1]['valor']},
                             content_type='application/json').json()
        self.assertTrue(r['ok'], r)
        self.assertEqual(sc.escolhida, UNIDADES[1]['valor'])
        self.assertTrue(_esperar(lambda: sc.logado))
        self.assertTrue(_esperar(lambda: SessaoSiresp.objects.filter(
            usuario_web=self.user, status='logado').exists()))
        st = self.client.get(reverse('siresp_app:producao_status_login')).json()
        self.assertEqual((st['estado'], st['logado']), ('logado', True))

    def test_lembrar_salva_a_preferencia_e_fica_auditado(self):
        self._sessao()
        self.client.post(reverse('siresp_app:producao_escolher_unidade'),
                         data={'valor': UNIDADES[2]['valor'], 'lembrar': True},
                         content_type='application/json')
        self.assertEqual(ConfiguracaoLogin.get_para(self.user).unidade_preferida, UNIDADES[2]['valor'])
        self.assertTrue(LogAuditoria.objects.filter(acao='UNIDADE_SIRESP', usuario_nome='medico').exists())

    def test_sem_lembrar_nao_grava_preferencia(self):
        self._sessao()
        self.client.post(reverse('siresp_app:producao_escolher_unidade'),
                         data={'valor': UNIDADES[0]['valor'], 'lembrar': False},
                         content_type='application/json')
        self.assertEqual(ConfiguracaoLogin.get_para(self.user).unidade_preferida, '')

    def test_esquecer_unidade(self):
        cfg = ConfiguracaoLogin.get_para(self.user)
        cfg.unidade_preferida = UNIDADES[0]['valor']
        cfg.save()
        r = self.client.post(reverse('siresp_app:producao_esquecer_unidade'))
        self.assertEqual(r.status_code, 302)
        cfg.refresh_from_db()
        self.assertEqual(cfg.unidade_preferida, '')
        self.assertEqual(self.client.get(reverse('siresp_app:producao_esquecer_unidade')).status_code, 405)

    def test_casos_de_erro_nao_quebram(self):
        url = reverse('siresp_app:producao_escolher_unidade')
        post = lambda corpo, **kw: self.client.post(url, data=corpo, content_type='application/json', **kw)
        # sem sessão
        self.assertFalse(post({'valor': 'x'}).json()['ok'])
        # sessão sem escolha pendente
        self._sessao(aguardando=False)
        self.assertFalse(post({'valor': 'x'}).json()['ok'])
        # valor vazio e payload inválido
        self._sessao()
        self.assertFalse(post({'valor': ''}).json()['ok'])
        self.assertFalse(self.client.post(url, data='lixo', content_type='application/json').json()['ok'])
        # SIRESP recusa a unidade: a pausa continua e nada é lembrado
        sc = self._sessao(recusa=True)
        r = post({'valor': UNIDADES[0]['valor'], 'lembrar': True}).json()
        self.assertFalse(r['ok'])
        self.assertTrue(sc.aguardando_unidade)
        self.assertEqual(ConfiguracaoLogin.get_para(self.user).unidade_preferida, '')

    def test_digitos_rejeitados_apos_a_unidade_viram_erro(self):
        self._sessao(resultado_final={'ok': False, 'captcha_novo': False,
                                      'mensagem': 'Dígitos de segurança rejeitados: x'})
        self.client.post(reverse('siresp_app:producao_escolher_unidade'),
                         data={'valor': UNIDADES[0]['valor']}, content_type='application/json')
        self.assertTrue(_esperar(lambda: SessaoSiresp.objects.filter(
            usuario_web=self.user, status='erro').exists()))
        self.assertIn('Dígitos', SessaoSiresp.objects.get(usuario_web=self.user).mensagem)

    def test_tela_do_siresp_capturada_aparece_no_status_e_no_endpoint(self):
        sc = self._sessao(aguardando=False)
        url_status = reverse('siresp_app:producao_status_login')
        url_tela = reverse('siresp_app:producao_tela_siresp')
        # sem captura: nada de tela_id e o endpoint avisa
        self.assertNotIn('tela_id', self.client.get(url_status).json())
        self.assertFalse(self.client.get(url_tela).json()['ok'])
        # o scraper capturou o que o SIRESP mostrou
        sc.ultima_tela = {'imagem_b64': 'data:image/png;base64,AAAA', 'texto': 'Acesso bloqueado',
                          'url': 'https://siresp/x', 'titulo': 'SIRESP', 'alerta': 'Usuário inativo'}
        sc.ultima_tela_id = 3
        st = self.client.get(url_status).json()
        self.assertEqual(st['tela_id'], 3)
        self.assertNotIn('imagem_b64', str(st))               # a imagem pesada não vai em toda consulta
        r = self.client.get(url_tela).json()
        self.assertTrue(r['ok'])
        self.assertEqual(r['tela']['texto'], 'Acesso bloqueado')
        self.assertEqual(r['tela']['alerta'], 'Usuário inativo')
        # login concluído: o scraper limpa a tela e o app esconde o painel
        sc.ultima_tela = None
        self.assertNotIn('tela_id', self.client.get(url_status).json())

    def test_exige_login_no_sistema(self):
        from django.test import Client
        r = Client().post(reverse('siresp_app:producao_escolher_unidade'),
                          data={'valor': 'x'}, content_type='application/json')
        self.assertEqual(r.status_code, 302)


# ---------------------------------------------------------------------------
# Tela (navegador real). Rode com: RUN_BROWSER_TESTS=1 python manage.py test siresp_app.tests_unidade
# ---------------------------------------------------------------------------
class _ServidorUmaPorVez(LiveServerThread):
    """
    Servidor de teste que atende UMA requisição por vez. O padrão do Django usa uma thread por
    requisição, todas compartilhando a mesma conexão do SQLite em memória; como a tela faz várias
    consultas em paralelo (status do login, do lote, estáticos), isso gera erros aleatórios de banco
    que só existem no ambiente de teste.
    """
    class server_class(WSGIServer):
        def __init__(self, *args, connections_override=None, **kwargs):
            super().__init__(*args, **kwargs)      # sem threads por requisição: uma de cada vez


@skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1', 'defina RUN_BROWSER_TESTS=1 para testar no Chrome')
class UnidadeTelaTests(LiveServerTestCase):
    server_thread_class = _ServidorUmaPorVez
    # Conta as requisições em andamento no servidor de teste: ao fim de cada teste só limpamos o
    # banco quando o servidor está ocioso (SQLite em memória não aceita duas threads ao mesmo tempo).
    _em_andamento = 0
    _trava = threading.Lock()

    @classmethod
    def _inicio(cls, **kw):
        with cls._trava:
            cls._em_andamento += 1

    @classmethod
    def _fim(cls, **kw):
        with cls._trava:
            cls._em_andamento -= 1

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        request_started.connect(cls._inicio)
        request_finished.connect(cls._fim)
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        o = Options()
        o.add_argument('--headless=new')
        o.add_argument('--window-size=1400,1000')
        cls.browser = webdriver.Chrome(options=o)

    @classmethod
    def tearDownClass(cls):
        request_started.disconnect(cls._inicio)
        request_finished.disconnect(cls._fim)
        cls.browser.quit()
        super().tearDownClass()

    def setUp(self):
        from selenium.webdriver.support.ui import WebDriverWait
        self.WebDriverWait = WebDriverWait
        self.user = User.objects.create_user('medico', password='senha123')
        scraper_service._SCRAPERS.clear()
        self.addCleanup(scraper_service._SCRAPERS.clear)
        b = self.browser
        self.addCleanup(self._parar_navegador)
        b.get(self.live_server_url + '/login/')
        self.client.force_login(self.user)
        b.add_cookie({'name': 'sessionid', 'value': self.client.cookies['sessionid'].value, 'path': '/'})

    def _parar_navegador(self):
        # A tela consulta o servidor a cada 1s: para o polling e espera o servidor ficar ocioso
        # antes de o banco de teste ser limpo.
        try:
            self.browser.get('about:blank')
        except Exception:
            pass
        fim = time.time() + 10
        ociosos = 0
        while time.time() < fim and ociosos < 4:          # 4 leituras seguidas com 0 em andamento
            ociosos = ociosos + 1 if type(self)._em_andamento <= 0 else 0
            time.sleep(0.1)

    def _modal_visivel(self):
        from selenium.webdriver.common.by import By
        return self.WebDriverWait(self.browser, 10).until(
            lambda d: next((m for m in d.find_elements(By.ID, 'modalUnidade') if m.is_displayed()), None))

    def test_seletor_aparece_sozinho_e_clicar_na_unidade_conclui_o_login(self):
        from selenium.webdriver.common.by import By
        sc = ScraperFalso()
        scraper_service._SCRAPERS[self.user.id] = sc
        b = self.browser
        b.get(self.live_server_url + reverse('siresp_app:producao_home'))

        modal = self._modal_visivel()                              # aparece sem ninguém pedir, como o CAPTCHA
        itens = modal.find_elements(By.CSS_SELECTOR, '#unidade-lista button')
        self.assertEqual([i.find_element(By.TAG_NAME, 'span').text for i in itens],
                         [u['texto'] for u in UNIDADES])
        self.assertIn('sugerida', itens[0].text)                   # a unidade padrão vem destacada, não escolhida
        self.assertEqual(sc.chamadas_escolher, 0)                  # nada é enviado antes do clique
        self.assertEqual(len(modal.find_elements(By.ID, 'btn-unidade-ok')), 0)   # sem botão "Continuar"
        self.assertEqual(b.find_element(By.ID, 'status-text').text, 'Escolha a unidade')

        b.find_element(By.ID, 'unidade-lembrar').click()
        itens[2].click()                                           # um clique: confirma e segue o login

        self.WebDriverWait(b, 10).until(lambda d: 'Logado' in d.find_element(By.ID, 'status-text').text)
        self.assertEqual(sc.escolhida, UNIDADES[2]['valor'])
        self.assertFalse(b.find_element(By.ID, 'modalUnidade').is_displayed())
        self.assertEqual(ConfiguracaoLogin.get_para(self.user).unidade_preferida, UNIDADES[2]['valor'])
        time.sleep(2.5)                                            # o seletor não reabre depois de logado
        self.assertFalse(b.find_element(By.ID, 'modalUnidade').is_displayed())

    def test_clique_duplo_envia_uma_vez_so(self):
        from selenium.webdriver.common.by import By
        sc = ScraperFalso()
        scraper_service._SCRAPERS[self.user.id] = sc
        b = self.browser
        b.get(self.live_server_url + reverse('siresp_app:producao_home'))
        item = self._modal_visivel().find_elements(By.CSS_SELECTOR, '#unidade-lista button')[1]
        b.execute_script('arguments[0].click(); arguments[0].click();', item)
        self.WebDriverWait(b, 10).until(lambda d: 'Logado' in d.find_element(By.ID, 'status-text').text)
        self.assertEqual(sc.chamadas_escolher, 1)
        self.assertEqual(sc.escolhida, UNIDADES[1]['valor'])

    def test_unidade_recusada_mostra_erro_e_permite_tentar_de_novo(self):
        from selenium.webdriver.common.by import By
        sc = ScraperFalso(recusa=True)
        scraper_service._SCRAPERS[self.user.id] = sc
        b = self.browser
        b.get(self.live_server_url + reverse('siresp_app:producao_home'))
        itens = self._modal_visivel().find_elements(By.CSS_SELECTOR, '#unidade-lista button')
        itens[0].click()
        self.WebDriverWait(b, 10).until(lambda d: d.find_element(By.ID, 'unidade-erro').is_displayed())
        self.assertIn('Unidade inválida', b.find_element(By.ID, 'unidade-erro').text)
        self.assertTrue(b.find_element(By.ID, 'modalUnidade').is_displayed())     # continua aberto
        self.assertTrue(all(i.is_enabled() for i in
                            b.find_elements(By.CSS_SELECTOR, '#unidade-lista button')))   # pode clicar de novo
        self.assertEqual(ConfiguracaoLogin.get_para(self.user).unidade_preferida, '')

    def test_nome_da_unidade_nunca_vira_html(self):
        from selenium.webdriver.common.by import By
        sc = ScraperFalso()
        sc.unidades_disponiveis = [{'valor': 'a<b>', 'texto': '<img src=x onerror=alert(1)> UNIDADE A'},
                                   {'valor': 'b', 'texto': 'Unidade B'}]
        scraper_service._SCRAPERS[self.user.id] = sc
        b = self.browser
        b.get(self.live_server_url + reverse('siresp_app:producao_home'))
        self._modal_visivel()
        lista = b.find_element(By.ID, 'unidade-lista')
        self.assertEqual(lista.find_elements(By.TAG_NAME, 'img'), [])
        self.assertIn('<img src=x', lista.text)                    # aparece como texto puro
