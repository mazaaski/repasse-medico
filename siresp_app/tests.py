from decimal import Decimal

from django.contrib.auth.models import User
from .tests_util import AguardaThreads
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .models import (
    Extracao, ItemProducao, GrupoValor, EspecialidadeGrupo,
    RegraMinuto, Repasse, ItemRepasse, EquipeMedica,
)
from .services import repasse_service
from .services.repasse_service import competencia_padrao, parse_competencia
from .services.valores_service import registrar_regras


class BaseTest(TestCase):
    def setUp(self):
        # admin: os testes de fluxo/cadastros exercitam tudo; papéis em PermissoesTests
        self.user = User.objects.create_user('medico', password='senha123', is_staff=True)
        self.client.login(username='medico', password='senha123')
        GrupoValor.objects.create(nome='Padrão', valor_base=100, bonus=40)
        g = GrupoValor.objects.create(nome='Cardio', valor_base=200, bonus=50)
        EspecialidadeGrupo.objects.create(grupo=g, nome='CARDIOLOGIA')

    def criar_extracao(self):
        ext = Extracao.objects.create(
            usuario_web=self.user, medico_nome='JOAO SILVA',
            data_ini='01/01/2026', data_fim='31/01/2026',
        )
        ItemProducao.objects.create(
            extracao=ext, especialidade='CARDIOLOGIA', ordem=0,
            dados={'Especialidade': 'CARDIOLOGIA', 'Oferta_N': '30', 'Atend_Total_N': '28'},
        )
        ItemProducao.objects.create(
            extracao=ext, especialidade='ORTOPEDIA', ordem=1,
            dados={'Especialidade': 'ORTOPEDIA', 'Oferta_N': '1.000', 'Atend_Total_N': ''},
        )
        return ext


class AuthTests(TestCase):
    def test_login_page_and_redirect(self):
        self.assertEqual(self.client.get(reverse('siresp_app:login')).status_code, 200)
        r = self.client.get(reverse('siresp_app:producao_home'))
        self.assertEqual(r.status_code, 302)
        self.assertIn('/login/', r.url)

    def test_login_invalido_e_valido(self):
        User.objects.create_user('u', password='p')
        r = self.client.post(reverse('siresp_app:login'), {'usuario': 'u', 'senha': 'x'})
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse('siresp_app:login'), {'usuario': 'u', 'senha': 'p'})
        self.assertRedirects(r, reverse('siresp_app:home'), fetch_redirect_response=False)


