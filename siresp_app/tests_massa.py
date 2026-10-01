"""Ações em massa na base de profissionais."""
from django.urls import reverse

from .models import EquipeMedica, LogAuditoria, Profissional
from .tests_papeis import PapeisBase


class AcaoEmMassaTests(PapeisBase):
    def setUp(self):
        super().setUp()
        self.alfa = EquipeMedica.objects.create(nome='Clínica Alfa')
        self.beta = EquipeMedica.objects.create(nome='Clínica Beta')
        self.p = {n: Profissional.objects.create(nome=n, nome_norm=n)
                  for n in ('ANA LIMA', 'BRUNO DIAS', 'CARLA MELO', 'DIOGO SOLO')}
        self.p['BRUNO DIAS'].equipe = self.beta
        self.p['BRUNO DIAS'].save()
        self.url = reverse('siresp_app:profissionais_massa')

    def ids(self, *nomes):
        return [self.p[n].pk for n in nomes]

    def post(self, cliente=None, **dados):
        dados.setdefault('mes', 8)
        dados.setdefault('ano', 2026)
        return (cliente or self.client).post(self.url, dados)

    def test_desativar_e_reativar_varios(self):
        r = self.post(acao='desativar', ids=self.ids('ANA LIMA', 'CARLA MELO'), status='pendente')
        self.assertRedirects(r, reverse('siresp_app:profissionais_lista') + '?mes=8&ano=2026&status=pendente',
                             fetch_redirect_response=False)
        self.assertEqual(sorted(Profissional.objects.filter(ativo=False).values_list('nome', flat=True)),
                         ['ANA LIMA', 'CARLA MELO'])
        log = LogAuditoria.objects.get(acao='PROFISSIONAL_ALTERADO')
        self.assertIn('2 profissional(is) desativados', log.descricao)
        self.assertEqual({(d['item'], d['de'], d['para']) for d in log.detalhes},
                         {('ANA LIMA', 'ativo', 'desativado'), ('CARLA MELO', 'ativo', 'desativado')})
        # a lista (só ativos) deixa de mostrá-los; a de desativados aparece
        pagina = self.client.get(reverse('siresp_app:profissionais_lista') + '?mes=8&ano=2026')
        self.assertEqual(sorted(s['profissional'].nome for s in pagina.context['situacoes']),
                         ['BRUNO DIAS', 'DIOGO SOLO'])
        self.assertContains(pagina, 'Desativados (2)')
        # reativar
        self.post(acao='reativar', ids=self.ids('ANA LIMA', 'CARLA MELO'))
        self.assertEqual(Profissional.objects.filter(ativo=False).count(), 0)

    def test_mover_para_equipe_registra_de_para_e_tirar_da_equipe(self):
        self.post(acao='equipe', equipe_id=self.alfa.pk, ids=self.ids('ANA LIMA', 'BRUNO DIAS', 'CARLA MELO'))
        for n in ('ANA LIMA', 'BRUNO DIAS', 'CARLA MELO'):
            self.p[n].refresh_from_db()
            self.assertEqual(self.p[n].equipe, self.alfa)               # Bruno saiu da Beta
        detalhes = {d['item']: (d['de'], d['para']) for d in LogAuditoria.objects.get().detalhes}
        self.assertEqual(detalhes['BRUNO DIAS'], ('Clínica Beta', 'Clínica Alfa'))
        self.assertEqual(detalhes['ANA LIMA'], ('(nenhuma)', 'Clínica Alfa'))
        # tirar da equipe
        self.post(acao='sem_equipe', ids=self.ids('ANA LIMA', 'DIOGO SOLO'))     # Diogo já estava sem equipe
        self.p['ANA LIMA'].refresh_from_db()
        self.assertIsNone(self.p['ANA LIMA'].equipe)
        self.assertEqual(self.alfa.membros.count(), 2)
        ultimo = LogAuditoria.objects.first()
        self.assertEqual([d['item'] for d in ultimo.detalhes], ['ANA LIMA'])     # só quem mudou

    def test_remover_varios(self):
        self.post(acao='remover', ids=self.ids('ANA LIMA', 'DIOGO SOLO'))
        self.assertEqual(sorted(Profissional.objects.values_list('nome', flat=True)), ['BRUNO DIAS', 'CARLA MELO'])
        self.assertIn('removidos da base', LogAuditoria.objects.get().descricao)

    def test_sem_mudanca_nao_gera_log(self):
        self.post(acao='reativar', ids=self.ids('ANA LIMA'))        # já estava ativo
        self.assertFalse(LogAuditoria.objects.filter(acao='PROFISSIONAL_ALTERADO').exists())

    def test_entradas_invalidas_nao_quebram_nem_alteram(self):
        antes = list(Profissional.objects.values_list('pk', 'ativo', 'equipe_id'))
        casos = [
            dict(acao='', ids=self.ids('ANA LIMA')),                          # sem ação
            dict(acao='apagar_tudo', ids=self.ids('ANA LIMA')),               # ação inexistente
            dict(acao='desativar'),                                           # nada marcado
            dict(acao='desativar', ids=['abc']),                              # id inválido
            dict(acao='equipe', ids=self.ids('ANA LIMA')),                    # sem equipe de destino
            dict(acao='equipe', equipe_id=99999, ids=self.ids('ANA LIMA')),   # equipe inexistente
            dict(acao='desativar', ids=[999999]),                             # profissional inexistente
        ]
        for dados in casos:
            r = self.post(**dados)
            self.assertEqual(r.status_code, 302, dados)
        self.assertEqual(list(Profissional.objects.values_list('pk', 'ativo', 'equipe_id')), antes)
        self.assertFalse(LogAuditoria.objects.filter(acao='PROFISSIONAL_ALTERADO').exists())

    def test_redirect_ignora_valores_estranhos(self):
        r = self.post(acao='desativar', ids=self.ids('ANA LIMA'), mes='13', ano='x', status='http://evil')
        self.assertEqual(r.url, reverse('siresp_app:profissionais_lista'))
        r = self.post(acao='desativar', ids=self.ids('CARLA MELO'), status='http://evil')
        self.assertEqual(r.url, reverse('siresp_app:profissionais_lista') + '?mes=8&ano=2026')

    def test_usuario_comum_nao_executa_acao_em_massa(self):
        antes = list(Profissional.objects.values_list('pk', 'ativo', 'equipe_id'))
        for acao in ('desativar', 'remover', 'equipe', 'sem_equipe'):
            r = self.post(self.c_comum, acao=acao, equipe_id=self.alfa.pk, ids=self.ids('ANA LIMA'))
            self.assertRedirects(r, reverse('siresp_app:home'), fetch_redirect_response=False)
        r = self.c_comum.post(reverse('siresp_app:profissionais_adicionar_varios'), {'nomes': 'FULANO'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(list(Profissional.objects.values_list('pk', 'ativo', 'equipe_id')), antes)
        self.assertEqual(Profissional.objects.count(), 4)

    def test_adicionar_varios(self):
        url = reverse('siresp_app:profissionais_adicionar_varios')
        r = self.client.post(url, {'mes': 8, 'ano': 2026,
                                   'nomes': 'NOVO UM\n\n  novo dois  \nANA LIMA\nnovo um\n'})
        self.assertEqual(r.status_code, 302)
        nomes = set(Profissional.objects.values_list('nome_norm', flat=True))
        self.assertTrue({'NOVO UM', 'NOVO DOIS'} <= nomes)
        self.assertEqual(Profissional.objects.count(), 6)               # 2 novos; ANA LIMA e "novo um" repetidos
        log = LogAuditoria.objects.get()
        self.assertIn('2 profissional(is) adicionados', log.descricao)
        # vazio
        self.client.post(url, {'nomes': '  \n \n'})
        self.assertEqual(Profissional.objects.count(), 6)

    def test_tela_mostra_controles_so_para_admin(self):
        url = reverse('siresp_app:profissionais_lista') + '?mes=8&ano=2026'
        admin = self.client.get(url).content.decode('utf-8')
        comum = self.c_comum.get(url).content.decode('utf-8')
        for trecho in ('name="ids"', 'id="acao"', 'Mover para a equipe', 'Adicionar todos', 'id="marcar-todos"'):
            self.assertIn(trecho, admin, trecho)
            self.assertNotIn(trecho, comum, trecho)
        self.assertIn('Clínica Beta', admin)                            # coluna de equipe visível para todos
        self.assertIn('Clínica Beta', comum)
