"""
Views da aba Relatórios.
"""
import time as _t
from decimal import Decimal

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.views.decorators.http import require_POST

from ..models import Repasse


@login_required
def home(request):
    qs = Repasse.objects.filter(
        usuario_web=request.user,
        status='finalizado',
    ).select_related('extracao')

    medico = request.GET.get('medico', '').strip()
    data_ini = request.GET.get('data_ini', '').strip()
    data_fim = request.GET.get('data_fim', '').strip()

    if medico:
        qs = qs.filter(extracao__medico_nome__icontains=medico)
    if data_ini:
        qs = qs.filter(extracao__data_ini__gte=data_ini)
    if data_fim:
        qs = qs.filter(extracao__data_fim__lte=data_fim)

    return render(request, 'siresp_app/relatorios/home.html', {
        'repasses': qs,
        'filtro_medico': medico,
        'filtro_data_ini': data_ini,
        'filtro_data_fim': data_fim,
    })


@login_required
@require_POST
def gerar_excel(request):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    ids_str = request.POST.getlist('repasses')
    if not ids_str:
        messages.warning(request, 'Selecione pelo menos um repasse.')
        return redirect('siresp_app:relatorios_home')

    try:
        ids = [int(i) for i in ids_str]
    except ValueError:
        messages.error(request, 'IDs inválidos.')
        return redirect('siresp_app:relatorios_home')

    repasses = Repasse.objects.filter(
        pk__in=ids,
        usuario_web=request.user,
        status='finalizado',
    ).select_related('extracao')

    if not repasses.exists():
        messages.warning(request, 'Nenhum repasse finalizado encontrado.')
        return redirect('siresp_app:relatorios_home')

    wb = Workbook()
    ws = wb.active
    ws.title = "Relatório Consolidado"

    ws["A1"] = "Relatório de Repasse Consolidado"
    ws["A1"].font = Font(bold=True, size=14)
    ws.merge_cells("A1:O1")
    ws["A1"].alignment = Alignment(horizontal="center")

    ws["A2"] = (
        f"Gerado em: {_t.strftime('%d/%m/%Y %H:%M')}  |  "
        f"Total de repasses: {repasses.count()}"
    )
    ws.merge_cells("A2:O2")
    ws["A2"].alignment = Alignment(horizontal="center")
    ws["A2"].font = Font(italic=True, size=11)

    linha_cab = 4
    cabecalhos = [
        "Profissional", "CRM", "Período",
        "Especialidade", "Grupo",
        "Oferta", "Atendimentos", "Minutos",
        "Valor Base (R$)", "Bônus 100% (R$)", "Bônus %", "Bônus Aplicado (R$)",
        "Valor/Hora (R$)",
        "Horas Final",
        "Total Final (R$)",
    ]

    fonte_cab = Font(bold=True, color="FFFFFF")
    fundo_cab = PatternFill(start_color="003366", end_color="003366", fill_type="solid")

    for col, texto in enumerate(cabecalhos, start=1):
        cell = ws.cell(row=linha_cab, column=col, value=texto)
        cell.font = fonte_cab
        cell.fill = fundo_cab
        cell.alignment = Alignment(horizontal="center", vertical="center")

    larguras = [40, 12, 22, 40, 22, 8, 12, 10, 14, 15, 10, 16, 14, 12, 15]
    for i, w in enumerate(larguras):
        col_letter = chr(ord('A') + i)
        ws.column_dimensions[col_letter].width = w

    linha = linha_cab + 1
    total_horas_geral = Decimal('0')
    total_valor_geral = Decimal('0')

    for repasse in repasses.order_by('extracao__medico_nome', 'extracao__data_ini'):
        ext = repasse.extracao
        marcados = repasse.itens.filter(marcado=True).order_by('ordem')

        for item in marcados:
            ws.cell(row=linha, column=1, value=ext.medico_nome)
            ws.cell(row=linha, column=2, value=ext.medico_crm)
            ws.cell(row=linha, column=3, value=f"{ext.data_ini} a {ext.data_fim}")
            ws.cell(row=linha, column=4, value=item.especialidade)
            ws.cell(row=linha, column=5, value=item.grupo_nome)
            ws.cell(row=linha, column=6, value=item.oferta)
            ws.cell(row=linha, column=7, value=item.atendimentos)
            ws.cell(row=linha, column=8, value=float(item.minutos))
            ws.cell(row=linha, column=9, value=float(item.valor_base))
            ws.cell(row=linha, column=10, value=float(item.bonus_cheio))
            ws.cell(row=linha, column=11, value=item.bonus_percent)
            ws.cell(row=linha, column=12, value=float(item.bonus_aplicado))
            ws.cell(row=linha, column=13, value=float(item.valor_hora))
            ws.cell(row=linha, column=14, value=float(item.horas_final))
            ws.cell(row=linha, column=15, value=float(item.total_final))

            ws.cell(row=linha, column=8).number_format = '0'
            for c in (9, 10, 12, 13, 15):
                ws.cell(row=linha, column=c).number_format = 'R$ #,##0.00'
            ws.cell(row=linha, column=14).number_format = '0.00'

            total_horas_geral += item.horas_final
            total_valor_geral += item.total_final

            linha += 1

    ws.cell(row=linha, column=1, value="TOTAL GERAL").font = Font(bold=True)
    ws.cell(row=linha, column=14, value=float(total_horas_geral)).font = Font(bold=True)
    ws.cell(row=linha, column=15, value=float(total_valor_geral)).font = Font(bold=True)
    ws.cell(row=linha, column=14).number_format = '0.00'
    ws.cell(row=linha, column=15).number_format = 'R$ #,##0.00'

    thin = Side(border_style="thin", color="000000")
    for c in range(1, 16):
        cell = ws.cell(row=linha, column=c)
        cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    nome = f"relatorio_repasse_{_t.strftime('%Y-%m-%d_%H%M')}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{nome}"'
    wb.save(response)
    return response