class PaginasTests(BaseTest):
    def test_paginas_carregam(self):
        ext = self.criar_extracao()
        nomes = [
            'producao_home', 'producao_historico', 'config_lista',
            'config_especialidades', 'config_importar', 'config_regras',
            'relatorios_home', 'config_novo',
        ]
        for n in nomes:
            r = self.client.get(reverse(f'siresp_app:{n}'))
            self.assertEqual(r.status_code, 200, n)
        r = self.client.get(reverse('siresp_app:producao_ver_extracao', args=[ext.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(
            reverse('siresp_app:producao_exportar_csv', args=[ext.pk])).status_code, 200)
        self.assertEqual(self.client.get(
            reverse('siresp_app:producao_exportar_json', args=[ext.pk])).status_code, 200)


class RepasseTests(BaseTest):
    def test_criar_repasse_valores(self):
        RegraMinuto.objects.create(
            profissional_norm='JOAO SILVA', especialidade_norm='CARDIOLOGIA', minutos=[20])
        rep = repasse_service.criar_repasse_de_extracao(self.criar_extracao(), self.user)
        cardio, orto = rep.itens.all()
        self.assertEqual(cardio.minutos, Decimal('20'))
        self.assertEqual(cardio.valor_base, Decimal('200'))
        self.assertEqual(cardio.valor_hora, Decimal('250.00'))
        self.assertEqual(cardio.horas_real, Decimal('10.00'))
        self.assertEqual(cardio.total_real, Decimal('2500.00'))
        self.assertTrue(orto.faltou_regra)
        self.assertEqual(orto.oferta, 1000)
        self.assertEqual(orto.grupo_nome, 'Padrão')

    def test_fluxo_view_repasse(self):
        ext = self.criar_extracao()
        r = self.client.get(reverse('siresp_app:producao_ir_repasse', args=[ext.pk]))
        rep = Repasse.objects.get(extracao=ext)
        self.assertRedirects(r, reverse('siresp_app:repasse_ver', args=[rep.pk]))
        self.assertEqual(self.client.get(
            reverse('siresp_app:repasse_ver', args=[rep.pk])).status_code, 200)

        item = rep.itens.first()
        r = self.client.post(
            reverse('siresp_app:repasse_atualizar_item', args=[item.pk]),
            data='{"campo": "marcado", "valor": true}', content_type='application/json')
        self.assertTrue(r.json()['ok'])

        r = self.client.post(
            reverse('siresp_app:repasse_arredondar', args=[rep.pk]),
            data='{"modo": "cima"}', content_type='application/json')
        self.assertTrue(r.json()['ok'])

        # Excel bloqueado até finalizar
        r = self.client.get(reverse('siresp_app:repasse_excel', args=[rep.pk]))
        self.assertRedirects(r, reverse('siresp_app:repasse_ver', args=[rep.pk]))

        # Finalizar exige competência válida (mês já fechado)
        url = reverse('siresp_app:repasse_finalizar', args=[rep.pk])
        post = lambda body: self.client.post(url, data=body, content_type='application/json').json()
        self.assertFalse(post({})['ok'])
        self.assertFalse(post({'competencia': '2999-01'})['ok'])
        ok = post({'competencia': competencia_padrao().strftime('%Y-%m')})
        self.assertTrue(ok['ok'], ok)
        rep.refresh_from_db()
        self.assertEqual(rep.competencia, competencia_padrao())
        self.assertEqual(self.client.get(
            reverse('siresp_app:repasse_excel', args=[rep.pk])).status_code, 200)
        # Trava de edição
        r = self.client.post(
            reverse('siresp_app:repasse_atualizar_item', args=[item.pk]),
            data='{"campo": "marcado", "valor": false}', content_type='application/json')
        self.assertFalse(r.json()['ok'])
        # Aparece em relatórios
        r = self.client.post(reverse('siresp_app:relatorios_gerar_excel'), {'repasses': [rep.pk]})
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse('siresp_app:repasse_reabrir', args=[rep.pk]),
                             data={'motivo': 'Corrigir valor base'}, content_type='application/json')
        self.assertTrue(r.json()['ok'])

    def test_finalizar_sem_marcados(self):
        rep = repasse_service.criar_repasse_de_extracao(self.criar_extracao(), self.user)
        r = self.client.post(reverse('siresp_app:repasse_finalizar', args=[rep.pk]))
        self.assertFalse(r.json()['ok'])

    def test_outro_usuario_consulta_mas_nao_edita(self):
        rep = repasse_service.criar_repasse_de_extracao(self.criar_extracao(), self.user)
        item = rep.itens.first()
        User.objects.create_user('outro', password='x')
        self.client.logout()
        self.client.login(username='outro', password='x')
        r = self.client.get(reverse('siresp_app:repasse_ver', args=[rep.pk]))
        self.assertEqual(r.status_code, 200)              # vê os mesmos dados
        self.assertTrue(r.context['outro_dono'])
        self.assertTrue(r.context['bloqueado'])
        antes = item.valor_base
        r = self.client.post(reverse('siresp_app:repasse_atualizar_item', args=[item.pk]),
                             data={'campo': 'valor_base', 'valor': '1'}, content_type='application/json')
        self.assertEqual(r.status_code, 404)              # mas não altera
        item.refresh_from_db()
        self.assertEqual(item.valor_base, antes)


class RegrasTests(BaseTest):
    def test_registrar_regras_e_crud(self):
        stats = registrar_regras([('Dr. João', 'Cardiologia', 15), ('Dr. João', 'Cardiologia', 30)])
        self.assertEqual(stats['pares'], 1)
        self.assertEqual(RegraMinuto.objects.get().minutos, [15, 30])

        r = self.client.post(reverse('siresp_app:config_nova_regra'), {
            'profissional': 'Maria', 'especialidade': 'Neuro', 'minutos': '10, 20'})
        self.assertEqual(r.status_code, 302)
        regra = RegraMinuto.objects.get(profissional_norm='MARIA')
        self.assertEqual(regra.minutos, [10, 20])

        # Editar mudando o profissional não deve deixar duplicata
        self.client.post(reverse('siresp_app:config_editar_regra', args=[regra.pk]), {
            'profissional': 'Mariana', 'especialidade': 'Neuro', 'minutos': '10'})
        self.assertFalse(RegraMinuto.objects.filter(profissional_norm='MARIA').exists())
        self.assertTrue(RegraMinuto.objects.filter(profissional_norm='MARIANA').exists())

        # Edição inválida não pode apagar a regra
        r2 = RegraMinuto.objects.get(profissional_norm='MARIANA')
        self.client.post(reverse('siresp_app:config_editar_regra', args=[r2.pk]), {
            'profissional': 'Outra', 'especialidade': 'Neuro', 'minutos': ''})
        self.assertTrue(RegraMinuto.objects.filter(pk=r2.pk).exists())

        self.client.post(reverse('siresp_app:config_deletar_regra', args=[r2.pk]))
        self.assertFalse(RegraMinuto.objects.filter(pk=r2.pk).exists())

    def test_grupo_crud(self):
        r = self.client.post(reverse('siresp_app:config_novo'), {
            'nome': 'Novo', 'valor_base': '150,50', 'bonus': '30', 'especialidades': ['ORTOPEDIA']})
        self.assertEqual(r.status_code, 302)
        g = GrupoValor.objects.get(nome='Novo')
        self.assertEqual(g.valor_base, Decimal('150.50'))
        self.assertEqual(g.especialidades.count(), 1)
        # GET não pode mais apagar
        self.assertEqual(self.client.get(
            reverse('siresp_app:config_remover', args=[g.pk])).status_code, 405)
        self.assertTrue(GrupoValor.objects.filter(pk=g.pk).exists())
        self.client.post(reverse('siresp_app:config_remover', args=[g.pk]))
        self.assertFalse(GrupoValor.objects.filter(nome='Novo').exists())

    def test_excluir_grupos_em_massa(self):
        self.assertEqual(GrupoValor.objects.count(), 2)
        cardio = GrupoValor.objects.get(nome='Cardio')
        self.client.post(reverse('siresp_app:config_excluir_grupos'), {'grupo_ids': [cardio.pk]})
        self.assertEqual(GrupoValor.objects.count(), 1)
        self.assertEqual(self.client.get(reverse('siresp_app:config_lista')).status_code, 200)
        self.client.post(reverse('siresp_app:config_excluir_grupos'), {'todos': '1'})
        self.assertEqual(GrupoValor.objects.count(), 0)
        self.assertEqual(self.client.get(reverse('siresp_app:config_lista')).status_code, 200)


class RepasseLoteTests(BaseTest):
    def _extracao(self, nome, esp_list):
        ext = Extracao.objects.create(usuario_web=self.user, medico_nome=nome,
                                      data_ini='01/01/2026', data_fim='31/01/2026')
        for i, esp in enumerate(esp_list):
            ItemProducao.objects.create(
                extracao=ext, especialidade=esp, ordem=i,
                dados={'Especialidade': esp, 'Oferta_N': '60', 'Atend_Total_N': '50'})
        return ext

    def test_lote_marca_por_regra_e_gera_relatorio(self):
        RegraMinuto.objects.create(profissional_norm='JOAO SILVA',
                                   especialidade_norm='CARDIOLOGIA', minutos=[30])
        e1 = self._extracao('JOAO SILVA', ['CARDIOLOGIA', 'ORTOPEDIA'])
        e2 = self._extracao('MARIA SOUZA', ['NEURO'])

        page = self.client.get(reverse('siresp_app:repasse_lote') + '?mes=1&ano=2026')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'JOAO SILVA')

        r = self.client.post(reverse('siresp_app:repasse_lote_gerar'),
                             {'extracao_ids': [e1.pk, e2.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertIn('/repasse/lote/relatorio/?ids=', r.url)

        rep = Repasse.objects.get(extracao=e1)
        marcados = list(rep.itens.filter(marcado=True))
        self.assertEqual([i.especialidade for i in marcados], ['CARDIOLOGIA'])
        # 60 * 30min = 30h * (200 + 50) = 7500
        self.assertEqual(rep.horas_total_final, Decimal('30.00'))
        self.assertEqual(rep.valor_total_final, Decimal('7500.00'))
        self.assertEqual(rep.status, 'rascunho')
        self.assertEqual(Repasse.objects.get(extracao=e2).itens.filter(marcado=True).count(), 0)

        rel = self.client.get(r.url)
        self.assertEqual(rel.status_code, 200)
        self.assertContains(rel, 'CARDIOLOGIA')
        self.assertContains(rel, 'ORTOPEDIA')  # listada como sem regra
        self.assertEqual(rel.context['qtd_sem_regra'], 2)
        self.assertEqual(rel.context['tot_valor'], Decimal('7500.00'))
        url_xl = reverse('siresp_app:repasse_lote_relatorio_excel') + '?ids=%d' % rep.pk
        self.assertEqual(self.client.get(url_xl).status_code, 302)  # rascunho: bloqueado
        self.client.post(reverse('siresp_app:repasse_lote_finalizar'), {
            'extracao_ids': [e1.pk], 'competencia': competencia_padrao().strftime('%Y-%m')})
        self.assertEqual(self.client.get(url_xl).status_code, 200)

    def test_lote_refaz_rascunho_e_protege_finalizado(self):
        RegraMinuto.objects.create(profissional_norm='JOAO SILVA',
                                   especialidade_norm='CARDIOLOGIA', minutos=[30])
        e1 = self._extracao('JOAO SILVA', ['CARDIOLOGIA'])
        e2 = self._extracao('MARIA SOUZA', ['NEURO'])
        for e in (e1, e2):
            repasse_service.criar_repasse_de_extracao(e, self.user)
        # João: rascunho com ajuste manual; Maria: finalizada
        r1 = Repasse.objects.get(extracao=e1)
        r1.itens.update(minutos=Decimal('99'))
        r2 = Repasse.objects.get(extracao=e2)
        r2.status = 'finalizado'
        r2.save()
        id2 = r2.pk

        page = self.client.get(reverse('siresp_app:repasse_lote') + '?mes=1&ano=2026')
        self.assertEqual(page.context['rascunhos'], 1)

        r = self.client.post(reverse('siresp_app:repasse_lote_gerar'),
                             {'extracao_ids': [e1.pk, e2.pk]})
        self.assertIn('/repasse/lote/relatorio/?ids=', r.url)
        novo = Repasse.objects.get(extracao=e1)
        self.assertEqual(novo.itens.get().minutos, Decimal('30'))   # refeito com a regra
        self.assertTrue(novo.itens.get().marcado)
        self.assertEqual(Repasse.objects.get(extracao=e2).pk, id2)  # finalizado intacto
        self.assertEqual(Repasse.objects.get(extracao=e2).status, 'finalizado')

    def test_lote_so_finalizados_nao_gera(self):
        e = self._extracao('JOAO SILVA', ['CARDIOLOGIA'])
        rep = repasse_service.criar_repasse_de_extracao(e, self.user)
        rep.status = 'finalizado'
        rep.save()
        r = self.client.post(reverse('siresp_app:repasse_lote_gerar'), {'extracao_ids': [e.pk]})
        self.assertRedirects(r, reverse('siresp_app:repasse_lote'))


class PainelTests(BaseTest):
    def test_painel_e_proximo_passo(self):
        r = self.client.get(reverse('siresp_app:home'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('planilha', r.context['passo_texto'])  # base vazia
        Profissional.objects.create(nome='JOAO SILVA', nome_norm='JOAO SILVA')
        r = self.client.get(reverse('siresp_app:home') + '?mes=1&ano=2026')
        self.assertEqual(r.context['cont']['pendente'], 1)
        ext = Extracao.objects.create(usuario_web=self.user, medico_nome='JOAO SILVA',
                                      data_ini='01/01/2026', data_fim='31/01/2026')
        r = self.client.get(reverse('siresp_app:home') + '?mes=1&ano=2026')
        self.assertEqual(r.context['passo_botao'], 'Gerar repasses em lote')
        repasse_service.criar_repasse_de_extracao(ext, self.user)
        r = self.client.get(reverse('siresp_app:home') + '?mes=1&ano=2026')
        self.assertEqual(r.context['passo_botao'], 'Conferir rascunhos')
        Repasse.objects.update(status='finalizado')
        r = self.client.get(reverse('siresp_app:home') + '?mes=1&ano=2026')
        self.assertEqual(r.context['passo_botao'], 'Ir para Relatórios')


class ModelTests(TestCase):
    def test_bonus_aplicado(self):
        item = ItemRepasse(bonus_cheio=Decimal('40'), bonus_percent='50%',
                           valor_base=Decimal('100'), oferta=6, minutos=Decimal('30'))
        item.recalcular()
        self.assertEqual(item.valor_hora, Decimal('120.00'))
        self.assertEqual(item.horas_real, Decimal('3.00'))
        self.assertEqual(item.total_real, Decimal('360.00'))


# =========================================================
# Base de profissionais e lote
# =========================================================
import time
from unittest import mock

from .models import Profissional
from .services import lote_service
from .services.profissionais_service import situacao_mes


class ProfissionaisTests(BaseTest):
    def test_importacao_popula_base(self):
        stats = registrar_regras([
            ('Dr. João', 'Cardio', 15), ('DR. JOAO', 'Neuro', 20), ('Maria', 'Cardio', 30)])
        self.assertEqual(stats['novos_prof'], 2)
        self.assertEqual(Profissional.objects.count(), 2)
        # reimportar não duplica
        self.assertEqual(registrar_regras([('Maria', 'Cardio', 30)])['novos_prof'], 0)

    def test_situacao_mes(self):
        for n in ('JOAO SILVA', 'MARIA SOUZA', 'PEDRO LIMA', 'ANA COSTA'):
            Profissional.objects.create(nome=n, nome_norm=n)
        Profissional.objects.create(nome='INATIVO', nome_norm='INATIVO', ativo=False)

        ext = self.criar_extracao()  # JOAO SILVA, janeiro/2026
        rep = repasse_service.criar_repasse_de_extracao(ext, self.user)
        # Maria: extraída sem repasse
        Extracao.objects.create(usuario_web=self.user, medico_nome='Maria Souza',
                                data_ini='01/01/2026', data_fim='31/01/2026')
        # Ana: fevereiro (fora do mês)
        Extracao.objects.create(usuario_web=self.user, medico_nome='ANA COSTA',
                                data_ini='01/02/2026', data_fim='28/02/2026')

        def por_nome():
            return {s['profissional'].nome: s['status'] for s in situacao_mes(self.user, 2026, 1)}

        st = por_nome()
        self.assertEqual(st['JOAO SILVA'], 'rascunho')
        self.assertEqual(st['MARIA SOUZA'], 'extraido')
        self.assertEqual(st['PEDRO LIMA'], 'pendente')
        self.assertEqual(st['ANA COSTA'], 'pendente')
        self.assertNotIn('INATIVO', st)

        rep.status = 'finalizado'
        rep.save()
        self.assertEqual(por_nome()['JOAO SILVA'], 'finalizado')

    def test_paginas_e_acoes(self):
        r = self.client.post(reverse('siresp_app:profissionais_novo'), {'nome': 'Fulano de Tal'})
        self.assertEqual(r.status_code, 302)
        p = Profissional.objects.get()
        self.assertEqual(self.client.get(
            reverse('siresp_app:profissionais_lista') + '?mes=1&ano=2026').status_code, 200)
        self.client.post(reverse('siresp_app:profissionais_alternar', args=[p.pk]))
        p.refresh_from_db()
        self.assertFalse(p.ativo)
        self.client.post(reverse('siresp_app:profissionais_remover', args=[p.pk]))
        self.assertEqual(Profissional.objects.count(), 0)

    def test_pendentes_json(self):
        Profissional.objects.create(nome='PEDRO LIMA', nome_norm='PEDRO LIMA')
        r = self.client.get(reverse('siresp_app:producao_lote_pendentes') + '?mes=1&ano=2026')
        self.assertEqual(r.json()['nomes'], ['PEDRO LIMA'])


class LoteTests(BaseTest):
    def test_escolher_medico(self):
        m = [{'nome': 'JOAO SILVA', 'crm': '1', 'codigo': '1'},
             {'nome': 'JOAO SILVA JUNIOR', 'crm': '2', 'codigo': '2'}]
        self.assertEqual(lote_service.escolher_medico('João Silva', m)[1], 'ok')
        self.assertEqual(lote_service.escolher_medico('João', m)[1], 'ambiguo')
        self.assertEqual(lote_service.escolher_medico('X', [])[1], 'nao_encontrado')
        self.assertEqual(lote_service.escolher_medico('Fulano', m[:1])[1], 'ok')

    def test_lote_exige_login_siresp(self):
        r = self.client.post(
            reverse('siresp_app:producao_lote_iniciar'),
            data={'nomes': ['X'], 'data_ini': '01/01/2026', 'data_fim': '31/01/2026'},
            content_type='application/json')
        self.assertFalse(r.json()['ok'])


class LoteThreadTests(AguardaThreads, TransactionTestCase):
    # TransactionTestCase: a thread de fundo precisa enxergar os dados commitados
    def setUp(self):
        User.objects.create_user('medico', password='senha123')
        self.client.login(username='medico', password='senha123')

    def test_lote_end_to_end_com_scraper_falso(self):
        buscas = {
            'JOAO SILVA': [{'nome': 'JOAO SILVA', 'crm': '1', 'codigo': '10'}],
            'ANA': [{'nome': 'ANA A', 'crm': '2', 'codigo': '20'},
                    {'nome': 'ANA B', 'crm': '3', 'codigo': '30'}],
        }
        dados = [{'Especialidade': 'CARDIOLOGIA', 'Oferta_N': '10', 'Atend_Total_N': '9'}]
        sc = 'siresp_app.services.lote_service.scraper_service'
        with mock.patch(sc + '.listar_medicos', side_effect=lambda u, n, o: buscas.get(n.upper().replace('Ã','A').replace('É','E'), [])), \
                mock.patch(sc + '.extrair_producao', return_value=dados), \
                mock.patch(sc + '.sessao_ativa', return_value=True), \
                mock.patch('siresp_app.views.producao.scraper_service.sessao_ativa', return_value=True), \
                mock.patch('siresp_app.views.producao.scraper_service.status_login',
                           return_value={'estado': 'logado', 'logado': True}):
            r = self.client.post(
                reverse('siresp_app:producao_lote_iniciar'),
                data={'nomes': ['João Silva', 'Ana', 'Zé', 'joao silva'],
                      'data_ini': '01/01/2026', 'data_fim': '31/01/2026'},
                content_type='application/json')
            self.assertTrue(r.json()['ok'], r.json())
            for _ in range(50):
                st = self.client.get(reverse('siresp_app:producao_lote_status')).json()
                if not st['rodando']:
                    break
                time.sleep(0.1)

        status = {i['nome']: i['status'] for i in st['itens']}
        self.assertEqual(status, {'João Silva': 'concluido', 'Ana': 'ambiguo', 'Zé': 'nao_encontrado'})
        ext = Extracao.objects.get(medico_nome='JOAO SILVA')
        self.assertEqual(ext.itens.count(), 1)


class LoteErrosTests(TestCase):
    def test_descrever_erro_sem_stacktrace(self):
        class TimeoutException(Exception):
            pass
        msg = lote_service._descrever_erro(TimeoutException('Message: \nStacktrace: chromedriver!x'))
        self.assertNotIn('chromedriver', msg)
        self.assertIn('tempo esgotado', msg)
        self.assertEqual(lote_service._descrever_erro(Exception('Message: falhou\nStacktrace: x')), 'falhou')


class CompetenciaTests(BaseTest):
    def test_parse_competencia(self):
        from datetime import date
        hoje = date(2026, 9, 15)
        self.assertEqual(parse_competencia('2026-08', hoje), date(2026, 8, 1))
        self.assertEqual(parse_competencia('08/2026', hoje), date(2026, 8, 1))
        self.assertEqual(parse_competencia('2026-01', hoje), date(2026, 1, 1))
        for ruim in ('', '2026-09', '2026-10', 'abc'):
            with self.assertRaises(ValueError):
                parse_competencia(ruim, hoje)
        self.assertEqual(competencia_padrao(date(2026, 1, 10)), date(2025, 12, 1))

    def test_lote_finalizar_libera_excel(self):
        RegraMinuto.objects.create(profissional_norm='JOAO SILVA',
                                   especialidade_norm='CARDIOLOGIA', minutos=[30])
        ext = Extracao.objects.create(usuario_web=self.user, medico_nome='JOAO SILVA',
                                      data_ini='01/01/2026', data_fim='31/01/2026')
        ItemProducao.objects.create(extracao=ext, especialidade='CARDIOLOGIA', ordem=0,
                                    dados={'Oferta_N': '10', 'Atend_Total_N': '9'})
        e_vazia = Extracao.objects.create(usuario_web=self.user, medico_nome='MARIA',
                                          data_ini='01/01/2026', data_fim='31/01/2026')
        ItemProducao.objects.create(extracao=e_vazia, especialidade='NEURO', ordem=0,
                                    dados={'Oferta_N': '10'})
        repasse_service.criar_repasses_lote(self.user, [ext, e_vazia])
        rep = Repasse.objects.get(extracao=ext)
        ids = f'{rep.pk},{Repasse.objects.get(extracao=e_vazia).pk}'
        url_xl = reverse('siresp_app:repasse_lote_relatorio_excel') + '?ids=' + str(rep.pk)

        # bloqueado antes de finalizar
        self.assertEqual(self.client.get(url_xl).status_code, 302)
        rel = self.client.get(reverse('siresp_app:repasse_lote_relatorio') + '?ids=' + ids)
        self.assertFalse(rel.context['todos_finalizados'])

        # competência inválida (mês atual) não finaliza
        self.client.post(reverse('siresp_app:repasse_lote_finalizar'), {
            'extracao_ids': [ext.pk], 'competencia': '2999-01'})
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'rascunho')

        # válida: finaliza quem tem linha marcada; a sem regra fica de fora
        self.client.post(reverse('siresp_app:repasse_lote_finalizar'), {
            'extracao_ids': [ext.pk, e_vazia.pk],
            'competencia': competencia_padrao().strftime('%Y-%m')})
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'finalizado')
        self.assertEqual(rep.competencia, competencia_padrao())
        self.assertEqual(Repasse.objects.get(extracao=e_vazia).status, 'rascunho')
        self.assertEqual(self.client.get(url_xl).status_code, 200)
        # com a vazia ainda em rascunho, o excel conjunto continua bloqueado
        self.assertEqual(self.client.get(
            reverse('siresp_app:repasse_lote_relatorio_excel') + '?ids=' + ids).status_code, 302)

        # reabrir limpa a competência
        self.client.post(reverse('siresp_app:repasse_reabrir', args=[rep.pk]),
                         data={'motivo': 'Corrigir valor base'}, content_type='application/json')
        rep.refresh_from_db()
        self.assertIsNone(rep.competencia)


class LoteEdicaoTests(BaseTest):
    def _setup(self):
        RegraMinuto.objects.create(profissional_norm='JOAO SILVA',
                                   especialidade_norm='CARDIOLOGIA', minutos=[30])
        ext = Extracao.objects.create(usuario_web=self.user, medico_nome='JOAO SILVA',
                                      data_ini='01/01/2026', data_fim='31/01/2026')
        for i, esp in enumerate(['CARDIOLOGIA', 'ORTOPEDIA']):
            ItemProducao.objects.create(extracao=ext, especialidade=esp, ordem=i,
                                        dados={'Oferta_N': '60', 'Atend_Total_N': '50'})
        criados, _, _ = repasse_service.criar_repasses_lote(self.user, [ext])
        return ext, criados[0]

    def test_salvar_edicao_sem_finalizar(self):
        ext, rep = self._setup()
        cardio, orto = rep.itens.all()
        r = self.client.post(reverse('siresp_app:repasse_lote_salvar'), data={'itens': [
            {'id': cardio.pk, 'valor_base': '300,00', 'bonus_cheio': 100, 'bonus_percent': '50%',
             'minutos': 60, 'marcado': True},
            {'id': orto.pk, 'marcado': True, 'minutos': 30, 'valor_base': 100, 'bonus_cheio': 0},
        ]}, content_type='application/json').json()
        self.assertTrue(r['ok'], r)
        rep.refresh_from_db()
        cardio.refresh_from_db()
        self.assertEqual(rep.status, 'rascunho')            # não finalizou
        self.assertEqual(cardio.valor_hora, Decimal('350.00'))  # 300 + 100*50%
        self.assertEqual(cardio.horas_real, Decimal('60.00'))   # 60 * 60min
        self.assertEqual(cardio.total_real, Decimal('21000.00'))
        orto.refresh_from_db()
        self.assertTrue(orto.marcado)
        self.assertEqual(rep.valor_total_final, Decimal('21000.00') + orto.total_final)

    def test_salvar_recusa_finalizado_e_valor_invalido(self):
        ext, rep = self._setup()
        item = rep.itens.first()
        r = self.client.post(reverse('siresp_app:repasse_lote_salvar'), data={'itens': [
            {'id': item.pk, 'valor_base': -5}]}, content_type='application/json').json()
        self.assertFalse(r['ok'])
        rep.status = 'finalizado'
        rep.save()
        r = self.client.post(reverse('siresp_app:repasse_lote_salvar'), data={'itens': [
            {'id': item.pk, 'valor_base': 10}]}, content_type='application/json').json()
        self.assertFalse(r['ok'])
        item.refresh_from_db()
        self.assertNotEqual(item.valor_base, Decimal('10'))

    def test_relatorio_do_mes_inclui_finalizados_e_lista_sem_botao_finalizar(self):
        ext, rep = self._setup()
        rep.status = 'finalizado'
        rep.competencia = competencia_padrao()
        rep.save()
        rel = self.client.get(reverse('siresp_app:repasse_lote_relatorio') + '?mes=1&ano=2026')
        self.assertEqual(rel.status_code, 200)
        self.assertEqual(len(rel.context['blocos']), 1)      # finalizado continua aparecendo
        self.assertTrue(rel.context['todos_finalizados'])
        lista = self.client.get(reverse('siresp_app:repasse_lote') + '?mes=1&ano=2026')
        self.assertNotContains(lista, 'Finalizar selecionados')
        self.assertContains(lista, 'Relatório e edição do mês')


class EquipeTests(BaseTest):
    def _prof(self, nome):
        return Profissional.objects.create(nome=nome, nome_norm=nome.upper())

    def test_crud_equipe_e_unicidade(self):
        a, b, c = self._prof('Ana Lima'), self._prof('Bruno Dias'), self._prof('Carla Melo')
        r = self.client.post(reverse('siresp_app:equipes_nova'),
                             {'nome': 'Clínica Alfa', 'membros': [a.pk, b.pk]})
        self.assertEqual(r.status_code, 302)
        eq = EquipeMedica.objects.get(nome='Clínica Alfa')
        self.assertEqual(eq.membros.count(), 2)

        # profissional já em outra equipe é ignorado
        self.client.post(reverse('siresp_app:equipes_nova'),
                         {'nome': 'Clínica Beta', 'membros': [b.pk, c.pk]})
        beta = EquipeMedica.objects.get(nome='Clínica Beta')
        self.assertEqual([p.nome for p in beta.membros.all()], ['Carla Melo'])
        b.refresh_from_db()
        self.assertEqual(b.equipe, eq)

        # editar: remove Ana, mantém Bruno
        self.client.post(reverse('siresp_app:equipes_editar', args=[eq.pk]),
                         {'nome': 'Clínica Alfa', 'membros': [b.pk]})
        a.refresh_from_db()
        self.assertIsNone(a.equipe)
        self.assertEqual(self.client.get(reverse('siresp_app:equipes_lista')).status_code, 200)
        self.assertEqual(self.client.get(
            reverse('siresp_app:equipes_editar', args=[eq.pk])).status_code, 200)

        # nome duplicado é recusado
        self.client.post(reverse('siresp_app:equipes_nova'), {'nome': 'clínica alfa'})
        self.assertEqual(EquipeMedica.objects.count(), 2)

        # remover equipe não apaga profissionais
        self.client.post(reverse('siresp_app:equipes_remover', args=[eq.pk]))
        self.assertEqual(Profissional.objects.count(), 3)
        b.refresh_from_db()
        self.assertIsNone(b.equipe)

    def test_relatorio_agrupa_equipe_e_soma(self):
        RegraMinuto.objects.create(profissional_norm='ANA LIMA',
                                   especialidade_norm='CARDIOLOGIA', minutos=[30])
        RegraMinuto.objects.create(profissional_norm='BRUNO DIAS',
                                   especialidade_norm='CARDIOLOGIA', minutos=[60])
        eq = EquipeMedica.objects.create(nome='Clínica Alfa')
        Profissional.objects.create(nome='Ana Lima', nome_norm='ANA LIMA', equipe=eq)
        Profissional.objects.create(nome='Bruno Dias', nome_norm='BRUNO DIAS', equipe=eq)

        exts = []
        for nome in ('ANA LIMA', 'BRUNO DIAS', 'DIOGO SOLO'):
            e = Extracao.objects.create(usuario_web=self.user, medico_nome=nome,
                                        data_ini='01/01/2026', data_fim='31/01/2026')
            ItemProducao.objects.create(extracao=e, especialidade='CARDIOLOGIA', ordem=0,
                                        dados={'Oferta_N': '60'})
            exts.append(e)
        repasse_service.criar_repasses_lote(self.user, exts)

        rel = self.client.get(reverse('siresp_app:repasse_lote_relatorio') + '?mes=1&ano=2026')
        self.assertEqual(rel.status_code, 200)
        grupos = rel.context['grupos']
        self.assertEqual([g['equipe'].nome if g['equipe'] else None for g in grupos],
                         ['Clínica Alfa', None])            # avulsos por último
        alfa = grupos[0]
        self.assertEqual(len(alfa['itens']), 2)
        # Ana: 60*30/60=30h ; Bruno: 60*60/60=60h ; valor/h do grupo Cardio 250
        self.assertEqual(alfa['horas'], Decimal('90.00'))
        self.assertEqual(alfa['valor'], Decimal('22500.00'))
        self.assertContains(rel, 'Equipe Clínica Alfa')
        self.assertContains(rel, 'Total da equipe')
        self.assertContains(rel, 'Resumo por faturamento')
        resumo = rel.context['resumo']
        self.assertEqual([(l['nome'], l['equipe']) for l in resumo],
                         [('Clínica Alfa', True), ('DIOGO SOLO', False)])
        self.assertEqual(resumo[0]['valor'], Decimal('22500.00'))

        # Excel: finaliza tudo e confere aba por equipe
        self.client.post(reverse('siresp_app:repasse_lote_finalizar'), {
            'extracao_ids': [e.pk for e in exts],
            'competencia': competencia_padrao().strftime('%Y-%m')})
        # Diogo não tem regra: sem linha marcada, fica em rascunho -> Excel bloqueado
        ids = ','.join(str(r.pk) for r in Repasse.objects.exclude(extracao__medico_nome='DIOGO SOLO'))
        xl = self.client.get(reverse('siresp_app:repasse_lote_relatorio_excel') + '?ids=' + ids)
        self.assertEqual(xl.status_code, 200)
        from io import BytesIO
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(xl.content))
        self.assertEqual(wb.sheetnames, ['Resumo do Lote', 'Por Equipe'])
        linhas = list(wb['Por Equipe'].iter_rows(values_only=True))
        self.assertEqual(linhas[1][0], 'Clínica Alfa')
        self.assertIn('ANA LIMA', linhas[1][1])
        self.assertIn('BRUNO DIAS', linhas[1][1])
        self.assertEqual(linhas[1][3], 22500.0)
        principal = [r for r in wb['Resumo do Lote'].iter_rows(values_only=True) if any(v is not None for v in r)]
        nomes = [r[0] for r in principal]
        self.assertIn('RESUMO POR FATURAMENTO (EQUIPES)', nomes)
        self.assertEqual(nomes[-1], 'TOTAL GERAL DO REPASSE')
        self.assertEqual(principal[-2][0], 'Clínica Alfa')

    def test_excel_consolidado_relatorios_tem_equipe(self):
        RegraMinuto.objects.create(profissional_norm='ANA LIMA',
                                   especialidade_norm='CARDIOLOGIA', minutos=[60])
        eq = EquipeMedica.objects.create(nome='Clínica Alfa')
        Profissional.objects.create(nome='Ana Lima', nome_norm='ANA LIMA', equipe=eq)
        e = Extracao.objects.create(usuario_web=self.user, medico_nome='ANA LIMA',
                                    data_ini='01/01/2026', data_fim='31/01/2026')
        ItemProducao.objects.create(extracao=e, especialidade='CARDIOLOGIA', ordem=0,
                                    dados={'Oferta_N': '10'})
        repasse_service.criar_repasses_lote(self.user, [e])
        self.client.post(reverse('siresp_app:repasse_lote_finalizar'), {
            'extracao_ids': [e.pk], 'competencia': competencia_padrao().strftime('%Y-%m')})
        rep = Repasse.objects.get()
        xl = self.client.post(reverse('siresp_app:relatorios_gerar_excel'), {'repasses': [rep.pk]})
        self.assertEqual(xl.status_code, 200)
        from io import BytesIO
        from openpyxl import load_workbook
        wb = load_workbook(BytesIO(xl.content))
        self.assertIn('Por Equipe', wb.sheetnames)
        self.assertEqual(wb.worksheets[0].cell(row=5, column=17).value, 'Clínica Alfa')


class SmokeTests(BaseTest):
    """Abre todas as telas/rotas GET com dados completos e exige resposta sem erro."""

    def test_todas_as_telas_abrem(self):
        RegraMinuto.objects.create(profissional_norm='JOAO SILVA',
                                   especialidade_norm='CARDIOLOGIA', minutos=[15, 30])
        eq = EquipeMedica.objects.create(nome='Clínica Alfa')
        prof = Profissional.objects.create(nome='JOAO SILVA', nome_norm='JOAO SILVA', equipe=eq)
        ext = self.criar_extracao()
        rep = repasse_service.criar_repasses_lote(self.user, [ext])[0][0]
        reg = RegraMinuto.objects.get()
        grupo = GrupoValor.objects.first()
        item = rep.itens.first()

        sem_args = [
            'home', 'producao_home', 'producao_historico', 'producao_status_login',
            'producao_lote_status', 'producao_lote_pendentes', 'config_lista', 'config_novo',
            'config_especialidades', 'config_importar', 'config_regras',
            'relatorios_home', 'profissionais_lista', 'equipes_lista', 'equipes_nova',
            'repasse_lote', 'repasse_lote_relatorio_excel',
        ]
        for nome in sem_args:
            r = self.client.get(reverse(f'siresp_app:{nome}'))
            self.assertIn(r.status_code, (200, 302), f'{nome} -> {r.status_code}')

        com_pk = [
            ('producao_ver_extracao', ext.pk), ('producao_exportar_csv', ext.pk),
            ('producao_exportar_json', ext.pk), ('producao_status_extracao', ext.pk),
            ('producao_ir_repasse', ext.pk), ('repasse_ver', rep.pk),
            ('config_editar', grupo.pk), ('config_editar_regra', reg.pk),
            ('equipes_editar', eq.pk),
        ]
        for nome, pk in com_pk:
            r = self.client.get(reverse(f'siresp_app:{nome}', args=[pk]))
            self.assertEqual(r.status_code in (200, 302), True, f'{nome} -> {r.status_code}')

        # com filtros e parâmetros
        for url in [
            reverse('siresp_app:home') + '?mes=13&ano=abc',          # inválidos
            reverse('siresp_app:relatorios_home') + '?medico=joao&competencia=zzz',
            reverse('siresp_app:relatorios_home') + '?competencia=2026-01',
            reverse('siresp_app:profissionais_lista') + '?mes=1&ano=2026&status=pendente',
            reverse('siresp_app:repasse_lote') + '?mes=0&ano=2026',
            reverse('siresp_app:repasse_lote_relatorio') + '?ids=abc',
            reverse('siresp_app:repasse_lote_relatorio') + '?mes=1&ano=2026',
            reverse('siresp_app:producao_lote_pendentes') + '?mes=99',
            reverse('siresp_app:config_regras') + '?q=joao',
        ]:
            r = self.client.get(url)
            self.assertIn(r.status_code, (200, 302), f'{url} -> {r.status_code}')


class RelatoriosTests(BaseTest):
    def test_filtro_por_competencia_e_equipe(self):
        from datetime import date
        eq = EquipeMedica.objects.create(nome='Clínica Alfa')
        Profissional.objects.create(nome='JOAO SILVA', nome_norm='JOAO SILVA', equipe=eq)
        ext = self.criar_extracao()
        rep = repasse_service.criar_repasses_lote(self.user, [ext])[0][0]
        rep.status = 'finalizado'
        rep.competencia = date(2026, 1, 1)
        rep.save()

        r = self.client.get(reverse('siresp_app:relatorios_home') + '?competencia=2026-01')
        self.assertEqual(len(r.context['repasses']), 1)
        self.assertEqual(r.context['repasses'][0].equipe.nome, 'Clínica Alfa')
        self.assertContains(r, 'Competência 01/2026')
        r = self.client.get(reverse('siresp_app:relatorios_home') + '?competencia=2026-02')
        self.assertEqual(len(r.context['repasses']), 0)


class CasamentoNomesTests(TestCase):
    def test_nomes_batem_por_palavras_inteiras(self):
        from .services.profissionais_service import _nomes_batem
        self.assertTrue(_nomes_batem('JOAO PEDRO SILVA', 'JOAO PEDRO SILVA'))
        self.assertTrue(_nomes_batem('JOAO PEDRO SILVA', 'JOAO PEDRO SILVA FILHO'))
        self.assertFalse(_nomes_batem('ANA LIMA SOUZA', 'MARIANA LIMA SOUZA'))
        self.assertTrue(_nomes_batem('ANA LIMA', 'ANA LIMA COSTA'))   # palavras inteiras, 8+ letras
        self.assertFalse(_nomes_batem('ANA', 'ANA LIMA COSTA'))       # curto demais


class LayoutTests(BaseTest):
    def test_menu_marca_ativo_e_erro_vira_danger(self):
        r = self.client.get(reverse('siresp_app:repasse_lote'))
        self.assertContains(r, 'active fw-bold')
        self.assertContains(r, 'Cadastros')
        self.assertNotContains(r, 'Histórico</a>')  # histórico agora fica dentro de Produção
        r = self.client.post(reverse('siresp_app:profissionais_novo'), {'nome': ''}, follow=True)
        self.assertContains(r, 'alert-danger')
        r = self.client.get(reverse('siresp_app:producao_home'))
        self.assertContains(r, 'Histórico de extrações')


class PdfEResumoExcelTests(BaseTest):
    def _montar(self):
        eq = EquipeMedica.objects.create(nome='Clínica Alfa & Cia')
        exts = []
        for n in ('ANA LIMA', 'BRUNO DIAS', 'DIOGO SOLO'):
            Profissional.objects.create(nome=n, nome_norm=n, equipe=eq if n != 'DIOGO SOLO' else None)
            RegraMinuto.objects.create(profissional_norm=n,
                                       especialidade_norm='CARDIOLOGIA', minutos=[30])
            e = Extracao.objects.create(usuario_web=self.user, medico_nome=n,
                                        data_ini='01/08/2026', data_fim='31/08/2026')
            ItemProducao.objects.create(extracao=e, especialidade='CARDIOLOGIA', ordem=0,
                                        dados={'Oferta_N': '40'})
            exts.append(e)
        repasse_service.criar_repasses_lote(self.user, exts)
        return exts

    def _finalizar(self, exts):
        self.client.post(reverse('siresp_app:repasse_lote_finalizar'), {
            'extracao_ids': [e.pk for e in exts],
            'competencia': competencia_padrao().strftime('%Y-%m')})
        return ','.join(str(r.pk) for r in Repasse.objects.all())

    def test_excel_lote_tem_resumo_de_equipe_no_fim(self):
        from io import BytesIO
        from openpyxl import load_workbook
        exts = self._montar()
        ids = self._finalizar(exts)
        xl = self.client.get(reverse('siresp_app:repasse_lote_relatorio_excel') + '?ids=' + ids)
        self.assertEqual(xl.status_code, 200)
        ws = load_workbook(BytesIO(xl.content))['Resumo do Lote']
        linhas = [r for r in ws.iter_rows(values_only=True) if any(v is not None for v in r)]
        nomes = [r[0] for r in linhas]
        ini = nomes.index('RESUMO POR FATURAMENTO (EQUIPES)')
        bloco = linhas[ini:]
        self.assertEqual(bloco[1][:4], ('Equipe / Profissional', 'Profissionais', 'Horas', 'Valor (R$)'))
        self.assertEqual(bloco[2][0], 'Clínica Alfa & Cia')
        self.assertEqual(bloco[2][1], 'ANA LIMA, BRUNO DIAS')
        self.assertEqual(bloco[2][2], 40.0)                 # 20h + 20h
        self.assertEqual(bloco[2][3], 10000.0)              # 40h x R$ 250 (grupo Cardio: 200 + 50)
        self.assertEqual(bloco[3][0], 'DIOGO SOLO')
        self.assertEqual(bloco[-1][0], 'TOTAL GERAL DO REPASSE')
        self.assertEqual(bloco[-1][3], 15000.0)             # equipe 10000 + Diogo 5000

    def test_pdf_lote_bloqueado_ate_finalizar_e_gera_depois(self):
        exts = self._montar()
        ids = ','.join(str(r.pk) for r in Repasse.objects.all())
        url = reverse('siresp_app:repasse_lote_relatorio_pdf') + '?ids=' + ids
        self.assertEqual(self.client.get(url).status_code, 302)        # rascunho: bloqueado
        self._finalizar(exts)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertGreater(len(r.content), 1500)

    def test_pdf_consolidado_relatorios(self):
        exts = self._montar()
        self._finalizar(exts)
        ids = [r.pk for r in Repasse.objects.all()]
        r = self.client.post(reverse('siresp_app:relatorios_gerar_pdf'), {'repasses': ids})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))
        # sem seleção volta com aviso
        r = self.client.post(reverse('siresp_app:relatorios_gerar_pdf'), {})
        self.assertEqual(r.status_code, 302)

    def test_excel_consolidado_resumo_nas_primeiras_colunas(self):
        from io import BytesIO
        from openpyxl import load_workbook
        exts = self._montar()
        self._finalizar(exts)
        ids = [r.pk for r in Repasse.objects.all()]
        xl = self.client.post(reverse('siresp_app:relatorios_gerar_excel'), {'repasses': ids})
        ws = load_workbook(BytesIO(xl.content)).worksheets[0]
        linhas = [r for r in ws.iter_rows(values_only=True) if any(v is not None for v in r)]
        i = [r[0] for r in linhas].index('RESUMO POR FATURAMENTO (EQUIPES)')
        bloco = linhas[i:]
        self.assertEqual(bloco[2][0], 'Clínica Alfa & Cia')
        self.assertEqual(bloco[2][3], 'ANA LIMA, BRUNO DIAS')   # coluna D: profissionais
        self.assertEqual(bloco[-1][0], 'TOTAL GERAL DO REPASSE')


