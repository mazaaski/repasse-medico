"""Permissões (admin x usuário comum) e trilha de auditoria."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from .models import (
    EquipeMedica, Extracao, GrupoValor, ItemProducao, LogAuditoria,
    Profissional, RegraMinuto,
)
from .services import repasse_service
from .services.repasse_service import competencia_padrao
from .tests import BaseTest


class PapeisBase(BaseTest):
    """self.user = admin (is_staff). self.comum = usuário comum com client próprio."""

    def setUp(self):
        super().setUp()
        self.comum = User.objects.create_user('operador', password='senha123')
        self.c_comum = Client()
        self.c_comum.login(username='operador', password='senha123')

    def _repasse(self, dono, finalizar=False):
        ext = Extracao.objects.create(usuario_web=dono, medico_nome='JOAO SILVA',
                                      data_ini='01/01/2026', data_fim='31/01/2026')
        ItemProducao.objects.create(extracao=ext, especialidade='CARDIOLOGIA', ordem=0,
                                    dados={'Oferta_N': '10'})
        RegraMinuto.objects.get_or_create(profissional_norm='JOAO SILVA',
                                          especialidade_norm='CARDIOLOGIA',
                                          defaults={'minutos': [30]})
        rep = repasse_service.criar_repasses_lote(dono, [ext])[0][0]
        if finalizar:
            ok, _ = repasse_service.finalizar_repasse(rep, competencia_padrao())
            assert ok
            rep.refresh_from_db()
        return rep


class PermissoesTests(PapeisBase):
    def test_comum_nao_altera_cadastros(self):
        """Telas de consulta abrem; formulários e ações de escrita são barrados."""
        grupo = GrupoValor.objects.first()
        barradas_get = [
            reverse('siresp_app:config_novo'),
            reverse('siresp_app:config_editar', args=[grupo.pk]),
            reverse('siresp_app:equipes_nova'),
        ]
        for url in barradas_get:
            r = self.c_comum.get(url)
            self.assertRedirects(r, reverse('siresp_app:home'),
                                 fetch_redirect_response=False, msg_prefix=url)

        prof = Profissional.objects.create(nome='X', nome_norm='X')
        barradas_post = [
            reverse('siresp_app:config_remover', args=[grupo.pk]),
            reverse('siresp_app:config_excluir_grupos'),
            reverse('siresp_app:config_limpar_regras'),
            reverse('siresp_app:profissionais_novo'),
            reverse('siresp_app:profissionais_remover', args=[prof.pk]),
            reverse('siresp_app:equipes_nova'),
        ]
        for url in barradas_post:
            r = self.c_comum.post(url, {'todos': '1', 'nome': 'Y'})
            self.assertEqual(r.status_code, 302, url)
        self.assertTrue(GrupoValor.objects.filter(pk=grupo.pk).exists())
        self.assertEqual(Profissional.objects.count(), 1)
        self.assertEqual(EquipeMedica.objects.count(), 0)

    def test_comum_acessa_o_fluxo_operacional(self):
        for nome in ['home', 'producao_home', 'producao_historico', 'repasse_lote',
                     'relatorios_home', 'profissionais_lista', 'equipes_lista']:
            r = self.c_comum.get(reverse(f'siresp_app:{nome}'))
            self.assertEqual(r.status_code, 200, nome)

    def test_menu_mostra_as_mesmas_telas_e_marca_consulta(self):
        r = self.c_comum.get(reverse('siresp_app:home'))
        for texto in ('Grupos de valores', 'Regras de minutos', 'Importar planilha', 'Auditoria',
                      'Equipes médicas', 'Profissionais'):
            self.assertContains(r, texto)                 # mesmas opções do admin
        self.assertContains(r, 'consulta')
        self.assertNotContains(r, 'Usuários e permissões')  # só admin gerencia usuários
        r = self.client.get(reverse('siresp_app:home'))
        self.assertContains(r, 'Usuários e permissões')
        self.assertNotContains(r, 'border">consulta')

    def test_reabrir_so_admin_e_com_motivo(self):
        rep = self._repasse(self.comum, finalizar=True)
        url = reverse('siresp_app:repasse_reabrir', args=[rep.pk])

        r = self.c_comum.post(url, data={'motivo': 'quero editar'}, content_type='application/json')
        self.assertEqual(r.status_code, 403)          # até o dono comum é barrado
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'finalizado')

        r = self.client.post(url, data={}, content_type='application/json').json()
        self.assertFalse(r['ok'])                      # admin sem motivo
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'finalizado')

        r = self.client.post(url, data={'motivo': 'Ajustar valor base do grupo'},
                             content_type='application/json').json()
        self.assertTrue(r['ok'], r)                    # admin reabre repasse de outro usuário
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'rascunho')
        self.assertIsNone(rep.competencia)
        log = LogAuditoria.objects.get(acao='REPASSE_REABERTO')
        self.assertEqual(log.usuario_nome, 'medico')
        self.assertIn('Ajustar valor base do grupo', log.descricao)
        self.assertEqual(log.repasse_id, rep.pk)

    def test_reabrir_varios_so_admin(self):
        rep = self._repasse(self.comum, finalizar=True)
        url = reverse('siresp_app:relatorios_reabrir_varios')
        self.c_comum.post(url, {'repasses': [rep.pk], 'motivo': 'tentativa do comum'})
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'finalizado')
        self.client.post(url, {'repasses': [rep.pk], 'motivo': ''})
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'finalizado')     # admin sem motivo
        self.client.post(url, {'repasses': [rep.pk], 'motivo': 'Revisão de competência'})
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'rascunho')
        self.assertTrue(LogAuditoria.objects.filter(
            acao='REPASSE_REABERTO', repasse_id=rep.pk).exists())

    def test_relatorios_todos_veem_tudo_mas_so_admin_reabre(self):
        rep = self._repasse(self.comum, finalizar=True)
        User.objects.create_user('outro', password='x')
        c = Client()
        c.login(username='outro', password='x')
        for cli in (self.client, self.c_comum, c):         # admin, dono e um terceiro usuário
            r = cli.get(reverse('siresp_app:relatorios_home'))
            self.assertEqual([x.pk for x in r.context['repasses']], [rep.pk])
        self.assertNotContains(c.get(reverse('siresp_app:relatorios_home')), 'Reabrir selecionados')
        self.assertContains(self.client.get(reverse('siresp_app:relatorios_home')), 'Reabrir selecionados')
        # terceiro usuário abre o repasse em modo consulta
        r = c.get(reverse('siresp_app:repasse_ver', args=[rep.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['outro_dono'])
        self.assertNotContains(r, 'Reabrir (admin)')


class AuditoriaTests(PapeisBase):
    def test_edicao_de_item_registra_de_para(self):
        rep = self._repasse(self.user)
        item = rep.itens.get()
        antes = item.valor_base
        r = self.client.post(reverse('siresp_app:repasse_atualizar_item', args=[item.pk]),
                             data={'campo': 'valor_base', 'valor': '321.50'},
                             content_type='application/json').json()
        self.assertTrue(r['ok'])
        log = LogAuditoria.objects.get(acao='REPASSE_EDITADO')
        self.assertEqual(log.usuario_nome, 'medico')
        self.assertEqual(log.repasse_id, rep.pk)
        self.assertEqual(log.profissional, 'JOAO SILVA')
        campos = {d['campo']: d for d in log.detalhes}
        self.assertEqual(campos['Valor base']['de'], f'{antes:.2f}')
        self.assertEqual(campos['Valor base']['para'], '321.50')
        self.assertEqual(campos['Valor base']['item'], 'CARDIOLOGIA')
        self.assertIn('Total (final)', campos)          # o reflexo no total também fica registrado

    def test_edicao_sem_mudanca_nao_gera_log(self):
        rep = self._repasse(self.user)
        item = rep.itens.get()
        self.client.post(reverse('siresp_app:repasse_atualizar_item', args=[item.pk]),
                         data={'campo': 'valor_base', 'valor': str(item.valor_base)},
                         content_type='application/json')
        self.assertFalse(LogAuditoria.objects.filter(acao='REPASSE_EDITADO').exists())

    def test_lote_salvar_registra_bonus_e_marcacao(self):
        rep = self._repasse(self.user)
        item = rep.itens.get()
        r = self.client.post(reverse('siresp_app:repasse_lote_salvar'), data={'itens': [
            {'id': item.pk, 'bonus_percent': '50%', 'marcado': False, 'minutos': 45}]},
            content_type='application/json').json()
        self.assertTrue(r['ok'], r)
        log = LogAuditoria.objects.get(acao='REPASSE_EDITADO')
        campos = {d['campo']: (d['de'], d['para']) for d in log.detalhes}
        self.assertEqual(campos['Bônus %'], ('100%', '50%'))
        self.assertEqual(campos['Incluído no repasse'], ('sim', 'não'))
        self.assertEqual(campos['Minutos'][1], '45.00')

    def test_finalizar_e_exportacao_registradas(self):
        rep = self._repasse(self.user)
        item = rep.itens.get()
        item.marcado = True
        item.save()
        rep.recalcular_totais()
        r = self.client.post(
            reverse('siresp_app:repasse_finalizar', args=[rep.pk]),
            data={'competencia': competencia_padrao().strftime('%Y-%m')},
            content_type='application/json').json()
        self.assertTrue(r['ok'], r)
        fin = LogAuditoria.objects.get(acao='REPASSE_FINALIZADO')
        self.assertIn(f'{competencia_padrao():%m/%Y}', fin.descricao)
        self.client.get(reverse('siresp_app:repasse_excel', args=[rep.pk]))
        self.assertTrue(LogAuditoria.objects.filter(acao='EXPORTACAO', repasse_id=rep.pk).exists())

    def test_cadastros_registram_mudancas(self):
        self.client.post(reverse('siresp_app:config_novo'),
                         {'nome': 'Ouro', 'valor_base': '150', 'bonus': '30'})
        self.assertTrue(LogAuditoria.objects.filter(acao='GRUPO_CRIADO').exists())
        g = GrupoValor.objects.get(nome='Ouro')
        self.client.post(reverse('siresp_app:config_editar', args=[g.pk]),
                         {'nome': 'Ouro', 'valor_base': '180', 'bonus': '30'})
        log = LogAuditoria.objects.get(acao='GRUPO_EDITADO')
        campos = {d['campo']: (d['de'], d['para']) for d in log.detalhes}
        self.assertEqual(campos['Valor base'], ('150.00', '180.00'))
        self.assertNotIn('Bônus 100%', campos)          # só o que mudou
        self.client.post(reverse('siresp_app:config_remover', args=[g.pk]))
        self.assertTrue(LogAuditoria.objects.filter(acao='GRUPO_EXCLUIDO').exists())

        self.client.post(reverse('siresp_app:config_nova_regra'),
                         {'profissional': 'Maria', 'especialidade': 'Neuro', 'minutos': '10'})
        regra = RegraMinuto.objects.get(profissional_norm='MARIA')
        self.client.post(reverse('siresp_app:config_editar_regra', args=[regra.pk]),
                         {'profissional': 'Maria', 'especialidade': 'Neuro', 'minutos': '10, 20'})
        log = LogAuditoria.objects.get(acao='REGRA_EDITADA')
        self.assertEqual({d['campo']: d['para'] for d in log.detalhes}['Minutos'], '10, 20')

        a = Profissional.objects.create(nome='Ana', nome_norm='ANA')
        self.client.post(reverse('siresp_app:equipes_nova'), {'nome': 'Alfa', 'membros': [a.pk]})
        self.assertTrue(LogAuditoria.objects.filter(acao='EQUIPE_CRIADA').exists())

    def test_login_logout_e_falha(self):
        c = Client()
        c.post(reverse('siresp_app:login'), {'usuario': 'operador', 'senha': 'errada'})
        falha = LogAuditoria.objects.get(acao='LOGIN_FALHA')
        self.assertEqual(falha.usuario_nome, 'operador')
        c.post(reverse('siresp_app:login'), {'usuario': 'operador', 'senha': 'senha123'})
        self.assertTrue(LogAuditoria.objects.filter(acao='LOGIN', usuario_nome='operador').exists())
        c.get(reverse('siresp_app:logout'))
        self.assertTrue(LogAuditoria.objects.filter(acao='LOGOUT', usuario_nome='operador').exists())

    def test_tela_filtros_e_csv(self):
        rep = self._repasse(self.user)
        item = rep.itens.get()
        self.client.post(reverse('siresp_app:repasse_atualizar_item', args=[item.pk]),
                         data={'campo': 'bonus_cheio', 'valor': '77'},
                         content_type='application/json')
        self.client.post(reverse('siresp_app:config_novo'),
                         {'nome': 'Ouro', 'valor_base': '1', 'bonus': '1'})

        url = reverse('siresp_app:auditoria_lista')
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Bônus 100%')
        r = self.client.get(url + '?acao=REPASSE_EDITADO')
        self.assertEqual([l.acao for l in r.context['pagina']], ['REPASSE_EDITADO'])
        r = self.client.get(url + f'?repasse={rep.pk}')
        self.assertTrue(all(l.repasse_id == rep.pk for l in r.context['pagina']))
        r = self.client.get(url + '?usuario=medico&q=joao&de=2000-01-01&ate=2999-12-31')
        self.assertGreaterEqual(len(r.context['pagina']), 1)
        r = self.client.get(url + '?de=lixo&acao=invalida')     # filtros inválidos não quebram
        self.assertEqual(r.status_code, 200)

        csv = self.client.get(reverse('siresp_app:auditoria_csv') + '?acao=REPASSE_EDITADO')
        texto = csv.content.decode('utf-8-sig')
        self.assertIn('Data/hora;Usuário;Ação', texto)
        self.assertIn('Bônus 100%', texto)
        self.assertIn('77.00', texto)

    def test_log_nao_e_editavel_no_admin_do_django(self):
        from django.contrib import admin as dj_admin
        from .admin import LogAuditoriaAdmin
        ma = LogAuditoriaAdmin(LogAuditoria, dj_admin.site)
        req = type('R', (), {'user': self.user})()
        self.assertFalse(ma.has_add_permission(req))
        self.assertFalse(ma.has_change_permission(req))
        self.assertFalse(ma.has_delete_permission(req))

    def test_falha_de_auditoria_nao_derruba_a_operacao(self):
        from unittest import mock
        rep = self._repasse(self.user)
        item = rep.itens.get()
        with mock.patch('siresp_app.models.LogAuditoria.objects') as m:
            m.create.side_effect = RuntimeError('banco fora')
            r = self.client.post(reverse('siresp_app:repasse_atualizar_item', args=[item.pk]),
                                 data={'campo': 'valor_base', 'valor': '10'},
                                 content_type='application/json').json()
        self.assertTrue(r['ok'])
