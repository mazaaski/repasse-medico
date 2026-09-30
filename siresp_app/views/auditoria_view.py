"""
Tela de auditoria (somente administrador): consulta e exportação da trilha
de alterações.
"""
import csv
from datetime import datetime, timedelta

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from ..models import LogAuditoria
from django.contrib.auth.decorators import login_required
from ..services.auditoria import ACOES


def _filtrar(request):
    qs = LogAuditoria.objects.all()

    usuario = request.GET.get('usuario', '').strip()
    acao = request.GET.get('acao', '').strip()
    q = request.GET.get('q', '').strip()
    repasse = request.GET.get('repasse', '').strip()
    de = request.GET.get('de', '').strip()
    ate = request.GET.get('ate', '').strip()

    if usuario:
        qs = qs.filter(usuario_nome__iexact=usuario)
    if acao in ACOES:
        qs = qs.filter(acao=acao)
    if q:
        qs = qs.filter(Q(descricao__icontains=q) | Q(profissional__icontains=q))
    if repasse.isdigit():
        qs = qs.filter(repasse_id=int(repasse))

    def _data(txt):
        try:
            return datetime.strptime(txt, '%Y-%m-%d')
        except ValueError:
            return None

    d1, d2 = _data(de), _data(ate)
    tz = timezone.get_current_timezone()
    if d1:
        qs = qs.filter(criado_em__gte=timezone.make_aware(d1, tz))
    if d2:
        qs = qs.filter(criado_em__lt=timezone.make_aware(d2 + timedelta(days=1), tz))

    filtros = {'usuario': usuario, 'acao': acao, 'q': q, 'repasse': repasse, 'de': de, 'ate': ate}
    return qs.order_by('-criado_em', '-id'), filtros


@login_required
def lista(request):
    qs, filtros = _filtrar(request)
    pagina = Paginator(qs, 50).get_page(request.GET.get('pagina'))

    query = '&'.join(f'{k}={v}' for k, v in filtros.items() if v)
    return render(request, 'siresp_app/auditoria/lista.html', {
        'pagina': pagina,
        'filtros': filtros,
        'query': query,
        'acoes': sorted(ACOES.items(), key=lambda x: x[1]),
        'usuarios': (LogAuditoria.objects.exclude(usuario_nome='')
                     .values_list('usuario_nome', flat=True).distinct().order_by('usuario_nome')),
        'rotulos': ACOES,
    })


@login_required
def exportar_csv(request):
    qs, _ = _filtrar(request)
    resp = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    resp['Content-Disposition'] = 'attachment; filename="auditoria.csv"'
    w = csv.writer(resp, delimiter=';')
    w.writerow(['Data/hora', 'Usuário', 'Ação', 'Descrição', 'Profissional', 'Repasse',
                'Item', 'Campo', 'De', 'Para', 'IP'])
    tz = timezone.get_current_timezone()
    for log in qs[:20000]:
        quando = timezone.localtime(log.criado_em, tz).strftime('%d/%m/%Y %H:%M:%S')
        base = [quando, log.usuario_nome, ACOES.get(log.acao, log.acao), log.descricao,
                log.profissional, log.repasse_id or '']
        if log.detalhes:
            for d in log.detalhes:
                w.writerow(base + [d.get('item', ''), d.get('campo', ''), d.get('de', ''),
                                   d.get('para', ''), log.ip])
        else:
            w.writerow(base + ['', '', '', '', log.ip])
    return resp
