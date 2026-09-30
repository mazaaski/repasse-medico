"""
Indicadores para o painel inicial (visão contábil).

Base: repasses cujo período de produção cruza o mês escolhido.
Só entram linhas marcadas (as que realmente compõem o repasse).
Valores "fechados" = repasses finalizados; "em aberto" = rascunhos.
"""
import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal

from .profissionais_service import _parse_data, equipe_por_medico

ZERO = Decimal('0')
LIMITE_FATURAMENTO = 10   # linhas visíveis de início na tabela de faturamento


def _mes_anterior(ano, mes):
    return (ano - 1, 12) if mes == 1 else (ano, mes - 1)


def _repasses_do_mes(qs, ano, mes):
    primeiro = date(ano, mes, 1)
    ultimo = date(ano, mes, calendar.monthrange(ano, mes)[1])
    saida = []
    for r in qs.select_related('extracao', 'usuario_web'):
        ini, fim = _parse_data(r.extracao.data_ini), _parse_data(r.extracao.data_fim)
        if ini and fim and ini <= ultimo and fim >= primeiro:
            saida.append(r)
    return saida


def _totais(repasses):
    fech = [r for r in repasses if r.finalizado]
    aberto = [r for r in repasses if not r.finalizado]
    soma = lambda lista, campo: sum((getattr(r, campo) for r in lista), ZERO)
    return {
        'qtd_total': len(repasses),
        'qtd_fechados': len(fech),
        'qtd_abertos': len(aberto),
        'valor_fechado': soma(fech, 'valor_total_final'),
        'valor_aberto': soma(aberto, 'valor_total_final'),
        'horas_fechadas': soma(fech, 'horas_total_final'),
        'horas_abertas': soma(aberto, 'horas_total_final'),
    }


def _variacao(atual, anterior):
    """Variação percentual; None quando não há base de comparação."""
    if not anterior:
        return None
    return float((atual - anterior) / anterior * 100)


def dados_mes(qs, ano, mes):
    """
    qs: queryset de Repasse já filtrado por visibilidade (usuário/admin).
    Retorna dict com KPIs, quebras e comparativo com o mês anterior.
    """
    from ..models import ItemRepasse

    repasses = _repasses_do_mes(qs, ano, mes)
    tot = _totais(repasses)
    valor_total = tot['valor_fechado'] + tot['valor_aberto']
    horas_total = tot['horas_fechadas'] + tot['horas_abertas']

    # ---- itens marcados (base das quebras por grupo/especialidade)
    itens = list(ItemRepasse.objects.filter(repasse__in=repasses, marcado=True)
                 .select_related('repasse__extracao'))
    oferta = sum(i.oferta for i in itens)
    atend = sum(i.atendimentos for i in itens)

    por_grupo = defaultdict(lambda: {'horas': ZERO, 'valor': ZERO, 'linhas': 0})
    por_esp = defaultdict(lambda: {'horas': ZERO, 'valor': ZERO})
    for i in itens:
        g = (i.grupo_nome or 'Sem grupo').replace(' (override)', '')
        por_grupo[g]['horas'] += i.horas_final
        por_grupo[g]['valor'] += i.total_final
        por_grupo[g]['linhas'] += 1
        por_esp[i.especialidade]['horas'] += i.horas_final
        por_esp[i.especialidade]['valor'] += i.total_final

    def ordenar(d, n=None):
        linhas = [{'nome': k, **v} for k, v in d.items()]
        linhas.sort(key=lambda x: (-x['valor'], x['nome']))
        return linhas[:n] if n else linhas

    def com_pct(linhas):
        maximo = max((l['valor'] for l in linhas), default=ZERO)
        for l in linhas:
            l['pct'] = float(l['valor'] / maximo * 100) if maximo else 0
            l['pct_total'] = float(l['valor'] / valor_total * 100) if valor_total else 0
        return linhas

    # ---- por profissional e por faturamento (equipe x avulso)
    equipes = equipe_por_medico({r.extracao.medico_nome for r in repasses})
    profissionais, faturamento = [], {}
    for r in repasses:
        nome = r.extracao.medico_nome
        eq = equipes.get(nome)
        profissionais.append({
            'nome': nome, 'equipe': eq.nome if eq else '',
            'horas': r.horas_total_final, 'valor': r.valor_total_final,
            'fechado': r.finalizado, 'repasse_id': r.pk,
        })
        chave = ('eq', eq.pk) if eq else ('av', r.pk)
        f = faturamento.setdefault(chave, {
            'nome': eq.nome if eq else nome, 'equipe': bool(eq),
            'profissionais': [], 'horas': ZERO, 'valor': ZERO})
        f['profissionais'].append(nome)
        f['horas'] += r.horas_total_final
        f['valor'] += r.valor_total_final
    profissionais.sort(key=lambda x: (-x['valor'], x['nome']))
    fat = sorted(faturamento.values(), key=lambda x: (-x['valor'], x['nome']))
    # Mostra só as maiores linhas; equipes nunca ficam recolhidas (é por elas que se fatura a empresa)
    for posicao, f in enumerate(fat):
        f['extra'] = posicao >= LIMITE_FATURAMENTO and not f['equipe']

    # ---- mês anterior (comparativo)
    ano_a, mes_a = _mes_anterior(ano, mes)
    ant = _totais(_repasses_do_mes(qs, ano_a, mes_a))
    valor_ant = ant['valor_fechado'] + ant['valor_aberto']
    horas_ant = ant['horas_fechadas'] + ant['horas_abertas']

    return {
        **tot,
        'valor_total': valor_total,
        'horas_total': horas_total,
        'valor_medio_hora': (valor_total / horas_total) if horas_total else ZERO,
        'ticket_medio': (valor_total / len(repasses)) if repasses else ZERO,
        'oferta': oferta,
        'atendimentos': atend,
        'taxa_atendimento': (atend * 100 / oferta) if oferta else 0,
        'pct_fechado': float(tot['valor_fechado'] / valor_total * 100) if valor_total else 0,
        'por_grupo': com_pct(ordenar(por_grupo)),
        'top_especialidades': com_pct(ordenar(por_esp, 8)),
        'top_profissionais': profissionais[:8],
        'faturamento': fat,
        'faturamento_extra': sum(1 for f in fat if f['extra']),
        'qtd_equipes': sum(1 for f in fat if f['equipe']),
        'anterior': {
            'rotulo': f'{mes_a:02d}/{ano_a}',
            'valor': valor_ant, 'horas': horas_ant,
            'var_valor': _variacao(valor_total, valor_ant),
            'var_horas': _variacao(horas_total, horas_ant),
        },
    }


def evolucao(qs, ano, mes, meses=6):
    """Valor finalizado por competência nos últimos `meses` meses (termina no mês escolhido)."""
    lista = []
    a, m = ano, mes
    for _ in range(meses):
        lista.append((a, m))
        a, m = _mes_anterior(a, m)
    lista.reverse()

    fech = qs.filter(status='finalizado', competencia__isnull=False)
    acumulado = defaultdict(lambda: {'valor': ZERO, 'horas': ZERO})
    for r in fech:
        acumulado[(r.competencia.year, r.competencia.month)]['valor'] += r.valor_total_final
        acumulado[(r.competencia.year, r.competencia.month)]['horas'] += r.horas_total_final

    serie = [{'rotulo': f'{m:02d}/{a}', **acumulado[(a, m)], 'atual': (a, m) == (ano, mes)}
             for a, m in lista]
    maximo = max((s['valor'] for s in serie), default=ZERO)
    for s in serie:
        s['pct'] = float(s['valor'] / maximo * 100) if maximo else 0
    return serie