class RelatoriosCoresTests(BaseTest):
    def test_lista_finalizado_verde_e_rascunho_amarelo(self):
        a = Extracao.objects.create(usuario_web=self.user, medico_nome='ANA LIMA',
                                    data_ini='01/08/2026', data_fim='31/08/2026')
        b = Extracao.objects.create(usuario_web=self.user, medico_nome='BRUNO DIAS',
                                    data_ini='01/08/2026', data_fim='31/08/2026')
        for e in (a, b):
            ItemProducao.objects.create(extracao=e, especialidade='CARDIOLOGIA', ordem=0,
                                        dados={'Oferta_N': '10'})
        repasse_service.criar_repasses_lote(self.user, [a, b])
        Repasse.objects.filter(extracao=a).update(status='finalizado',
                                                  competencia=competencia_padrao())

        r = self.client.get(reverse('siresp_app:relatorios_home'))
        self.assertContains(r, 'table-success', count=1)   # linha finalizada
        self.assertContains(r, 'table-warning', count=1)   # linha em rascunho
        self.assertEqual(r.context['qtd_finalizados'], 1)
        self.assertEqual(r.context['qtd_rascunhos'], 1)
        # rascunho não pode ser selecionado para Excel/PDF
        self.assertContains(r, 'disabled title="Finalize o repasse', count=1)

        r = self.client.get(reverse('siresp_app:relatorios_home') + '?situacao=rascunho')
        self.assertEqual([x.extracao.medico_nome for x in r.context['repasses']], ['BRUNO DIAS'])
        r = self.client.get(reverse('siresp_app:relatorios_home') + '?situacao=finalizado')
        self.assertEqual([x.extracao.medico_nome for x in r.context['repasses']], ['ANA LIMA'])

        # mesmo forçando o id do rascunho, o Excel só considera finalizados
        ids = [x.pk for x in Repasse.objects.all()]
        xl = self.client.post(reverse('siresp_app:relatorios_gerar_excel'), {'repasses': ids})
        self.assertEqual(xl.status_code, 200)
