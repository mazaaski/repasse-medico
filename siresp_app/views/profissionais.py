"""
Base de profissionais e situação dos repasses no mês.
"""
from datetime import date

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import EquipeMedica, Profissional
from ..permissions import admin_required
from ..services import auditoria
from ..services.profissionais_service import garantir_profissional, situacao_mes

MESES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho',
         'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']


@login_required
def lista(request):
    hoje = date.today()
    try:
        ano = int(request.GET.get('ano', hoje.year))
        mes = int(request.GET.get('mes', hoje.month))
        date(ano, mes, 1)
    except ValueError:
        ano, mes = hoje.year, hoje.month

    situacoes = situacao_mes(request.user, ano, mes)
    contagem = {'finalizado': 0, 'rascunho': 0, 'extraido': 0, 'pendente': 0}
    for s in situacoes:
        contagem[s['status']] += 1

    filtro = request.GET.get('status', '')
    if filtro in contagem:
        situacoes = [s for s in situacoes if s['status'] == filtro]

    return render(request, 'siresp_app/profissionais/lista.html', {
        'situacoes': situacoes,
        'contagem': contagem,
        'ano': ano,
        'mes': mes,
        'meses': list(enumerate(MESES, start=1)),
        'anos': range(hoje.year - 3, hoje.year + 1),
        'filtro': filtro,
        'inativos': Profissional.objects.filter(ativo=False),
        'total_base': Profissional.objects.count(),
        'equipes': EquipeMedica.objects.all(),
        'voltar': _querystring(mes, ano, filtro),
    })


def _querystring(mes, ano, filtro=''):
    qs = f'mes={mes}&ano={ano}'
    return qs + (f'&status={filtro}' if filtro in ('pendente', 'extraido', 'rascunho', 'finalizado') else '')


def _destino(request):
    """Volta para a lista preservando mês/ano/filtro (só aceita valores válidos)."""
    try:
        mes, ano = int(request.POST.get('mes', 0)), int(request.POST.get('ano', 0))
        date(ano, mes, 1)
    except ValueError:
        return reverse('siresp_app:profissionais_lista')
    return reverse('siresp_app:profissionais_lista') + '?' + _querystring(mes, ano, request.POST.get('status', ''))


ACOES_MASSA = {
    'desativar': 'desativados',
    'reativar': 'reativados',
    'equipe': 'movidos para a equipe',
    'sem_equipe': 'retirados da equipe',
    'remover': 'removidos da base',
}


@admin_required
@require_POST
def acao_em_massa(request):
    """Aplica uma ação aos profissionais marcados. Tudo fica registrado na auditoria."""
    destino = _destino(request)
    acao = request.POST.get('acao', '')
    if acao not in ACOES_MASSA:
        messages.error(request, 'Escolha uma ação.')
        return redirect(destino)

    try:
        ids = {int(i) for i in request.POST.getlist('ids')}
    except ValueError:
        messages.error(request, 'Seleção inválida.')
        return redirect(destino)
    if not ids:
        messages.warning(request, 'Marque pelo menos um profissional.')
        return redirect(destino)

    equipe = None
    if acao == 'equipe':
        equipe = EquipeMedica.objects.filter(pk=request.POST.get('equipe_id') or 0).first()
        if not equipe:
            messages.error(request, 'Escolha a equipe de destino.')
            return redirect(destino)

    profs = list(Profissional.objects.filter(pk__in=ids).select_related('equipe'))
    detalhes, alterados = [], 0
    for p in profs:
        if acao == 'desativar' and p.ativo:
            p.ativo = False
            p.save(update_fields=['ativo'])
            detalhes.append({'item': p.nome, 'campo': 'Situação', 'de': 'ativo', 'para': 'desativado'})
        elif acao == 'reativar' and not p.ativo:
            p.ativo = True
            p.save(update_fields=['ativo'])
            detalhes.append({'item': p.nome, 'campo': 'Situação', 'de': 'desativado', 'para': 'ativo'})
        elif acao == 'equipe' and p.equipe_id != equipe.pk:
            detalhes.append({'item': p.nome, 'campo': 'Equipe',
                             'de': p.equipe.nome if p.equipe else '(nenhuma)', 'para': equipe.nome})
            p.equipe = equipe
            p.save(update_fields=['equipe'])
        elif acao == 'sem_equipe' and p.equipe_id:
            detalhes.append({'item': p.nome, 'campo': 'Equipe', 'de': p.equipe.nome, 'para': '(nenhuma)'})
            p.equipe = None
            p.save(update_fields=['equipe'])
        elif acao == 'remover':
            detalhes.append({'item': p.nome, 'campo': 'Base', 'de': 'cadastrado', 'para': 'removido'})
            p.delete()
        else:
            continue                     # já estava no estado pedido
        alterados += 1

    if alterados:
        destino_txt = f' "{equipe.nome}"' if equipe else ''
        auditoria.registrar(
            request, 'PROFISSIONAL_ALTERADO',
            f'Em massa: {alterados} profissional(is) {ACOES_MASSA[acao]}{destino_txt}',
            detalhes=detalhes)
        messages.success(request, f'{alterados} profissional(is) {ACOES_MASSA[acao]}{destino_txt}.')
    else:
        messages.info(request, 'Nenhuma alteração: os selecionados já estavam nesse estado.')
    ignorados = len(ids) - len(profs)
    if ignorados:
        messages.warning(request, f'{ignorados} selecionado(s) não existem mais.')
    return redirect(destino)


