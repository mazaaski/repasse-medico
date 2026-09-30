"""
Painel inicial: mostra em que etapa do mês o usuário está e qual é o
próximo passo.
"""
from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from ..models import Profissional
from ..permissions import eh_admin, repasses_visiveis
from ..services import scraper_service, dashboard_service
from ..services.profissionais_service import situacao_mes, extracoes_do_mes

MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho',
         'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']


def proximo_passo(*, total_base, logado, pendentes, sem_repasse, rascunhos,
                  finalizados, qs):
    """Decide a próxima ação sugerida. Retorna (texto, botão, url)."""
    if total_base == 0:
        return ('Comece importando a planilha de agendas: ela cadastra os profissionais '
                'e as regras de minutos.',
                'Importar planilha', reverse('siresp_app:config_importar'))
    if pendentes:
        if not logado:
            return (f'{pendentes} profissional(is) ainda sem extração. '
                    'Faça login no SIRESP para extrair a produção.',
                    'Ir para Produção', reverse('siresp_app:producao_home'))
        return (f'{pendentes} profissional(is) ainda sem extração. '
                'Use a busca em lote com "Carregar pendentes do período".',
                'Extrair em lote', reverse('siresp_app:producao_home'))
    if sem_repasse:
        return (f'{sem_repasse} extração(ões) esperando repasse. '
                'Gere todos de uma vez.',
                'Gerar repasses em lote', reverse('siresp_app:repasse_lote') + qs)
    if rascunhos:
        return (f'{rascunhos} repasse(s) em rascunho. Confira, ajuste e finalize cada um.',
                'Conferir rascunhos', reverse('siresp_app:repasse_lote') + qs)
    return ('Tudo finalizado neste mês. Gere o relatório consolidado.',
            'Ir para Relatórios', reverse('siresp_app:relatorios_home'))


@login_required
def home(request):
    hoje = date.today()
    try:
        ano = int(request.GET.get('ano', hoje.year))
        mes = int(request.GET.get('mes', hoje.month))
        date(ano, mes, 1)
    except ValueError:
        ano, mes = hoje.year, hoje.month

    situacoes = situacao_mes(request.user, ano, mes)
    cont = {'pendente': 0, 'extraido': 0, 'rascunho': 0, 'finalizado': 0}
    for s in situacoes:
        cont[s['status']] += 1

    total = len(situacoes)
    extraidos = total - cont['pendente']
    logado = scraper_service.sessao_ativa(request.user)
    qs = f'?mes={mes}&ano={ano}'

    texto, botao, url = proximo_passo(
        total_base=total, logado=logado, pendentes=cont['pendente'],
        sem_repasse=cont['extraido'], rascunhos=cont['rascunho'],
        finalizados=cont['finalizado'], qs=qs,
    )

    return render(request, 'siresp_app/painel.html', {
        'ano': ano, 'mes': mes,
        'meses': list(enumerate(MESES, start=1)),
        'anos': range(hoje.year - 3, hoje.year + 1),
        'nome_mes': MESES[mes - 1],
        'total': total,
        'extraidos': extraidos,
        'cont': cont,
        'logado': logado,
        'total_extracoes': len(extracoes_do_mes(request.user, ano, mes)),
        'sem_base': Profissional.objects.count() == 0,
        'passo_texto': texto, 'passo_botao': botao, 'passo_url': url,
        'pct_extraido': round(extraidos * 100 / total) if total else 0,
        'pct_final': round(cont['finalizado'] * 100 / total) if total else 0,
        'qs': qs,
        # indicadores contábeis (admin vê todos os usuários)
        'fin': dashboard_service.dados_mes(repasses_visiveis(request.user), ano, mes),
        'serie': dashboard_service.evolucao(repasses_visiveis(request.user), ano, mes),
        'ver_todos': True,
    })
