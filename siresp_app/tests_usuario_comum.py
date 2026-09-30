"""
Validação completa do usuário comum (ex.: o usuário "teste").

Princípio: vê as MESMAS telas e dados do administrador; só não tem o DIREITO
de alterar cadastros, reabrir repasses ou gerir usuários.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from .models import (
    EquipeMedica, Extracao, GrupoValor, ItemProducao, LogAuditoria, Profissional,
    RegraMinuto, Repasse,
)
from .services import repasse_service
from .services.repasse_service import competencia_padrao
from .tests_papeis import PapeisBase


class UsuarioComumCompleto(PapeisBase):
    """
    self.user  = admin (dono dos dados de 'outros');  self.comum = usuário comum.
    Cenário: o admin tem uma equipe, regras, grupos e um repasse finalizado + um rascunho.
    """

    def setUp(self):
        super().setUp()
        self.eq = EquipeMedica.objects.create(nome='Clínica Alfa')
        Profissional.objects.create(nome='JOAO SILVA', nome_norm='JOAO SILVA', equipe=self.eq)
        Profissional.objects.create(nome='MARIA SOUZA', nome_norm='MARIA SOUZA')
        self.rep_fin = self._repasse(self.user, finalizar=True)          # JOAO SILVA, finalizado
        ext = Extracao.objects.create(usuario_web=self.user, medico_nome='MARIA SOUZA',
                                      data_ini='01/01/2026', data_fim='31/01/2026')
        ItemProducao.objects.create(extracao=ext, especialidade='NEURO', ordem=0,
                                    dados={'Oferta_N': '10'})
        RegraMinuto.objects.create(profissional_norm='MARIA SOUZA',
                                   especialidade_norm='NEURO', minutos=[20])
        self.rep_rasc = repasse_service.criar_repasses_lote(self.user, [ext])[0][0]

    # ------------------------------------------------------------------ LEITURA
    def test_telas_de_consulta_abrem_para_o_comum(self):
        paginas = [
            ('home', None), ('producao_home', None), ('producao_historico', None),
            ('repasse_lote', None), ('relatorios_home', None), ('profissionais_lista', None),
            ('equipes_lista', None), ('config_lista', None), ('config_regras', None),
            ('config_especialidades', None), ('config_importar', None),
            ('auditoria_lista', None), ('auditoria_csv', None),
            ('repasse_ver', self.rep_fin.pk), ('repasse_ver', self.rep_rasc.pk),
        ]
        for nome, pk in paginas:
            url = reverse(f'siresp_app:{nome}', args=[pk] if pk else None)
            self.assertEqual(self.c_comum.get(url).status_code, 200, nome)
            self.assertEqual(self.client.get(url).status_code, 200, nome)

    def test_comum_ve_o_mesmo_conteudo_do_admin(self):
        def contexto(cli, nome, chave, **query):
            qs = '?' + '&'.join(f'{k}={v}' for k, v in query.items()) if query else ''
            return cli.get(reverse(f'siresp_app:{nome}') + qs).context[chave]

        ids = lambda lista: sorted(getattr(x, 'pk', x) for x in lista)
        for chave, nome in (('grupos', 'config_lista'), ('regras', 'config_regras'),
                            ('repasses', 'relatorios_home'), ('situacoes', 'profissionais_lista'),
                            ('equipes', 'equipes_lista')):
            a = contexto(self.client, nome, chave)
            c = contexto(self.c_comum, nome, chave)
            tam = lambda x: len(list(x))
            self.assertEqual(tam(a), tam(c), f'{nome}.{chave}')
            self.assertGreater(tam(c), 0, f'{nome}.{chave} vazio para o comum')

        fin_a = contexto(self.client, 'home', 'fin', mes=1, ano=2026)
        fin_c = contexto(self.c_comum, 'home', 'fin', mes=1, ano=2026)
        self.assertEqual(fin_c['qtd_total'], 2)
        for k in ('valor_total', 'horas_total', 'valor_fechado', 'valor_aberto'):
            self.assertEqual(fin_a[k], fin_c[k], k)

        log_a = self.client.get(reverse('siresp_app:auditoria_lista')).context['pagina']
        log_c = self.c_comum.get(reverse('siresp_app:auditoria_lista')).context['pagina']
        self.assertEqual(len(log_a), len(log_c))

    def test_comum_nao_ve_controles_de_alteracao_que_o_admin_ve(self):
        # (url, texto que só o admin vê)
        controles = [
            (reverse('siresp_app:config_lista'), ['Novo Grupo', 'Excluir selecionados', 'Excluir todos']),
            (reverse('siresp_app:config_regras'), ['Nova Regra', 'Limpar Tudo', 'modalNovaRegra']),
            (reverse('siresp_app:config_importar'), ['type="file"']),
            (reverse('siresp_app:config_especialidades'), ['Adicionar especialidade']),
            (reverse('siresp_app:equipes_lista'), ['Nova equipe', 'Remover']),
            (reverse('siresp_app:profissionais_lista'), ['Adicionar à base']),
            (reverse('siresp_app:relatorios_home'), ['Reabrir selecionados']),
            (reverse('siresp_app:repasse_ver', args=[self.rep_fin.pk]), ['Reabrir (admin)']),
        ]
        for url, textos in controles:
            comum = self.c_comum.get(url).content.decode('utf-8')
            admin = self.client.get(url).content.decode('utf-8')
            for t in textos:
                self.assertNotIn(t, comum, f'{url}: comum não deveria ver {t!r}')
                self.assertIn(t, admin, f'{url}: admin deveria ver {t!r}')

    # ------------------------------------------------------------------ ESCRITA BLOQUEADA
    def test_comum_nao_consegue_alterar_nenhum_cadastro(self):
        grupo = GrupoValor.objects.first()
        regra = RegraMinuto.objects.first()
        prof = Profissional.objects.first()
        foto = lambda: (GrupoValor.objects.count(), RegraMinuto.objects.count(),
                        Profissional.objects.count(), EquipeMedica.objects.count(),
                        Repasse.objects.filter(status='finalizado').count(),
                        LogAuditoria.objects.exclude(acao__in=['LOGIN', 'LOGOUT']).count())
        antes = foto()
        nome_grupo = grupo.nome

        posts = [
            ('config_novo', None, {'nome': 'Hack', 'valor_base': '1', 'bonus': '1'}),
            ('config_editar', grupo.pk, {'nome': 'Hack', 'valor_base': '1', 'bonus': '1'}),
            ('config_remover', grupo.pk, {}),
            ('config_excluir_grupos', None, {'todos': '1'}),
            ('config_limpar_regras', None, {}),
            ('config_nova_regra', None, {'profissional': 'A', 'especialidade': 'B', 'minutos': '5'}),
            ('config_editar_regra', regra.pk, {'profissional': 'A', 'especialidade': 'B', 'minutos': '5'}),
            ('config_deletar_regra', regra.pk, {}),
            ('config_nova_esp', None, {'nome': 'Hack'}),
            ('config_importar', None, {}),
            ('equipes_nova', None, {'nome': 'Hack'}),
            ('equipes_editar', self.eq.pk, {'nome': 'Hack'}),
            ('equipes_remover', self.eq.pk, {}),
            ('profissionais_novo', None, {'nome': 'Hack'}),
            ('profissionais_alternar', prof.pk, {}),
            ('profissionais_remover', prof.pk, {}),
            ('relatorios_reabrir_varios', None, {'repasses': [self.rep_fin.pk], 'motivo': 'tentativa do comum'}),
        ]
        for nome, pk, dados in posts:
            r = self.c_comum.post(reverse(f'siresp_app:{nome}', args=[pk] if pk else None), dados)
            self.assertIn(r.status_code, (302, 403), f'{nome} -> {r.status_code}')
        r = self.c_comum.post(reverse('siresp_app:repasse_reabrir', args=[self.rep_fin.pk]),
                              data={'motivo': 'tentativa do comum'}, content_type='application/json')
        self.assertEqual(r.status_code, 403)

        self.assertEqual(foto(), antes)                 # nada mudou, nada foi logado
        grupo.refresh_from_db()
        self.assertEqual(grupo.nome, nome_grupo)
        self.rep_fin.refresh_from_db()
        self.assertEqual(self.rep_fin.status, 'finalizado')

    def test_comum_nao_altera_repasse_de_outro_usuario(self):
        item = self.rep_rasc.itens.get()
        antes = (item.valor_base, item.minutos, item.marcado)
        chamadas = [
            ('repasse_atualizar_item', item.pk, {'campo': 'valor_base', 'valor': '999'}),
            ('repasse_marcar_todas', self.rep_rasc.pk, {'marcar': True}),
            ('repasse_arredondar', self.rep_rasc.pk, {'modo': 'cima'}),
            ('repasse_recalcular', self.rep_rasc.pk, {}),
            ('repasse_zerar', self.rep_rasc.pk, {}),
            ('repasse_escolher_minuto', item.pk, {'minutos': 99}),
            ('repasse_finalizar', self.rep_rasc.pk, {'competencia': competencia_padrao().strftime('%Y-%m')}),
        ]
        for nome, pk, corpo in chamadas:
            r = self.c_comum.post(reverse(f'siresp_app:{nome}', args=[pk]), data=corpo,
                                  content_type='application/json')
            self.assertEqual(r.status_code, 404, nome)
        r = self.c_comum.post(reverse('siresp_app:repasse_lote_salvar'), data={'itens': [
            {'id': item.pk, 'valor_base': 999, 'marcado': False}]}, content_type='application/json').json()
        self.assertEqual(r['salvos'], 0)                # a linha de outro usuário é ignorada
        item.refresh_from_db()
        self.rep_rasc.refresh_from_db()
        self.assertEqual((item.valor_base, item.minutos, item.marcado), antes)
        self.assertEqual(self.rep_rasc.status, 'rascunho')
        self.assertFalse(LogAuditoria.objects.filter(acao='REPASSE_EDITADO').exists())

    # ------------------------------------------------------------------ FLUXO PRÓPRIO
    def test_comum_executa_o_proprio_fluxo_do_mes(self):
        # extração própria (o scraper é simulado em outros testes)
        ext = Extracao.objects.create(usuario_web=self.comum, medico_nome='PEDRO LIMA',
                                      data_ini='01/01/2026', data_fim='31/01/2026')
        ItemProducao.objects.create(extracao=ext, especialidade='CARDIOLOGIA', ordem=0,
                                    dados={'Oferta_N': '60', 'Atend_Total_N': '50'})
        RegraMinuto.objects.create(profissional_norm='PEDRO LIMA',
                                   especialidade_norm='CARDIOLOGIA', minutos=[30])
        c = self.c_comum

        # tela de repasse em lote lista a extração e gera o repasse
        r = c.get(reverse('siresp_app:repasse_lote') + '?mes=1&ano=2026')
        self.assertIn('PEDRO LIMA', [l['ext'].medico_nome for l in r.context['linhas']])
        r = c.post(reverse('siresp_app:repasse_lote_gerar'), {'extracao_ids': [ext.pk]})
        self.assertEqual(r.status_code, 302)
        rep = Repasse.objects.get(extracao=ext)
        self.assertEqual(rep.usuario_web, self.comum)
        self.assertEqual(rep.itens.filter(marcado=True).count(), 1)     # marcação automática por regra

        # edita pelo relatório do lote e salva (sem finalizar)
        item = rep.itens.get()
        r = c.post(reverse('siresp_app:repasse_lote_salvar'), data={'itens': [
            {'id': item.pk, 'valor_base': '200', 'bonus_cheio': '50', 'bonus_percent': '100%'}]},
            content_type='application/json').json()
        self.assertTrue(r['ok'], r)
        item.refresh_from_db()
        self.assertEqual(item.valor_hora, Decimal('250.00'))
        self.assertEqual(Repasse.objects.get(pk=rep.pk).status, 'rascunho')

        # exportar antes de finalizar é bloqueado; depois de finalizar libera
        url_xl = reverse('siresp_app:repasse_lote_relatorio_excel') + f'?ids={rep.pk}'
        url_pdf = reverse('siresp_app:repasse_lote_relatorio_pdf') + f'?ids={rep.pk}'
        self.assertEqual(c.get(url_xl).status_code, 302)
        self.assertEqual(c.get(url_pdf).status_code, 302)
        r = c.post(reverse('siresp_app:repasse_lote_finalizar'), {
            'extracao_ids': [ext.pk], 'competencia': competencia_padrao().strftime('%Y-%m')})
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'finalizado')
        self.assertEqual(c.get(url_xl).status_code, 200)
        pdf = c.get(url_pdf)
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.assertEqual(c.get(reverse('siresp_app:repasse_excel', args=[rep.pk])).status_code, 200)

        # relatórios: Excel/PDF consolidados incluem os repasses finalizados de qualquer usuário
        ids = [self.rep_fin.pk, rep.pk]
        self.assertEqual(c.post(reverse('siresp_app:relatorios_gerar_excel'), {'repasses': ids}).status_code, 200)
        self.assertEqual(c.post(reverse('siresp_app:relatorios_gerar_pdf'), {'repasses': ids}).status_code, 200)

        # o que o comum fez ficou auditado com o nome dele
        usuarios = set(LogAuditoria.objects.filter(repasse_id=rep.pk).values_list('usuario_nome', flat=True))
        self.assertEqual(usuarios, {'operador'})
        self.assertTrue(LogAuditoria.objects.filter(acao='REPASSE_FINALIZADO', repasse_id=rep.pk).exists())

        # e só o admin consegue reabrir o que o comum finalizou
        url = reverse('siresp_app:repasse_reabrir', args=[rep.pk])
        self.assertEqual(c.post(url, data={'motivo': 'quero mexer'}, content_type='application/json').status_code, 403)
        self.assertTrue(self.client.post(url, data={'motivo': 'Correção de competência'},
                                         content_type='application/json').json()['ok'])
        rep.refresh_from_db()
        self.assertEqual(rep.status, 'rascunho')

    def test_comum_gerencia_as_proprias_extracoes_e_pendentes(self):
        ext = Extracao.objects.create(usuario_web=self.comum, medico_nome='PEDRO LIMA',
                                      data_ini='01/01/2026', data_fim='31/01/2026')
        outra = self.rep_fin.extracao                      # do admin
        r = self.c_comum.post(reverse('siresp_app:producao_excluir_extracao', args=[outra.pk]))
        self.assertEqual(r.status_code, 404)               # não apaga extração alheia
        self.assertTrue(Extracao.objects.filter(pk=outra.pk).exists())
        r = self.c_comum.post(reverse('siresp_app:producao_excluir_extracao', args=[ext.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Extracao.objects.filter(pk=ext.pk).exists())

        r = self.c_comum.get(reverse('siresp_app:producao_lote_pendentes')
                             + '?data_ini=01/01/2026&data_fim=31/01/2026').json()
        self.assertTrue(r['ok'])
        # o comum ainda não extraiu ninguém: ambos os profissionais da base estão pendentes para ele
        self.assertEqual(sorted(r['nomes']), ['JOAO SILVA', 'MARIA SOUZA'])

    def test_comum_precisa_de_sessao_siresp_para_extrair(self):
        r = self.c_comum.post(reverse('siresp_app:producao_lote_iniciar'), data={
            'nomes': ['X'], 'data_ini': '01/01/2026', 'data_fim': '31/01/2026'},
            content_type='application/json').json()
        self.assertFalse(r['ok'])

    def test_comum_nao_autenticado_vai_para_login(self):
        anon = Client()
        for nome in ('home', 'relatorios_home', 'config_lista', 'auditoria_lista',
                     'repasse_lote', 'profissionais_lista'):
            r = anon.get(reverse(f'siresp_app:{nome}'))
            self.assertEqual(r.status_code, 302, nome)
            self.assertIn('/login/', r.url)

    def test_usuario_desativado_nao_entra(self):
        self.comum.is_active = False
        self.comum.save()
        c = Client()
        r = c.post(reverse('siresp_app:login'), {'usuario': 'operador', 'senha': 'senha123'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get(reverse('siresp_app:home')).status_code, 302)
        self.assertTrue(LogAuditoria.objects.filter(acao='LOGIN_FALHA', usuario_nome='operador').exists())


class ExtracoesDeOutrosUsuarios(PapeisBase):
    """Regressão: abrir /producao/ver/<id>/ de uma extração de outro usuário dava 404."""

    def setUp(self):
        super().setUp()
        self.rep = self._repasse(self.user, finalizar=True)           # extração + repasse do admin
        self.ext = self.rep.extracao

    def test_extracao_de_outro_usuario_abre_em_modo_consulta(self):
        r = self.c_comum.get(reverse('siresp_app:producao_ver_extracao', args=[self.ext.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['outro_dono'])
        self.assertContains(r, 'Modo consulta')
        self.assertContains(r, 'Ver repasse')                        # leva ao repasse existente
        self.assertNotContains(r, 'Usar no Repasse')
        self.assertEqual(self.c_comum.get(reverse('siresp_app:producao_exportar_csv', args=[self.ext.pk])).status_code, 200)
        self.assertEqual(self.c_comum.get(reverse('siresp_app:producao_exportar_json', args=[self.ext.pk])).status_code, 200)
        # o dono continua vendo o botão de gerar repasse
        r = self.client.get(reverse('siresp_app:producao_ver_extracao', args=[self.ext.pk]))
        self.assertFalse(r.context['outro_dono'])
        self.assertContains(r, 'Usar no Repasse')

    def test_extracao_inexistente_continua_404(self):
        self.assertEqual(self.c_comum.get(reverse('siresp_app:producao_ver_extracao', args=[999999])).status_code, 404)

    def test_historico_lista_todos_e_so_o_dono_seleciona(self):
        minha = Extracao.objects.create(usuario_web=self.comum, medico_nome='PEDRO LIMA',
                                        data_ini='01/01/2026', data_fim='31/01/2026')
        r = self.c_comum.get(reverse('siresp_app:producao_historico'))
        linhas = {l['obj'].pk: l for l in r.context['extracoes']}
        self.assertEqual(set(linhas), {self.ext.pk, minha.pk})       # vê as do admin e as suas
        self.assertTrue(linhas[minha.pk]['dono'])
        self.assertFalse(linhas[self.ext.pk]['dono'])
        html = r.content.decode('utf-8')
        self.assertEqual(html.count('name="extracao_ids"'), 1)       # checkbox só na própria
        # e não consegue excluir a alheia, nem em lote
        self.c_comum.post(reverse('siresp_app:producao_excluir_varias'),
                          {'extracao_ids': [self.ext.pk, minha.pk]})
        self.assertTrue(Extracao.objects.filter(pk=self.ext.pk).exists())
        self.assertFalse(Extracao.objects.filter(pk=minha.pk).exists())

    def test_abrir_repasse_de_extracao_alheia(self):
        # com repasse existente: vai para ele
        r = self.c_comum.get(reverse('siresp_app:producao_ir_repasse', args=[self.ext.pk]))
        self.assertRedirects(r, reverse('siresp_app:repasse_ver', args=[self.rep.pk]))
        # sem repasse: não cria, avisa e volta para a extração
        sem = Extracao.objects.create(usuario_web=self.user, medico_nome='SEM REPASSE',
                                      data_ini='01/01/2026', data_fim='31/01/2026')
        r = self.c_comum.get(reverse('siresp_app:producao_ir_repasse', args=[sem.pk]))
        self.assertRedirects(r, reverse('siresp_app:producao_ver_extracao', args=[sem.pk]))
        self.assertFalse(Repasse.objects.filter(extracao=sem).exists())

    def test_relatorio_do_lote_de_outro_usuario_em_consulta(self):
        rascunho = self._repasse(self.user)              # rascunho do admin (2ª extração)
        ids = f'{self.rep.pk},{rascunho.pk}'
        r = self.c_comum.get(reverse('siresp_app:repasse_lote_relatorio') + f'?ids={ids}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context['blocos']), 2)
        self.assertTrue(all(b['bloqueado'] and b['outro_dono'] for b in r.context['blocos']))
        html = r.content.decode('utf-8')
        self.assertNotIn('name="extracao_ids"', html)    # nada para finalizar: nenhum rascunho é dele
        self.assertIn('disabled', html)
        # tentar salvar/finalizar linha alheia não altera nada
        item = rascunho.itens.get()
        res = self.c_comum.post(reverse('siresp_app:repasse_lote_salvar'), data={'itens': [
            {'id': item.pk, 'valor_base': 1}]}, content_type='application/json').json()
        self.assertEqual(res['salvos'], 0)
        self.c_comum.post(reverse('siresp_app:repasse_lote_finalizar'), {
            'extracao_ids': [rascunho.extracao.pk], 'competencia': competencia_padrao().strftime('%Y-%m')})
        rascunho.refresh_from_db()
        self.assertEqual(rascunho.status, 'rascunho')
