"""
Teste de ponta a ponta (navegador real): percorre o sistema como uma pessoa usaria.

Só o SIRESP é simulado (login/busca/extração), porque não dá para automatizar o site real.
Rode com:  RUN_BROWSER_TESTS=1 python manage.py test siresp_app.tests_e2e
"""
import os
import shutil
import tempfile
import time
import zipfile
from unittest import mock, skipUnless

from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

from .models import Extracao, LogAuditoria, Repasse
from .services import scraper_service
from .tests_unidade import ScraperFalso, _ServidorUmaPorVez
from .tests_unidade_logada import AME

NOMES = ['ANA LIMA SOUZA', 'BRUNO DIAS FILHO', 'CARLA MELO']
LINHAS_SIRESP = [
    {'Especialidade': 'CARDIOLOGIA', 'Oferta_N': '60', 'Atend_Total_N': '55', 'Agend_Total_N': '58'},
    {'Especialidade': 'CLINICA GERAL', 'Oferta_N': '40', 'Atend_Total_N': '30', 'Agend_Total_N': '35'},
]


@skipUnless(os.environ.get('RUN_BROWSER_TESTS') == '1', 'defina RUN_BROWSER_TESTS=1 para rodar no Chrome')
class SistemaInteiroNoNavegador(StaticLiveServerTestCase):
    server_thread_class = _ServidorUmaPorVez

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        cls.downloads = tempfile.mkdtemp(prefix='e2e_dl_')
        o = Options()
        o.add_argument('--headless=new')
        o.add_argument('--window-size=1500,1100')
        o.add_experimental_option('prefs', {
            'download.default_directory': cls.downloads,
            'download.prompt_for_download': False,
            'safebrowsing.enabled': True,
            'profile.default_content_setting_values.automatic_downloads': 1,   # vários downloads
            'plugins.always_open_pdf_externally': True,                         # PDF vira arquivo
        })
        cls.b = webdriver.Chrome(options=o)

    @classmethod
    def tearDownClass(cls):
        cls.b.quit()
        shutil.rmtree(cls.downloads, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from selenium.webdriver.support.ui import WebDriverWait
        self.WebDriverWait = WebDriverWait
        self.admin = User.objects.create_user('admin_e2e', password='senha123', is_staff=True, is_superuser=True)
        self.comum = User.objects.create_user('comum_e2e', password='senha123')
        scraper_service._SCRAPERS.clear()
        self.addCleanup(scraper_service._SCRAPERS.clear)
        self.addCleanup(self._parar_navegador)

    def _parar_navegador(self):
        try:
            self.b.get('about:blank')
        except Exception:
            pass
        time.sleep(0.8)

    # ------------------------------------------------------------------ utilidades
    def ir(self, rota, args=None, qs=''):
        self.b.get(self.live_server_url + reverse(f'siresp_app:{rota}', args=args) + qs)

    def esperar(self, cond, segundos=12, msg=''):
        from selenium.common.exceptions import (
            NoSuchElementException, StaleElementReferenceException, TimeoutException)
        try:
            # a página troca durante a espera (navegação): elemento "velho" não é erro
            return self.WebDriverWait(
                self.b, segundos,
                ignored_exceptions=(NoSuchElementException, StaleElementReferenceException),
            ).until(cond, msg)
        except TimeoutException:
            destino = os.environ.get('E2E_DEBUG_DIR', self.downloads)
            try:
                self.b.save_screenshot(os.path.join(destino, 'e2e_falha.png'))
            except Exception:
                pass
            print('[E2E] tempo esgotado em', self.b.current_url)
            print('[E2E] texto da página:', ' | '.join(self.corpo()[:900].splitlines()))
            raise

    def css(self, seletor):
        from selenium.webdriver.common.by import By
        return self.b.find_element(By.CSS_SELECTOR, seletor)

    def todos(self, seletor):
        from selenium.webdriver.common.by import By
        return self.b.find_elements(By.CSS_SELECTOR, seletor)

    def clicar(self, el):
        self.b.execute_script('arguments[0].scrollIntoView({block: "center"});', el)
        self.b.execute_script('arguments[0].click();', el)

    def botao(self, texto):
        from selenium.webdriver.common.by import By
        xp = f'//button[contains(normalize-space(.), "{texto}")] | //a[contains(normalize-space(.), "{texto}")] | //input[@value="{texto}"]'
        return self.b.find_element(By.XPATH, xp)

    def botao_opcional(self, texto):
        from selenium.webdriver.common.by import By
        return self.b.find_elements(By.XPATH, f'//button[contains(normalize-space(.), "{texto}")]')

    def corpo(self):
        from selenium.webdriver.common.by import By
        return self.b.find_element(By.TAG_NAME, 'body').text

    def titulo(self):
        return self.css('h1.page-title').text

    def preencher(self, seletor, valor):
        el = self.css(seletor)
        el.clear()
        el.send_keys(valor)

    def login(self, usuario):
        self.b.get(self.live_server_url + reverse('siresp_app:login'))
        self.preencher('input[name=usuario]', usuario)
        self.preencher('input[name=senha]', 'senha123')
        self.clicar(self.css('button[type=submit]'))
        self.esperar(lambda d: 'login' not in d.current_url)

    def sair(self):
        self.clicar(self.botao('Sair'))
        self.esperar(lambda d: 'login' in d.current_url)

    def arquivo_baixado(self, sufixo, segundos=15):
        fim = time.time() + segundos
        while time.time() < fim:
            achados = [f for f in os.listdir(self.downloads) if f.endswith(sufixo)]
            if achados and not any(f.endswith('.crdownload') for f in os.listdir(self.downloads)):
                return os.path.join(self.downloads, achados[0])
            time.sleep(0.2)
        self.fail(f'nenhum arquivo {sufixo} baixado: {os.listdir(self.downloads)}')

    def limpar_downloads(self):
        for f in os.listdir(self.downloads):
            os.remove(os.path.join(self.downloads, f))

    def sem_erro_de_servidor(self):
        corpo = self.corpo()
        self.assertNotIn('Server Error', corpo)
        self.assertNotIn('Traceback', corpo)
        self.assertNotIn('TemplateSyntaxError', corpo)

    # ------------------------------------------------------------------ o roteiro completo
    def test_roteiro_completo(self):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import Select

        # ---------- 1. login e painel
        self.login('admin_e2e')
        self.assertIn('Painel', self.titulo())
        for texto in ('1. Produção', '2. Repasse em Lote', '3. Relatórios', 'Cadastros', 'Administração'):
            self.assertIn(texto, self.css('nav').text)
        self.assertIn('admin', self.css('nav').text)

        # ---------- 2. importar planilha de agendas
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(['PROFISSIONAL', 'ESPECIALIDADE', 'INTERVALO ENTRE AS CONSULTAS'])
        for linha in (('ANA LIMA SOUZA', 'CARDIOLOGIA', 30), ('ANA LIMA SOUZA', 'CLINICA GERAL', 15),
                      ('BRUNO DIAS FILHO', 'CARDIOLOGIA', 30), ('BRUNO DIAS FILHO', 'CLINICA GERAL', 15),
                      ('CARLA MELO', 'CARDIOLOGIA', 20), ('CARLA MELO', 'CLINICA GERAL', 15)):
            ws.append(list(linha))
        planilha = os.path.join(self.downloads, 'agendas.xlsx')
        wb.save(planilha)
        self.ir('config_importar')
        self.css('input[name=arquivo]').send_keys(planilha)
        self.clicar(self.css('form[enctype="multipart/form-data"] button[type=submit]'))
        self.esperar(lambda d: 'Regras de Minutos' in d.find_element(By.CSS_SELECTOR, 'h1').text)
        self.assertIn('Importação concluída', self.corpo())
        self.assertEqual(len(self.todos('table tbody tr')), 6)

        # ---------- 3. grupos de valores (Padrão + um por especialidade)
        for nome, base, bonus, esp in (('Padrão', '100', '40', None), ('Cardiologia E2E', '200', '50', 'CARDIOLOGIA')):
            self.ir('config_novo')
            self.preencher('input[name=nome]', nome)
            self.preencher('input[name=valor_base]', base)
            self.preencher('input[name=bonus]', bonus)
            if esp:
                self.clicar(self.css(f'input[name=especialidades][value="{esp}"]'))
            self.clicar(self.botao('Salvar'))
            self.esperar(lambda d: 'Grupos de Valores' in d.find_element(By.CSS_SELECTOR, 'h1').text)
        corpo = self.corpo()
        self.assertIn('Cardiologia E2E', corpo)
        self.assertIn('R$ 250,00', corpo)                       # 200 + 50 de bônus
        self.assertIn('Grupo salvo com sucesso', corpo)

        # ---------- 4. equipe médica
        self.ir('equipes_nova')
        self.preencher('input[name=nome]', 'Clínica E2E Ltda')
        for nome in ('ANA LIMA SOUZA', 'BRUNO DIAS FILHO'):
            label = self.b.find_element(By.XPATH, f'//label[contains(normalize-space(.), "{nome}")]')
            self.clicar(self.b.find_element(By.ID, label.get_attribute('for')))
        self.clicar(self.botao('Salvar equipe'))
        self.esperar(lambda d: 'Equipes Médicas' in d.find_element(By.CSS_SELECTOR, 'h1').text)
        self.assertIn('Clínica E2E Ltda', self.corpo())
        self.assertIn('2 profissional', self.corpo())

        # ---------- 5. produção (SIRESP simulado): login visível + extração em lote
        sc = ScraperFalso(aguardando=False)
        sc.logado = True
        sc.unidade_atual = AME
        scraper_service._SCRAPERS[self.admin.id] = sc
        busca = {n: [{'nome': n, 'crm': '1', 'codigo': str(i)}] for i, n in enumerate(NOMES)}
        alvo = 'siresp_app.services.lote_service.scraper_service'
        with mock.patch(alvo + '.listar_medicos', side_effect=lambda u, n, o: busca.get(n, [])), \
                mock.patch(alvo + '.extrair_producao', return_value=LINHAS_SIRESP):
            self.ir('producao_home')
            self.esperar(lambda d: 'Logado no SIRESP' in d.find_element(By.ID, 'status-text').text)
            self.assertIn('AME SAO JOSE DO RIO PRETO', self.css('#status-unidade').text)   # unidade logada
            self.css('#data-ini').send_keys('01082026')
            self.css('#data-fim').send_keys('31082026')
            self.assertEqual(self.css('#data-ini').get_attribute('value'), '01/08/2026')    # máscara de data
            self.css('#lote-nomes').send_keys('\n'.join(NOMES))
            self.esperar(lambda d: d.find_element(By.ID, 'btn-lote').is_enabled())
            self.clicar(self.css('#btn-lote'))
            self.esperar(lambda d: 'finalizado' in d.find_element(By.ID, 'lote-resumo').text, 25)
            linhas = self.todos('#lote-itens tr')
            self.assertEqual(len(linhas), 3)
            self.assertTrue(all('Concluído' in tr.text for tr in linhas), [tr.text for tr in linhas])
        self.assertEqual(Extracao.objects.filter(unidade_nome='AME SAO JOSE DO RIO PRETO').count(), 3)
        self.ir('producao_historico')
        self.assertIn('AME SAO JOSE DO RIO PRETO', self.corpo())
        self.assertEqual(len(self.todos('tbody tr')), 3)

        # ---------- 6. repasse em lote: gerar -> editar ao vivo -> salvar -> finalizar
        self.ir('repasse_lote', qs='?mes=8&ano=2026')
        self.assertEqual(len(self.todos('input[name=extracao_ids]')), 3)
        self.clicar(self.botao('Gerar repasses selecionados'))
        self.esperar(lambda d: 'Relatório e Edição do Lote' in d.find_element(By.CSS_SELECTOR, 'h1').text)
        self.sem_erro_de_servidor()
        self.assertIn('AME SAO JOSE DO RIO PRETO', self.css('.dica-neutra').text)         # relatório em nome da unidade
        self.assertEqual(len(self.todos('tr.linha')), 6)
        self.assertFalse(self.css('#btn-salvar').is_enabled())

        # ---------- 6b. apagar os repasses em lote e gerar de novo
        self.ir('repasse_lote', qs='?mes=8&ano=2026')
        self.clicar(self.botao('Rascunhos ('))                                         # marca os 3 rascunhos
        self.assertEqual(len(self.todos('.chk:checked')), 3)
        self.clicar(self.botao('Apagar repasses selecionados'))
        self.assertIn('Os ajustes feitos neles serão perdidos', self.b.switch_to.alert.text)
        self.b.switch_to.alert.accept()
        self.esperar(lambda d: '3 repasse(s) apagado(s)' in d.find_element(By.TAG_NAME, 'body').text)
        self.assertEqual(Repasse.objects.count(), 0)
        self.assertEqual(Extracao.objects.count(), 3)                                   # extrações continuam
        self.assertEqual(len(self.todos('.st-pendente')), 3)                            # voltaram a "Sem repasse"
        self.assertEqual(len(self.botao_opcional('Apagar repasses selecionados')), 0)   # nada mais a apagar
        self.clicar(self.botao('Gerar repasses selecionados'))
        self.esperar(lambda d: 'Relatório e Edição do Lote' in d.find_element(By.CSS_SELECTOR, 'h1').text)
        self.assertEqual(len(self.todos('tr.linha')), 6)

        total_antes = self.css('#tot-valor').text
        campo = self.todos('.f-valor_base')[0]
        campo.clear()
        campo.send_keys('300')
        self.assertNotEqual(self.css('#tot-valor').text, total_antes)                  # recalculou na hora
        self.assertTrue(self.css('#btn-salvar').is_enabled())
        self.assertIn('table-warning', self.todos('tr.linha')[0].get_attribute('class'))
        total_editado = self.css('#tot-valor').text
        self.clicar(self.css('#btn-salvar'))
        self.esperar(lambda d: 'salva' in d.find_element(By.ID, 'msg-salvar').text)
        self.assertFalse(self.css('#btn-salvar').is_enabled())
        self.b.refresh()                                                               # persistiu
        self.assertEqual(self.css('#tot-valor').text, total_editado)
        self.assertEqual(self.todos('.f-valor_base')[0].get_attribute('value'), '300.00')

        # exportar antes de finalizar está bloqueado
        self.assertFalse(self.botao('Exportar Excel').is_enabled())
        self.assertFalse(self.botao('Exportar PDF').is_enabled())
        # equipe e resumo por faturamento
        corpo = self.corpo()
        self.assertIn('Equipe Clínica E2E Ltda', corpo)
        self.assertIn('Resumo por faturamento', corpo)

        # finalizar com competência (mês anterior ao atual, já sugerido)
        self.assertTrue(self.css('input[name=competencia]').get_attribute('value'))
        self.clicar(self.botao('Finalizar e liberar Excel/PDF'))
        self.b.switch_to.alert.accept()
        self.esperar(lambda d: 'Excel liberado' in d.find_element(By.CSS_SELECTOR, '.alert-success').text)
        self.assertEqual(Repasse.objects.filter(status='finalizado').count(), 3)
        self.assertTrue(self.botao('Exportar Excel').is_enabled())

        # Excel e PDF do lote
        self.limpar_downloads()
        self.clicar(self.botao('Exportar Excel'))
        xlsx = self.arquivo_baixado('.xlsx')
        self.assertTrue(zipfile.is_zipfile(xlsx))
        self.limpar_downloads()
        self.clicar(self.botao('Exportar PDF'))
        pdf = self.arquivo_baixado('.pdf')
        self.assertEqual(open(pdf, 'rb').read(4), b'%PDF')

        # ---------- 7. relatórios: cores, filtros, Excel/PDF consolidados e reabertura (admin)
        self.ir('relatorios_home')
        self.assertEqual(len(self.todos('tr.table-success')), 3)
        self.assertEqual(len(self.todos('tr.table-warning')), 0)
        Select(self.css('select[name=unidade]')).select_by_visible_text('AME SAO JOSE DO RIO PRETO')
        self.esperar(lambda d: 'unidade=' in d.current_url)
        self.assertEqual(len(self.todos('tr.table-success')), 3)
        self.clicar(self.botao('Marcar todos'))
        self.limpar_downloads()
        self.clicar(self.botao('Gerar Excel'))
        self.assertTrue(zipfile.is_zipfile(self.arquivo_baixado('.xlsx')))
        self.limpar_downloads()
        self.ir('relatorios_home')
        self.clicar(self.botao('Marcar todos'))
        self.clicar(self.botao('Gerar PDF'))
        self.assertEqual(open(self.arquivo_baixado('.pdf'), 'rb').read(4), b'%PDF')

        self.ir('relatorios_home')
        self.clicar(self.todos('.chk-repasse')[0])
        self.clicar(self.botao('Reabrir selecionados'))
        self.esperar(lambda d: d.find_element(By.ID, 'modal-motivo').is_displayed())
        self.clicar(self.css('#modalMotivo .btn-warning'))                              # sem motivo: não envia
        self.assertTrue(self.css('#modal-erro').is_displayed())
        self.css('#modal-motivo').send_keys('Conferência do valor base')
        self.clicar(self.css('#modalMotivo .btn-warning'))
        self.esperar(lambda d: len(d.find_elements(By.CSS_SELECTOR, 'tr.table-warning')) == 1)
        self.assertEqual(Repasse.objects.filter(status='rascunho').count(), 1)

        # ---------- 8. profissionais: ações em massa
        self.ir('profissionais_lista', qs='?mes=8&ano=2026')
        marcados = self.todos('.chk-prof')
        self.assertEqual(len(marcados), 3)
        self.clicar(marcados[0])
        self.clicar(marcados[1])
        Select(self.css('#acao')).select_by_value('desativar')
        self.clicar(self.botao('Aplicar'))
        self.esperar(lambda d: len(d.find_elements(By.CSS_SELECTOR, '.chk-prof')) == 1)
        self.assertIn('Desativados (2)', self.corpo())
        for chk in self.todos('.chk-inativo'):
            self.clicar(chk)
        self.clicar(self.botao('Reativar marcados'))
        self.esperar(lambda d: len(d.find_elements(By.CSS_SELECTOR, '.chk-prof')) == 3)
        Select(self.css('#acao')).select_by_value('sem_equipe')
        self.clicar(self.todos('.chk-prof')[0])
        self.clicar(self.botao('Aplicar'))
        self.esperar(lambda d: 'retirados da equipe' in d.find_element(By.TAG_NAME, 'body').text)

        # ---------- 9. auditoria: tudo o que foi feito está registrado
        self.ir('auditoria_lista')
        self.sem_erro_de_servidor()
        corpo = self.corpo()
        for esperado in ('Planilha de agendas importada', 'Grupo de valores criado', 'Equipe criada',
                         'Extração criada', 'Repasse gerado', 'Repasse editado', 'Repasse finalizado',
                         'Repasse reaberto', 'Repasse apagado', 'Exportação', 'Base de profissionais alterada'):
            self.assertIn(esperado, corpo, esperado)
        Select(self.css('select[name=acao]')).select_by_value('REPASSE_REABERTO')
        self.clicar(self.botao('Filtrar'))
        self.esperar(lambda d: 'acao=REPASSE_REABERTO' in d.current_url)
        self.assertEqual(len(self.todos('.table-responsive > table > tbody > tr')), 1)   # só o registro de reabertura
        self.assertIn('Conferência do valor base', self.css('details').get_attribute('textContent'))

        # ---------- 10. todas as telas abrem sem erro (admin)
        for rota, args, texto in [
            ('home', None, 'Painel'), ('producao_home', None, 'Produção'), ('producao_historico', None, 'Histórico'),
            ('repasse_lote', None, 'Repasse em Lote'), ('relatorios_home', None, 'Relatórios'),
            ('profissionais_lista', None, 'Profissionais'), ('equipes_lista', None, 'Equipes'),
            ('config_lista', None, 'Grupos'), ('config_regras', None, 'Regras'),
            ('config_especialidades', None, 'Especialidades'), ('config_importar', None, 'Importar'),
            ('auditoria_lista', None, 'Auditoria'),
        ]:
            self.ir(rota, args)
            self.sem_erro_de_servidor()
            self.assertIn(texto, self.titulo(), rota)
        extracao = Extracao.objects.first()
        self.ir('producao_ver_extracao', [extracao.pk])
        self.assertIn('Resultado da Extração', self.titulo())
        self.ir('repasse_ver', [Repasse.objects.first().pk])
        self.assertIn('Repasse', self.titulo())
        self.sem_erro_de_servidor()

        # ---------- 11. usuário comum: vê tudo, mas não altera
        self.sair()
        self.login('comum_e2e')
        self.assertIn('usuário', self.css('nav').text)
        self.ir('config_lista')
        self.assertEqual(self.titulo(), 'Grupos de Valores')
        self.assertIn('Modo consulta', self.corpo())
        self.assertEqual(len(self.todos('a[href*="/config/novo/"]')), 0)
        self.assertEqual(len(self.todos('input[name=grupo_ids]')), 0)
        self.ir('config_novo')                                                          # direto pela URL: barrado
        self.assertIn('Acesso restrito a administradores', self.corpo())
        self.assertIn('Painel', self.titulo())
        self.ir('relatorios_home')
        self.assertEqual(len(self.todos('tr.table-success')), 2)                         # vê os repasses do admin
        self.assertEqual(len(self.todos('tr.table-warning')), 1)
        self.assertNotIn('Reabrir selecionados', self.corpo())
        self.ir('profissionais_lista', qs='?mes=8&ano=2026')
        self.assertEqual(len(self.todos('.chk-prof')), 0)                                # sem ações em massa
        self.assertIn('Clínica E2E Ltda', self.corpo())
        self.ir('auditoria_lista')                                                       # consulta liberada
        self.assertEqual(self.titulo(), 'Auditoria')
        rep_admin = Repasse.objects.filter(status='finalizado').first()
        self.ir('repasse_ver', [rep_admin.pk])
        self.assertIn('Modo consulta', self.corpo())
        self.assertEqual(len(self.todos('button[onclick="reabrirRepasse()"]')), 0)
        self.sair()
        self.assertTrue(LogAuditoria.objects.filter(acao='LOGIN', usuario_nome='comum_e2e').exists())
