"""Indicadores contábeis do painel inicial."""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from .models import EquipeMedica, Extracao, ItemProducao, Profissional, RegraMinuto, Repasse
from .services import dashboard_service, repasse_service
from .services.repasse_service import competencia_padrao
from .tests import BaseTest


class DashboardTests(BaseTest):
    """
    Cenário (grupo Cardio = R$ 250/h; grupo Padrão = R$ 140/h):
      Clínica Alfa: ANA (30 min x 60 ofertas = 30 h, Cardio) + BRUNO (60 min x 20 = 20 h, Cardio)
      Avulso:       DIOGO (30 min x 40 = 20 h, Cardio)   -> rascunho
      Anterior (07/2026): ANA 10 h finalizada
    """

    def _extracao(self, nome, oferta, ini, fim, atend='0'):
        e = Extracao.objects.create(usuario_web=self.user, medico_nome=nome,
                                    data_ini=ini, data_fim=fim)
        ItemProducao.objects.create(extracao=e, especialidade='CARDIOLOGIA', ordem=0,
                                    dados={'Oferta_N': str(oferta), 'Atend_Total_N': atend})
        return e

    def setUp(self):
        super().setUp()
        eq = EquipeMedica.objects.create(nome='Clínica Alfa')
        for nome, minutos, equipe in (('ANA LIMA', 30, eq), ('BRUNO DIAS', 60, eq), ('DIOGO SOLO', 30, None)):
            Profissional.objects.create(nome=nome, nome_norm=nome, equipe=equipe)
            RegraMinuto.objects.create(profissional_norm=nome, especialidade_norm='CARDIOLOGIA',
                                       minutos=[minutos])
        ana = self._extracao('ANA LIMA', 60, '01/08/2026', '31/08/2026', atend='55')
        bruno = self._extracao('BRUNO DIAS', 20, '01/08/2026', '31/08/2026', atend='18')
        diogo = self._extracao('DIOGO SOLO', 40, '01/08/2026', '31/08/2026', atend='30')
        jul = self._extracao('ANA LIMA', 20, '01/07/2026', '31/07/2026')   # 20*30/60 = 10 h
        repasse_service.criar_repasses_lote(self.user, [ana, bruno, diogo, jul])
        for nome, ext in (('ana', ana), ('bruno', bruno)):
            ok, _ = repasse_service.finalizar_repasse(Repasse.objects.get(extracao=ext),
                                                      date(2026, 8, 1))
            assert ok
        ok, _ = repasse_service.finalizar_repasse(Repasse.objects.get(extracao=jul), date(2026, 7, 1))
        assert ok

    def test_kpis_do_mes(self):
        fin = dashboard_service.dados_mes(Repasse.objects.all(), 2026, 8)
        self.assertEqual(fin['qtd_total'], 3)
        self.assertEqual((fin['qtd_fechados'], fin['qtd_abertos']), (2, 1))
        self.assertEqual(fin['horas_fechadas'], Decimal('50.00'))        # 30 + 20
        self.assertEqual(fin['valor_fechado'], Decimal('12500.00'))      # 50 x 250
        self.assertEqual(fin['valor_aberto'], Decimal('5000.00'))        # 20 x 250
        self.assertEqual(fin['valor_total'], Decimal('17500.00'))
        self.assertEqual(fin['horas_total'], Decimal('70.00'))
        self.assertEqual(fin['valor_medio_hora'], Decimal('250'))
        self.assertAlmostEqual(float(fin['ticket_medio']), 17500 / 3, places=2)
        self.assertEqual(fin['oferta'], 120)
        self.assertEqual(fin['atendimentos'], 103)
        self.assertAlmostEqual(fin['taxa_atendimento'], 103 * 100 / 120, places=4)
        self.assertAlmostEqual(fin['pct_fechado'], 12500 / 17500 * 100, places=3)

    def test_faturamento_por_equipe_e_avulso(self):
        fin = dashboard_service.dados_mes(Repasse.objects.all(), 2026, 8)
        fat = {f['nome']: f for f in fin['faturamento']}
        self.assertEqual(set(fat), {'Clínica Alfa', 'DIOGO SOLO'})
        self.assertTrue(fat['Clínica Alfa']['equipe'])
        self.assertEqual(fat['Clínica Alfa']['valor'], Decimal('12500.00'))
        self.assertEqual(sorted(fat['Clínica Alfa']['profissionais']), ['ANA LIMA', 'BRUNO DIAS'])
        self.assertFalse(fat['DIOGO SOLO']['equipe'])
        self.assertEqual(fin['qtd_equipes'], 1)
        self.assertEqual(fin['faturamento'][0]['nome'], 'Clínica Alfa')   # ordenado por valor

    def test_quebras_e_topos(self):
        fin = dashboard_service.dados_mes(Repasse.objects.all(), 2026, 8)
        self.assertEqual([g['nome'] for g in fin['por_grupo']], ['Cardio'])
        self.assertEqual(fin['por_grupo'][0]['valor'], Decimal('17500.00'))
        self.assertEqual(fin['por_grupo'][0]['pct_total'], 100.0)
        self.assertEqual(fin['top_especialidades'][0]['nome'], 'CARDIOLOGIA')
        self.assertEqual([p['nome'] for p in fin['top_profissionais']],
                         ['ANA LIMA', 'BRUNO DIAS', 'DIOGO SOLO'])        # 7500, 5000, 5000
        self.assertEqual(fin['top_profissionais'][0]['valor'], Decimal('7500.00'))

    def test_comparativo_com_mes_anterior(self):
        fin = dashboard_service.dados_mes(Repasse.objects.all(), 2026, 8)
        ant = fin['anterior']
        self.assertEqual(ant['rotulo'], '07/2026')
        self.assertEqual(ant['horas'], Decimal('10.00'))
        self.assertEqual(ant['valor'], Decimal('2500.00'))
        self.assertAlmostEqual(ant['var_valor'], (17500 - 2500) / 2500 * 100)   # +600%
        self.assertAlmostEqual(ant['var_horas'], 600.0)
        # sem base de comparação (mês anterior vazio) -> None, sem divisão por zero
        assert dashboard_service.dados_mes(Repasse.objects.all(), 2026, 7)['anterior']['var_valor'] is None

    def test_mes_sem_dados_nao_quebra(self):
        fin = dashboard_service.dados_mes(Repasse.objects.all(), 2020, 1)
        self.assertEqual(fin['valor_total'], Decimal('0'))
        self.assertEqual(fin['valor_medio_hora'], Decimal('0'))
        self.assertEqual(fin['taxa_atendimento'], 0)
        self.assertEqual(fin['faturamento'], [])
        r = self.client.get(reverse('siresp_app:home') + '?mes=1&ano=2020')
        self.assertEqual(r.status_code, 200)

    def test_evolucao_por_competencia(self):
        serie = dashboard_service.evolucao(Repasse.objects.all(), 2026, 8)
        self.assertEqual(len(serie), 6)
        self.assertEqual([s['rotulo'] for s in serie][-3:], ['06/2026', '07/2026', '08/2026'])
        por = {s['rotulo']: s for s in serie}
        self.assertEqual(por['08/2026']['valor'], Decimal('12500.00'))     # só finalizados
        self.assertEqual(por['07/2026']['valor'], Decimal('2500.00'))
        self.assertEqual(por['06/2026']['valor'], Decimal('0'))
        self.assertEqual(por['08/2026']['pct'], 100.0)
        self.assertTrue(por['08/2026']['atual'])
        # virada de ano
        jan = dashboard_service.evolucao(Repasse.objects.all(), 2026, 1)
        self.assertEqual(jan[-2]['rotulo'], '12/2025')

    def test_tela_mostra_os_numeros(self):
        r = self.client.get(reverse('siresp_app:home') + '?mes=8&ano=2026')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Indicadores de Agosto/2026')
        self.assertContains(r, '17.500,00')                # valor total (pt-BR, com milhar)
        self.assertContains(r, 'Clínica Alfa')
        self.assertContains(r, 'taxa de atendimento 85,8%')
        self.assertContains(r, '▲ 600,0%')

    def test_todos_veem_os_mesmos_indicadores(self):
        User.objects.create_user('operador', password='senha123')
        c = Client()
        c.login(username='operador', password='senha123')
        r = c.get(reverse('siresp_app:home') + '?mes=8&ano=2026')
        adm = self.client.get(reverse('siresp_app:home') + '?mes=8&ano=2026')
        self.assertEqual(r.context['fin']['qtd_total'], 3)           # vê repasses de outro usuário
        self.assertTrue(r.context['ver_todos'])
        for chave in ('valor_total', 'horas_total', 'valor_fechado', 'valor_aberto', 'oferta', 'atendimentos'):
            self.assertEqual(r.context['fin'][chave], adm.context['fin'][chave], chave)
        self.assertEqual(r.context['serie'], adm.context['serie'])
        self.assertEqual([f['nome'] for f in r.context['fin']['faturamento']],
                         [f['nome'] for f in adm.context['fin']['faturamento']])

    def test_barras_usam_css_valido(self):
        """Em pt-BR o decimal sai com vírgula (width: 70,5%), CSS inválido: barras ficariam vazias."""
        import re
        r = self.client.get(reverse('siresp_app:home') + '?mes=8&ano=2026')
        larguras = re.findall(r'(?:width|height):\s*([^;"%]+)%', r.content.decode('utf-8'))
        self.assertTrue(larguras)
        for v in larguras:
            self.assertRegex(v.strip(), r'^\d+$', f'valor CSS inválido: {v!r}')


