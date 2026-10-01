"""Apagar repasses em lote (tela Repasse em Lote)."""
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from .models import Extracao, ItemProducao, ItemRepasse, LogAuditoria, RegraMinuto, Repasse
from .services import repasse_service
from .services.repasse_service import competencia_padrao
from .tests_papeis import PapeisBase


class ApagarRepassesEmLoteTests(PapeisBase):
    def setUp(self):
        super().setUp()
        self.exts = {}
        for nome in ('ANA LIMA', 'BRUNO DIAS', 'CARLA MELO'):
            RegraMinuto.objects.create(profissional_norm=nome, especialidade_norm='CARDIOLOGIA', minutos=[30])
            e = Extracao.objects.create(usuario_web=self.user, medico_nome=nome,
                                        data_ini='01/08/2026', data_fim='31/08/2026')
            ItemProducao.objects.create(extracao=e, especialidade='CARDIOLOGIA', ordem=0, dados={'Oferta_N': '40'})
            self.exts[nome] = e
        repasse_service.criar_repasses_lote(self.user, list(self.exts.values()))
        self.url = reverse('siresp_app:repasse_lote_apagar')

    def post(self, *nomes, cliente=None, **extra):
        dados = {'extracao_ids': [self.exts[n].pk for n in nomes], 'mes': 8, 'ano': 2026}
        dados.update(extra)
        return (cliente or self.client).post(self.url, dados)

    def test_apaga_so_os_marcados_e_mantem_as_extracoes(self):
        itens_antes = ItemRepasse.objects.count()
        r = self.post('ANA LIMA', 'BRUNO DIAS')
        self.assertRedirects(r, reverse('siresp_app:repasse_lote') + '?mes=8&ano=2026',
                             fetch_redirect_response=False)
        self.assertEqual(list(Repasse.objects.values_list('extracao__medico_nome', flat=True)), ['CARLA MELO'])
        self.assertLess(ItemRepasse.objects.count(), itens_antes)          # itens saíram junto
        self.assertEqual(Extracao.objects.count(), 3)                      # extrações continuam
        self.assertEqual(ItemProducao.objects.count(), 3)

    def test_fica_na_auditoria(self):
        self.post('ANA LIMA')
        log = LogAuditoria.objects.get(acao='REPASSE_APAGADO')
        self.assertEqual(log.usuario_nome, 'medico')
        self.assertEqual(log.profissional, 'ANA LIMA')
        self.assertIn('Repasse apagado em lote: ANA LIMA', log.descricao)
        self.assertIsNotNone(log.repasse_id)

    def test_pode_gerar_de_novo_depois_de_apagar(self):
        self.post('ANA LIMA', 'BRUNO DIAS', 'CARLA MELO')
        self.assertEqual(Repasse.objects.count(), 0)
        r = self.client.post(reverse('siresp_app:repasse_lote_gerar'),
                             {'extracao_ids': [e.pk for e in self.exts.values()]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Repasse.objects.count(), 3)

    def test_finalizado_nunca_e_apagado(self):
        rep = Repasse.objects.get(extracao=self.exts['ANA LIMA'])
        ok, _ = repasse_service.finalizar_repasse(rep, competencia_padrao())
        self.assertTrue(ok)
        r = self.client.post(self.url, {'extracao_ids': [self.exts['ANA LIMA'].pk, self.exts['BRUNO DIAS'].pk],
                                        'mes': 8, 'ano': 2026}, follow=True)
        self.assertTrue(Repasse.objects.filter(pk=rep.pk, status='finalizado').exists())   # protegido
        self.assertFalse(Repasse.objects.filter(extracao=self.exts['BRUNO DIAS']).exists())  # rascunho saiu
        self.assertContains(r, 'não foi(foram) apagado(s)')
        self.assertContains(r, 'ANA LIMA')
        self.assertEqual(LogAuditoria.objects.filter(acao='REPASSE_APAGADO').count(), 1)

    def test_nao_apaga_repasse_de_outro_usuario(self):
        # o admin (self.user) tenta apagar o rascunho do usuário comum
        e = Extracao.objects.create(usuario_web=self.comum, medico_nome='DIOGO SOLO',
                                    data_ini='01/08/2026', data_fim='31/08/2026')
        ItemProducao.objects.create(extracao=e, especialidade='CARDIOLOGIA', ordem=0, dados={'Oferta_N': '10'})
        repasse_service.criar_repasses_lote(self.comum, [e])
        self.client.post(self.url, {'extracao_ids': [e.pk], 'mes': 8, 'ano': 2026})
        self.assertTrue(Repasse.objects.filter(extracao=e).exists())
        self.assertFalse(LogAuditoria.objects.filter(acao='REPASSE_APAGADO').exists())

    def test_usuario_comum_apaga_os_proprios_rascunhos(self):
        e = Extracao.objects.create(usuario_web=self.comum, medico_nome='DIOGO SOLO',
                                    data_ini='01/08/2026', data_fim='31/08/2026')
        ItemProducao.objects.create(extracao=e, especialidade='CARDIOLOGIA', ordem=0, dados={'Oferta_N': '10'})
        repasse_service.criar_repasses_lote(self.comum, [e])
        r = self.c_comum.post(self.url, {'extracao_ids': [e.pk], 'mes': 8, 'ano': 2026})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Repasse.objects.filter(extracao=e).exists())
        self.assertEqual(LogAuditoria.objects.get(acao='REPASSE_APAGADO').usuario_nome, 'operador')

    def test_entradas_invalidas_nao_quebram(self):
        antes = Repasse.objects.count()
        for dados in ({}, {'extracao_ids': ['abc']}, {'extracao_ids': [999999]},
                      {'extracao_ids': [self.exts['ANA LIMA'].pk], 'mes': '13', 'ano': 'x'}):
            if dados.get('extracao_ids') == [self.exts['ANA LIMA'].pk]:
                antes -= 1                                         # este caso é válido: apaga a da Ana
            r = self.client.post(self.url, dados)
            self.assertEqual(r.status_code, 302, dados)
        self.assertEqual(Repasse.objects.count(), antes)
        # sem repasse nos selecionados: só informa
        r = self.client.post(self.url, {'extracao_ids': [self.exts['ANA LIMA'].pk], 'mes': 8, 'ano': 2026}, follow=True)
        self.assertContains(r, 'Nenhum dos selecionados tinha repasse')

    def test_so_aceita_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(Client().post(self.url, {}).status_code, 302)       # sem login: vai para o login
        self.assertEqual(Repasse.objects.count(), 3)

    def test_botao_so_aparece_quando_ha_rascunho(self):
        url = reverse('siresp_app:repasse_lote') + '?mes=8&ano=2026'
        r = self.client.get(url)
        self.assertContains(r, 'Apagar repasses selecionados')
        self.assertContains(r, 'name="mes"')
        for rep in Repasse.objects.all():
            repasse_service.finalizar_repasse(rep, competencia_padrao())
        self.assertNotContains(self.client.get(url), 'Apagar repasses selecionados')   # só finalizados: nada a apagar
        Repasse.objects.all().delete()
        self.assertNotContains(self.client.get(url), 'Apagar repasses selecionados')

    def test_auditoria_mostra_o_selo_da_acao(self):
        self.post('ANA LIMA')
        r = self.client.get(reverse('siresp_app:auditoria_lista') + '?acao=REPASSE_APAGADO')
        self.assertContains(r, 'Repasse apagado')
        self.assertEqual(len(r.context['pagina']), 1)
