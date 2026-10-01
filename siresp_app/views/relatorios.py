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
from ..permissions import admin_required, eh_admin, repasses_visiveis
from ..services import auditoria


@login_required
def home(request):
    from datetime import datetime
    from ..services.profissionais_service import equipe_por_medico

    # todos os repasses do usuário: finalizados (verde) e rascunhos (amarelo)
    base = repasses_visiveis(request.user)

    medico = request.GET.get('medico', '').strip()
    competencia = request.GET.get('competencia', '').strip()
    situacao = request.GET.get('situacao', '').strip()
    unidade = request.GET.get('unidade', '').strip()

    qs = base.select_related('extracao', 'usuario_web')
    if situacao in ('finalizado', 'rascunho'):
        qs = qs.filter(status=situacao)
    else:
        situacao = ''
    if unidade:
        qs = qs.filter(extracao__unidade_nome=unidade)
    if medico:
        qs = qs.filter(extracao__medico_nome__icontains=medico)
    if competencia:
        try:
            qs = qs.filter(competencia=datetime.strptime(competencia, '%Y-%m').date())
        except ValueError:
            competencia = ''

    repasses = list(qs.order_by('status', '-competencia', 'extracao__medico_nome'))
    equipes = equipe_por_medico({r.extracao.medico_nome for r in repasses})
    for r in repasses:
        r.equipe = equipes.get(r.extracao.medico_nome)

    return render(request, 'siresp_app/relatorios/home.html', {
        'repasses': repasses,
        'filtro_unidade': unidade,
        'unidades': sorted(set(base.exclude(extracao__unidade_nome='')
                               .values_list('extracao__unidade_nome', flat=True))),
        'filtro_situacao': situacao,
        'ver_usuario': True,
        'qtd_finalizados': sum(1 for r in repasses if r.finalizado),
        'qtd_rascunhos': sum(1 for r in repasses if not r.finalizado),
        'competencias': base.exclude(competencia__isnull=True)
                            .order_by('-competencia')
                            .values_list('competencia', flat=True).distinct(),
        'filtro_medico': medico,
        'filtro_competencia': competencia,
        'total_horas': sum((r.horas_total_final for r in repasses), Decimal('0')),
        'total_valor': sum((r.valor_total_final for r in repasses), Decimal('0')),
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

    repasses = repasses_visiveis(request.user).filter(
        pk__in=ids,
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

    from ..services.resumo_service import texto_unidades
    ws["A2"] = (
        f"{texto_unidades(r.extracao.unidade_nome for r in repasses)}  |  "
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
        "Total Final (R$)", "Competência", "Equipe", "Unidade",
    ]

    fonte_cab = Font(bold=True, color="FFFFFF")
    fundo_cab = PatternFill(start_color="003366", end_color="003366", fill_type="solid")

    for col, texto in enumerate(cabecalhos, start=1):
        cell = ws.cell(row=linha_cab, column=col, value=texto)
        cell.font = fonte_cab
        cell.fill = fundo_cab
        cell.alignment = Alignment(horizontal="center", vertical="center")

    larguras = [40, 12, 22, 40, 22, 8, 12, 10, 14, 15, 10, 16, 14, 12, 15, 13, 30, 34]
    for i, w in enumerate(larguras):
        col_letter = chr(ord('A') + i)
        ws.column_dimensions[col_letter].width = w

    from ..services.profissionais_service import equipe_por_medico, agrupar_por_equipe
    from ..services.resumo_service import linhas_resumo, anexar_resumo_planilha
    lista_repasses = list(repasses.order_by('extracao__medico_nome', 'extracao__data_ini'))
    equipes = equipe_por_medico({r.extracao.medico_nome for r in lista_repasses})

    linha = linha_cab + 1
    total_horas_geral = Decimal('0')
    total_valor_geral = Decimal('0')

    for repasse in lista_repasses:
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
            ws.cell(row=linha, column=16, value=repasse.competencia_fmt)
            eq = equipes.get(ext.medico_nome)
            ws.cell(row=linha, column=17, value=eq.nome if eq else '')
            ws.cell(row=linha, column=18, value=ext.unidade_nome)

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
    for c in range(1, 19):
        cell = ws.cell(row=linha, column=c)
        cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)

    grupos = agrupar_por_equipe(
        lista_repasses,
        chave_nome=lambda r: r.extracao.medico_nome,
        valor_horas=lambda r: r.horas_total_final,
        valor_total=lambda r: r.valor_total_final,
    )
    resumo_linhas = linhas_resumo(
        grupos,
        nome_item=lambda r: r.extracao.medico_nome,
        horas_item=lambda r: r.horas_total_final,
        valor_item=lambda r: r.valor_total_final,
        id_item=lambda r: r.pk,
    )
    # No fim da aba principal, alinhado às colunas Profissional/.../Horas Final/Total Final
    anexar_resumo_planilha(ws, resumo_linhas, total_horas_geral, total_valor_geral,
                           col_nome=1, col_profs=4, col_horas=2, col_valor=3)

    # Aba própria de fechamento por faturamento
    resumo = wb.create_sheet("Por Equipe")
    resumo.append(["Faturamento", "Profissionais", "Horas", "Valor total (R$)"])
    for c in resumo[1]:
        c.font = Font(bold=True)
    for l in resumo_linhas:
        resumo.append([l['nome'], l['profissionais'], float(l['horas']), float(l['valor'])])
    resumo.append(["TOTAL GERAL", '', float(total_horas_geral), float(total_valor_geral)])
    for c in resumo[resumo.max_row]:
        c.font = Font(bold=True)
    for col, w in zip("ABCD", (40, 80, 10, 18)):
        resumo.column_dimensions[col].width = w
    for row in resumo.iter_rows(min_row=2):
        row[3].number_format = 'R$ #,##0.00'

    auditoria.registrar(request, 'EXPORTACAO',
                        f'Excel consolidado: {len(lista_repasses)} repasse(s)')
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    nome = f"relatorio_repasse_{_t.strftime('%Y-%m-%d_%H%M')}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{nome}"'
    wb.save(response)
    return response
@login_required
@require_POST
def gerar_pdf(request):
    from ..services.pdf_service import gerar_pdf as _gerar
    from ..services.profissionais_service import agrupar_por_equipe
    from ..services.resumo_service import linhas_resumo, texto_unidades

    try:
        ids = [int(i) for i in request.POST.getlist('repasses')]
    except ValueError:
        messages.error(request, 'IDs inválidos.')
        return redirect('siresp_app:relatorios_home')
    if not ids:
        messages.warning(request, 'Selecione pelo menos um repasse.')
        return redirect('siresp_app:relatorios_home')

    lista = list(repasses_visiveis(request.user).filter(
        pk__in=ids, status='finalizado'
    ).select_related('extracao').order_by('extracao__medico_nome', 'extracao__data_ini'))
    if not lista:
        messages.warning(request, 'Nenhum repasse finalizado encontrado.')
        return redirect('siresp_app:relatorios_home')

    grupos = agrupar_por_equipe(
        lista,
        chave_nome=lambda r: r.extracao.medico_nome,
        valor_horas=lambda r: r.horas_total_final,
        valor_total=lambda r: r.valor_total_final,
    )
    resumo = linhas_resumo(
        grupos,
        nome_item=lambda r: r.extracao.medico_nome,
        horas_item=lambda r: r.horas_total_final,
        valor_item=lambda r: r.valor_total_final,
        id_item=lambda r: r.pk,
    )
    grupos_pdf = [{
        'equipe': g['equipe'].nome if g['equipe'] else None,
        'horas': g['horas'],
        'valor': g['valor'],
        'profissionais': [{
            'nome': r.extracao.medico_nome,
            'periodo': f"{r.extracao.data_ini} a {r.extracao.data_fim}",
            'competencia': r.competencia_fmt,
            'horas': r.horas_total_final,
            'valor': r.valor_total_final,
            'linhas': [{
                'especialidade': i.especialidade, 'minutos': i.minutos,
                'horas': i.horas_final, 'valor_hora': i.valor_hora, 'total': i.total_final,
            } for i in r.itens.filter(marcado=True).order_by('ordem')],
        } for r in g['itens']],
    } for g in grupos]

    competencias = sorted({r.competencia_fmt for r in lista if r.competencia})
    pdf = _gerar(
        'Relatório de Repasse Consolidado',
        texto_unidades(r.extracao.unidade_nome for r in lista)
        + ' | Competência: ' + (', '.join(competencias) or '-') + f' | {len(lista)} repasse(s)',
        grupos_pdf, resumo,
        sum((r.horas_total_final for r in lista), Decimal('0')),
        sum((r.valor_total_final for r in lista), Decimal('0')))
    auditoria.registrar(request, 'EXPORTACAO',
                        f'PDF consolidado: {len(lista)} repasse(s)')
    resp = HttpResponse(pdf, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="relatorio_repasse_{_t.strftime("%Y-%m-%d_%H%M")}.pdf"'
    return resp


# =========================================================
# REABRIR VÁRIOS REPASSES (somente administrador)
# =========================================================
@admin_required
@require_POST
def reabrir_varios(request):
    """
    Reabre vários repasses de uma vez. Exige usuário administrador logado e
    um motivo, registrado na auditoria de cada repasse.
    """
    ids_str = request.POST.getlist('repasses')
    motivo = request.POST.get('motivo', '').strip()

    if not ids_str:
        messages.warning(request, 'Selecione pelo menos um repasse.')
        return redirect('siresp_app:relatorios_home')

    if len(motivo) < 5:
        messages.error(request, 'Informe o motivo da reabertura (mínimo 5 caracteres).')
        return redirect('siresp_app:relatorios_home')

    try:
        ids = [int(i) for i in ids_str]
    except ValueError:
        messages.error(request, 'IDs inválidos.')
        return redirect('siresp_app:relatorios_home')

    reabertos = 0
    ignorados = 0
    for r in Repasse.objects.filter(pk__in=ids).select_related('extracao'):
        if r.status != 'finalizado':
            ignorados += 1
            continue

        competencia = r.competencia_fmt
        valor = r.valor_total_final
        r.status = 'rascunho'
        r.finalizado_em = None
        r.competencia = None
        r.save(update_fields=['status', 'finalizado_em', 'competencia', 'atualizado_em'])
        auditoria.registrar(
            request, 'REPASSE_REABERTO',
            f'Reaberto em lote (era competência {competencia}, R$ {valor}). Motivo: {motivo}',
            repasse=r,
            detalhes=[{'item': '', 'campo': 'Motivo', 'de': '', 'para': motivo}])
        reabertos += 1

    if reabertos:
        messages.success(request, f'{reabertos} repasse(s) reaberto(s).')
    if ignorados:
        messages.info(request, f'{ignorados} repasse(s) ignorado(s) (não estavam finalizados).')
    if not reabertos and not ignorados:
        messages.warning(request, 'Nenhum repasse encontrado.')

    return redirect('siresp_app:relatorios_home')
