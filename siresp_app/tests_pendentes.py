"""Busca de pendentes para extração em lote, por período."""
import time
from unittest import mock

from django.contrib.auth.models import User
from django.test import TransactionTestCase
from django.urls import reverse

from .models import Extracao, Profissional, SemProducao
from .services.profissionais_service import pendentes_extracao
from .tests import BaseTest
from .tests_util import AguardaThreads


def _ext(user, nome, ini, fim):
    return Extracao.objects.create(usuario_web=user, medico_nome=nome, data_ini=ini, data_fim=fim)


class PendentesPorPeriodoTests(BaseTest):
    def setUp(self):
        super().setUp()
        for n in ('ANA LIMA', 'BRUNO DIAS', 'DIOGO SOLO', 'ELISA NEVES'):
            Profissional.objects.create(nome=n, nome_norm=n)
        Profissional.objects.create(nome='FULANO INATIVO', nome_norm='FULANO INATIVO', ativo=False)
        _ext(self.user, 'ANA LIMA SOUZA', '01/08/2026', '31/08/2026')     # nome mais longo no SIRESP
        _ext(self.user, 'BRUNO DIAS', '01/08/2026', '15/08/2026')         # extração parcial
        SemProducao.objects.create(usuario_web=self.user, medico_nome='DIOGO SOLO',
                                   nome_norm='DIOGO SOLO', data_ini='01/08/2026', data_fim='31/08/2026')

    def test_so_quem_nao_tem_extracao_que_cubra_o_periodo(self):
        r = pendentes_extracao(self.user, '01/08/2026', '31/08/2026')
        self.assertEqual(r['nomes'], ['BRUNO DIAS', 'ELISA NEVES'])   # parcial e nunca extraído
        self.assertEqual((r['ja_extraidos'], r['sem_producao'], r['total']), (1, 1, 4))

    def test_periodo_menor_dentro_de_extracao_existente_conta_como_coberto(self):
        # 10 a 20/08: Ana (mês inteiro) cobre; Bruno só extraiu até 15/08 -> continua pendente
        r = pendentes_extracao(self.user, '10/08/2026', '20/08/2026')
        self.assertEqual(r['nomes'], ['BRUNO DIAS', 'ELISA NEVES'])
        # 05 a 12/08: agora a extração parcial do Bruno (01 a 15) também cobre
        r = pendentes_extracao(self.user, '05/08/2026', '12/08/2026')
        self.assertEqual(r['nomes'], ['ELISA NEVES'])
        self.assertEqual(r['ja_extraidos'], 2)

    def test_outro_periodo_todos_pendentes_e_inativo_fora(self):
        r = pendentes_extracao(self.user, '01/09/2026', '30/09/2026')
        self.assertEqual(sorted(r['nomes']), ['ANA LIMA', 'BRUNO DIAS', 'DIOGO SOLO', 'ELISA NEVES'])
        self.assertNotIn('FULANO INATIVO', r['nomes'])

    def test_extracao_de_outro_usuario_nao_conta(self):
        outro = User.objects.create_user('outro', password='x')
        _ext(outro, 'ELISA NEVES', '01/08/2026', '31/08/2026')
        self.assertIn('ELISA NEVES', pendentes_extracao(self.user, '01/08/2026', '31/08/2026')['nomes'])

    def test_periodo_invalido(self):
        for ini, fim in (('', ''), ('01/08/2026', ''), ('x', 'y'), ('31/08/2026', '01/08/2026')):
            with self.assertRaises(ValueError):
                pendentes_extracao(self.user, ini, fim)

    def test_endpoint_por_periodo(self):
        url = reverse('siresp_app:producao_lote_pendentes')
        r = self.client.get(url + '?data_ini=01/08/2026&data_fim=31/08/2026').json()
        self.assertTrue(r['ok'])
        self.assertEqual(r['nomes'], ['BRUNO DIAS', 'ELISA NEVES'])
        self.assertEqual(r['ja_extraidos'], 1)
        self.assertEqual(r['sem_producao'], 1)
        r = self.client.get(url + '?data_ini=01/08/2026&data_fim=xx').json()
        self.assertFalse(r['ok'])

    def test_modo_mes_nao_inclui_quem_ja_foi_extraido_sem_repasse(self):
        """O bug original: 'extraído, sem repasse' aparecia como pendente."""
        r = self.client.get(reverse('siresp_app:producao_lote_pendentes') + '?mes=8&ano=2026').json()
        self.assertNotIn('ANA LIMA', r['nomes'])
        self.assertNotIn('BRUNO DIAS', r['nomes'])
        self.assertIn('ELISA NEVES', r['nomes'])


class LoteGravaSemProducaoTests(AguardaThreads, TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user('medico', password='senha123')
        self.client.login(username='medico', password='senha123')
        for n in ('ANA LIMA', 'BRUNO DIAS'):
            Profissional.objects.create(nome=n, nome_norm=n)

    def _rodar_lote(self, nomes, dados_por_medico):
        sc = 'siresp_app.services.lote_service.scraper_service'
        vp = 'siresp_app.views.producao.scraper_service'
        buscas = {n: [{'nome': n, 'crm': '1', 'codigo': '1'}] for n in nomes}
        with mock.patch(sc + '.listar_medicos', side_effect=lambda u, n, o: buscas[n]), \
                mock.patch(sc + '.extrair_producao',
                           side_effect=lambda u, m, i, f: dados_por_medico[m['nome']]), \
                mock.patch(sc + '.sessao_ativa', return_value=True), \
                mock.patch(vp + '.sessao_ativa', return_value=True), \
                mock.patch(vp + '.status_login', return_value={'estado': 'logado', 'logado': True}):
            r = self.client.post(reverse('siresp_app:producao_lote_iniciar'), data={
                'nomes': nomes, 'data_ini': '01/08/2026', 'data_fim': '31/08/2026'},
                content_type='application/json').json()
            self.assertTrue(r['ok'], r)
            for _ in range(60):
                st = self.client.get(reverse('siresp_app:producao_lote_status')).json()
                if not st['rodando']:
                    return {i['nome']: i['status'] for i in st['itens']}
                time.sleep(0.1)
        self.fail('lote não terminou')

    def test_sem_producao_nao_volta_a_ser_pendente(self):
        linha = [{'Especialidade': 'CARDIOLOGIA', 'Oferta_N': '10'}]
        status = self._rodar_lote(['ANA LIMA', 'BRUNO DIAS'], {'ANA LIMA': linha, 'BRUNO DIAS': []})
        self.assertEqual(status, {'ANA LIMA': 'concluido', 'BRUNO DIAS': 'sem_dados'})
        self.assertEqual(SemProducao.objects.get().nome_norm, 'BRUNO DIAS')

        url = reverse('siresp_app:producao_lote_pendentes') + '?data_ini=01/08/2026&data_fim=31/08/2026'
        r = self.client.get(url).json()
        self.assertEqual(r['nomes'], [])                      # ninguém pendente: Ana extraída, Bruno sem produção
        self.assertEqual((r['ja_extraidos'], r['sem_producao']), (1, 1))

        # se depois o Bruno passar a ter produção, o registro de "sem produção" some
        status = self._rodar_lote(['BRUNO DIAS'], {'BRUNO DIAS': linha})
        self.assertEqual(status, {'BRUNO DIAS': 'concluido'})
        self.assertEqual(SemProducao.objects.count(), 0)