@admin_required
@require_POST
def adicionar_varios(request):
    """Cadastra vários profissionais de uma vez (um nome por linha)."""
    destino = _destino(request)
    nomes = [n for n in (request.POST.get('nomes', '').splitlines()) if n.strip()]
    if not nomes:
        messages.warning(request, 'Cole pelo menos um nome (um por linha).')
        return redirect(destino)

    novos, existentes, detalhes = 0, 0, []
    for n in nomes[:500]:
        obj, criado = garantir_profissional(n)
        if obj is None:
            continue
        if criado:
            novos += 1
            detalhes.append({'item': obj.nome, 'campo': 'Base', 'de': '', 'para': 'adicionado'})
        else:
            existentes += 1
    if novos:
        auditoria.registrar(request, 'PROFISSIONAL_ALTERADO',
                            f'Em massa: {novos} profissional(is) adicionados à base', detalhes=detalhes)
    messages.success(request, f'{novos} adicionado(s); {existentes} já estavam na base.')
    return redirect(destino)


@admin_required
@require_POST
def novo(request):
    nome = request.POST.get('nome', '').strip()
    obj, criado = garantir_profissional(nome)
    if not obj:
        messages.error(request, 'Informe o nome do profissional.')
    elif criado:
        auditoria.registrar(request, 'PROFISSIONAL_ALTERADO', f'"{obj.nome}" adicionado à base',
                            profissional=obj.nome)
        messages.success(request, f'"{obj.nome}" adicionado à base.')
    else:
        messages.info(request, f'"{obj.nome}" já está na base.')
    return redirect('siresp_app:profissionais_lista')


@admin_required
@require_POST
def alternar(request, pk):
    p = get_object_or_404(Profissional, pk=pk)
    p.ativo = not p.ativo
    p.save(update_fields=['ativo'])
    auditoria.registrar(request, 'PROFISSIONAL_ALTERADO',
                        f'"{p.nome}" {"reativado" if p.ativo else "desativado"}', profissional=p.nome)
    messages.success(
        request, f'"{p.nome}" {"reativado" if p.ativo else "desativado"}.'
    )
    return redirect('siresp_app:profissionais_lista')


@admin_required
@require_POST
def remover(request, pk):
    p = get_object_or_404(Profissional, pk=pk)
    p.delete()
    auditoria.registrar(request, 'PROFISSIONAL_ALTERADO', f'"{p.nome}" removido da base',
                        profissional=p.nome)
    messages.success(request, f'"{p.nome}" removido da base.')
    return redirect('siresp_app:profissionais_lista')