class FaturamentoLimitadoTests(BaseTest):
    """25 profissionais avulsos + 1 equipe de valor pequeno: só as 10 maiores linhas ficam abertas."""

    def setUp(self):
        super().setUp()
        self.eq = EquipeMedica.objects.create(nome='Equipe Pequena')
        Profissional.objects.create(nome='MEMBRO EQUIPE', nome_norm='MEMBRO EQUIPE', equipe=self.eq)
        nomes = [f'MEDICO {i:02d}' for i in range(1, 26)] + ['MEMBRO EQUIPE']
        exts = []
        for i, nome in enumerate(nomes):
            RegraMinuto.objects.create(profissional_norm=nome, especialidade_norm='CARDIOLOGIA', minutos=[60])
            oferta = 100 - i * 3 if nome != 'MEMBRO EQUIPE' else 1      # a equipe é a menor de todas
            e = Extracao.objects.create(usuario_web=self.user, medico_nome=nome,
                                        data_ini='01/08/2026', data_fim='31/08/2026')
            ItemProducao.objects.create(extracao=e, especialidade='CARDIOLOGIA', ordem=0,
                                        dados={'Oferta_N': str(oferta)})
            exts.append(e)
        repasse_service.criar_repasses_lote(self.user, exts)

    def test_so_as_maiores_ficam_visiveis_e_equipe_nunca_some(self):
        fin = dashboard_service.dados_mes(Repasse.objects.all(), 2026, 8)
        fat = fin['faturamento']
        self.assertEqual(len(fat), 26)
        visiveis = [f for f in fat if not f['extra']]
        self.assertEqual(len(visiveis), 11)                  # 10 maiores + a equipe (menor valor, mas sempre visível)
        self.assertEqual(fin['faturamento_extra'], 15)
        self.assertTrue(any(f['equipe'] and not f['extra'] for f in fat))
        ocultos = [f for f in fat if f['extra']]
        self.assertTrue(all(not f['equipe'] for f in ocultos))
        # ordem decrescente preservada: todo oculto vale menos ou igual ao menor avulso visível
        menor_visivel = min(f['valor'] for f in visiveis if not f['equipe'])
        self.assertTrue(all(f['valor'] <= menor_visivel for f in ocultos))

    def test_tela_tem_botoes_de_carregar_e_linhas_ocultas(self):
        r = self.client.get(reverse('siresp_app:home') + '?mes=8&ano=2026')
        html = r.content.decode('utf-8')
        self.assertEqual(html.count('d-none linha-extra'), 15)     # 15 linhas renderizadas ocultas
        self.assertIn('Carregar mais 10', html)
        self.assertIn('Carregar todos (15 restantes)', html)

    def test_poucos_profissionais_nao_mostram_botoes(self):
        Repasse.objects.filter(extracao__medico_nome__gte='MEDICO 06',
                               extracao__medico_nome__lte='MEDICO 25').delete()
        r = self.client.get(reverse('siresp_app:home') + '?mes=8&ano=2026')
        self.assertNotContains(r, 'Carregar mais 10')
        self.assertEqual(r.context['fin']['faturamento_extra'], 0)
