"""
Geração do PDF do relatório de repasse (lote ou consolidado).

Recebe uma estrutura neutra, para servir às duas telas:

grupos = [{
    'equipe': 'Clínica Alfa' | None,
    'horas': Decimal, 'valor': Decimal,
    'profissionais': [{
        'nome': str, 'periodo': str, 'competencia': 'MM/AAAA',
        'horas': Decimal, 'valor': Decimal,
        'linhas': [{'especialidade', 'minutos', 'horas', 'valor_hora', 'total'}],
    }],
}]
resumo = saída de resumo_service.linhas_resumo
"""
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape as _esc

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

AZUL = colors.HexColor('#003366')
AZUL_CLARO = colors.HexColor('#DCE6F1')
VERDE = colors.HexColor('#C6EFCE')
CINZA = colors.HexColor('#F2F2F2')


def _moeda(v):
    s = f'{float(v):,.2f}'          # 1,234.56
    return 'R$ ' + s.replace(',', 'X').replace('.', ',').replace('X', '.')


def _num(v, casas=2):
    s = f'{float(v):,.{casas}f}'
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')


def _estilos():
    base = getSampleStyleSheet()
    return {
        'titulo': ParagraphStyle('t', parent=base['Title'], fontSize=16, textColor=AZUL, spaceAfter=2),
        'sub': ParagraphStyle('s', parent=base['Normal'], fontSize=9, textColor=colors.grey, alignment=1),
        'h2': ParagraphStyle('h2', parent=base['Heading2'], fontSize=12, textColor=AZUL, spaceBefore=10, spaceAfter=2),
        'h3': ParagraphStyle('h3', parent=base['Heading3'], fontSize=10, spaceBefore=6, spaceAfter=2),
        'txt': ParagraphStyle('x', parent=base['Normal'], fontSize=8),
        'peq': ParagraphStyle('p', parent=base['Normal'], fontSize=8, textColor=colors.grey),
        'dir': ParagraphStyle('d', parent=base['Normal'], fontSize=8, alignment=TA_RIGHT),
    }


def _tabela_profissional(p, est):
    dados = [['Especialidade', 'Min', 'Horas', 'R$/h', 'Total']]
    for l in p['linhas']:
        dados.append([
            Paragraph(_esc(l['especialidade']), est['txt']),
            _num(l['minutos'], 0), _num(l['horas']), _num(l['valor_hora']), _moeda(l['total']),
        ])
    if not p['linhas']:
        dados.append([Paragraph('Nenhuma linha aplicada.', est['peq']), '', '', '', ''])
    dados.append(['Subtotal', '', _num(p['horas']), '', _moeda(p['valor'])])

    t = Table(dados, colWidths=[11.5 * cm, 1.8 * cm, 2.6 * cm, 2.8 * cm, 3.6 * cm], repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), AZUL),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, CINZA]),
        ('BACKGROUND', (0, -1), (-1, -1), AZUL_CLARO),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    return t


def _tabela_resumo(resumo, tot_horas, tot_valor, est):
    dados = [['Equipe / Profissional', 'Profissionais', 'Horas', 'Valor']]
    for l in resumo:
        dados.append([
            Paragraph(('<b>%s</b>' if l['equipe'] else '%s') % _esc(l['nome']), est['txt']),
            Paragraph(_esc(l['profissionais']) if l['equipe'] else '', est['txt']),
            _num(l['horas']), _moeda(l['valor']),
        ])
    dados.append(['TOTAL GERAL DO REPASSE', '', _num(tot_horas), _moeda(tot_valor)])

    estilo = [
        ('BACKGROUND', (0, 0), (-1, 0), AZUL),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, -1), (-1, -1), VERDE),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]
    for i, l in enumerate(resumo, start=1):
        if l['equipe']:
            estilo.append(('BACKGROUND', (0, i), (-1, i), AZUL_CLARO))
    t = Table(dados, colWidths=[6.5 * cm, 11.5 * cm, 2.6 * cm, 3.7 * cm], repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle(estilo))
    return t


def gerar_pdf(titulo, subtitulo, grupos, resumo, tot_horas, tot_valor):
    est = _estilos()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), title=titulo,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.4 * cm, bottomMargin=1.4 * cm,
    )

    def rodape(canvas, d):
        canvas.saveState()
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(1.5 * cm, 0.8 * cm, f'{titulo} - gerado em {datetime.now():%d/%m/%Y %H:%M}')
        canvas.drawRightString(landscape(A4)[0] - 1.5 * cm, 0.8 * cm, f'Página {d.page}')
        canvas.restoreState()

    el = [Paragraph(titulo, est['titulo']), Paragraph(subtitulo, est['sub']), Spacer(1, 0.4 * cm)]

    for g in grupos:
        if g['equipe']:
            nomes = _esc(', '.join(p['nome'] for p in g['profissionais']))
            cab = [[Paragraph(f'<b>Equipe {_esc(g["equipe"])}</b><br/><font size=7 color="#555555">{nomes}</font>', est['txt']),
                    Paragraph(f'<b>{_num(g["horas"])} h</b> &nbsp; <b>{_moeda(g["valor"])}</b>', est['dir'])]]
            t = Table(cab, colWidths=[18 * cm, 8.8 * cm])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), AZUL_CLARO),
                ('BOX', (0, 0), (-1, -1), 0.6, AZUL),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            el += [Spacer(1, 0.2 * cm), t]

        for p in g['profissionais']:
            titulo_p = (f'<b>{_esc(p["nome"])}</b> <font size=8 color="#666666">- {p["periodo"]}'
                        f'{" - competência " + p["competencia"] if p["competencia"] else ""}</font>')
            el.append(KeepTogether([Paragraph(titulo_p, est['h3']), _tabela_profissional(p, est)]))

    el += [Spacer(1, 0.5 * cm),
           KeepTogether([Paragraph('Resumo por faturamento (equipes e profissionais avulsos)', est['h2']),
                         _tabela_resumo(resumo, tot_horas, tot_valor, est)])]

    doc.build(el, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()