# =========================================================
# REABRIR VÁRIOS REPASSES (com senha de admin)
# =========================================================
@login_required
@require_POST
def reabrir_varios(request):
    """
    Reabre vários repasses de uma vez.
    Exige usuário + senha de um superuser (admin).
    """
    from django.contrib.auth import authenticate

    ids_str = request.POST.getlist('repasses')
    admin_user = request.POST.get('admin_user', '').strip()
    admin_pass = request.POST.get('admin_pass', '')

    if not ids_str:
        messages.warning(request, 'Selecione pelo menos um repasse.')
        return redirect('siresp_app:relatorios_home')

    if not admin_user or not admin_pass:
        messages.error(request, 'Informe usuário e senha do admin.')
        return redirect('siresp_app:relatorios_home')

    # Autentica
    user = authenticate(request, username=admin_user, password=admin_pass)
    if user is None:
        messages.error(request, 'Usuário ou senha do admin inválidos.')
        return redirect('siresp_app:relatorios_home')

    if not user.is_superuser:
        messages.error(
            request,
            f'O usuário "{admin_user}" não é admin. Apenas admins podem reabrir.'
        )
        return redirect('siresp_app:relatorios_home')

    # Busca os repasses
    try:
        ids = [int(i) for i in ids_str]
    except ValueError:
        messages.error(request, 'IDs inválidos.')
        return redirect('siresp_app:relatorios_home')

    repasses = Repasse.objects.filter(
        pk__in=ids,
        usuario_web=request.user,
    )

    reabertos = 0
    ignorados = 0

    for r in repasses:
        if r.status != 'finalizado':
            ignorados += 1
            continue

        r.status = 'rascunho'
        r.finalizado_em = None
        r.save(update_fields=['status', 'finalizado_em', 'atualizado_em'])
        reabertos += 1

    if reabertos > 0:
        messages.success(
            request,
            f'{reabertos} repasse(s) reaberto(s) por "{user.username}".'
        )
    if ignorados > 0:
        messages.info(
            request,
            f'{ignorados} repasse(s) ignorado(s) (não estavam finalizados).'
        )
    if reabertos == 0 and ignorados == 0:
        messages.warning(request, 'Nenhum repasse encontrado.')

    return redirect('siresp_app:relatorios_home')