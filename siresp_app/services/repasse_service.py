"""
Service que cria e gerencia os Repasses.
"""
import re
import unicodedata
from decimal import Decimal

from django.db import transaction


def _normalizar(texto):
    if texto is None:
        return ""
    texto = str(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip().upper()


def _buscar_minutos(profissional, especialidade):
    from ..models import RegraMinuto

    prof_n = _normalizar(profissional)
    esp_n = _normalizar(especialidade)

    try:
        r = RegraMinuto.objects.get(
            profissional_norm=prof_n,
            especialidade_norm=esp_n,
        )
        return sorted(r.minutos)
    except RegraMinuto.DoesNotExist:
        return []


def _resolver_minutos(profissional, especialidade, escolhas_ambiguas=None):
    valores = _buscar_minutos(profissional, especialidade)

    if not valores:
        return Decimal('15'), True

    if len(valores) == 1:
        return Decimal(str(valores[0])), False

    chave = (_normalizar(profissional), _normalizar(especialidade))
    if escolhas_ambiguas and chave in escolhas_ambiguas:
        return Decimal(str(escolhas_ambiguas[chave])), False

    return Decimal(str(valores[0])), False


def _resolver_valores(especialidade, profissional=None):
    """
    Resolve valor_base, bonus, grupo_nome.
    Verifica override da RegraMinuto primeiro.
    """
    from ..models import RegraMinuto

    # 1) Tenta override na regra
    if profissional:
        prof_n = _normalizar(profissional)
        esp_n = _normalizar(especialidade)
        try:
            r = RegraMinuto.objects.get(
                profissional_norm=prof_n,
                especialidade_norm=esp_n,
            )
            if r.tem_override:
                g_base, g_bonus, g_nome = _resolver_valores_grupo(especialidade)
                valor_base = r.valor_base_override if r.valor_base_override is not None else g_base
                bonus = r.bonus_override if r.bonus_override is not None else g_bonus
                return valor_base, bonus, f"{g_nome} (override)"
        except RegraMinuto.DoesNotExist:
            pass

    # 2) Fallback: grupo normal
    return _resolver_valores_grupo(especialidade)


def _resolver_valores_grupo(especialidade):
    from ..models import GrupoValor

    esp_norm = _normalizar(especialidade)

    padrao = None
    grupos = list(GrupoValor.objects.prefetch_related('especialidades').all())

    for g in grupos:
        if _normalizar(g.nome) == _normalizar('Padrão'):
            padrao = g
            break

    for g in grupos:
        if _normalizar(g.nome) == _normalizar('Padrão'):
            continue
        for esp in g.especialidades.all():
            if _normalizar(esp.nome) == esp_norm:
                return g.valor_base, g.bonus, g.nome

    candidatos = []
    for g in grupos:
        if _normalizar(g.nome) == _normalizar('Padrão'):
            continue
        for esp in g.especialidades.all():
            esp_n = _normalizar(esp.nome)
            if esp_n and esp_norm.startswith(esp_n):
                candidatos.append((len(esp_n), g))

    if candidatos:
        candidatos.sort(key=lambda x: x[0], reverse=True)
        g = candidatos[0][1]
        return g.valor_base, g.bonus, g.nome

    if padrao:
        return padrao.valor_base, padrao.bonus, padrao.nome

    return Decimal('0'), Decimal('0'), 'Sem grupo'


@transaction.atomic
def criar_repasse_de_extracao(extracao, usuario, escolhas_ambiguas=None):
    from ..models import Repasse, ItemRepasse

    Repasse.objects.filter(extracao=extracao).delete()

    repasse = Repasse.objects.create(
        extracao=extracao,
        usuario_web=usuario,
        status='rascunho',
    )

    profissional = extracao.medico_nome

    for ordem, item_prod in enumerate(extracao.itens.all()):
        esp = item_prod.especialidade

        minutos, faltou = _resolver_minutos(profissional, esp, escolhas_ambiguas)
        valor_base, bonus_cheio, grupo_nome = _resolver_valores(esp, profissional)

        try:
            oferta = int(str(item_prod.get('Oferta_N', '0')).replace('.', '').replace(',', '') or 0)
        except (ValueError, TypeError):
            oferta = 0

        try:
            atend = int(str(item_prod.get('Atend_Total_N', '0')).replace('.', '').replace(',', '') or 0)
        except (ValueError, TypeError):
            atend = 0

        ItemRepasse.objects.create(
            repasse=repasse,
            ordem=ordem,
            especialidade=esp,
            oferta=oferta,
            atendimentos=atend,
            minutos=minutos,
            valor_base=valor_base,
            bonus_cheio=bonus_cheio,
            bonus_percent='100%',
            grupo_nome=grupo_nome,
            marcado=False,
            faltou_regra=faltou,
        )

    repasse.recalcular_totais()
    return repasse


@transaction.atomic
def recalcular_repasse(repasse, escolhas_ambiguas=None):
    profissional = repasse.extracao.medico_nome

    for item in repasse.itens.all():
        minutos, faltou = _resolver_minutos(
            profissional, item.especialidade, escolhas_ambiguas,
        )
        valor_base, bonus_cheio, grupo_nome = _resolver_valores(
            item.especialidade, profissional
        )

        item.minutos = minutos
        item.valor_base = valor_base
        item.bonus_cheio = bonus_cheio
        item.grupo_nome = grupo_nome
        item.faltou_regra = faltou
        item.save()

    repasse.recalcular_totais()
    return repasse


def arredondar_repasse(repasse, modo):
    import math
    from decimal import Decimal as D

    for item in repasse.itens.filter(marcado=True):
        if modo == 'baixo':
            item.horas_final = D(math.floor(float(item.horas_real)))
        elif modo == 'cima':
            item.horas_final = D(math.ceil(float(item.horas_real)))
        else:
            item.horas_final = item.horas_real

        item.total_final = (item.horas_final * item.valor_hora).quantize(D('0.01'))
        item.save(update_fields=['horas_final', 'total_final', 'atualizado_em'])

    repasse.recalcular_totais()
    return repasse

def marcar_por_regra(repasse):
    """
    Marca as linhas cuja especialidade tem regra cadastrada para o
    profissional (as especialidades que ele realmente atende) e
    recalcula os totais. Retorna quantas linhas foram marcadas.
    """
    marcadas = repasse.itens.filter(faltou_regra=False).update(marcado=True)
    repasse.recalcular_totais()
    return marcadas


def criar_repasses_lote(usuario, extracoes):
    """
    Cria (ou refaz) o repasse de cada extração, aplicando regras de
    minutos/valores e marcando as especialidades do profissional.

    - sem repasse  -> cria
    - rascunho     -> refaz do zero (ajustes manuais são descartados)
    - finalizado   -> não mexe (precisa reabrir antes)

    Retorna (criados, refeitos, ignorados): repasses gerados agora
    (criados e refeitos, nesta ordem de lista) e extrações finalizadas puladas.
    """
    criados, refeitos, ignorados = [], [], []
    for ext in extracoes:
        existente = getattr(ext, 'repasse', None)
        if existente is not None and existente.status == 'finalizado':
            ignorados.append(ext)
            continue
        repasse = criar_repasse_de_extracao(ext, usuario)
        marcar_por_regra(repasse)
        (refeitos if existente is not None else criados).append(repasse)
    return criados, refeitos, ignorados


# =========================================================
# FINALIZAÇÃO / COMPETÊNCIA
# =========================================================
def competencia_padrao(hoje=None):
    """Mês anterior ao atual (1º dia): o repasse feito em setembro paga agosto."""
    from datetime import date
    hoje = hoje or date.today()
    ano, mes = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
    return date(ano, mes, 1)


def parse_competencia(texto, hoje=None):
    """
    Converte 'AAAA-MM' (ou 'MM/AAAA') em date (1º dia do mês).
    Só aceita meses já fechados: no máximo o mês anterior ao atual.
    Levanta ValueError com mensagem pronta para o usuário.
    """
    from datetime import date, datetime
    texto = (texto or '').strip()
    if not texto:
        raise ValueError('Selecione o mês de competência do repasse.')
    for fmt in ('%Y-%m', '%m/%Y'):
        try:
            d = datetime.strptime(texto, fmt).date().replace(day=1)
            break
        except ValueError:
            continue
    else:
        raise ValueError('Mês de competência inválido.')

    limite = competencia_padrao(hoje)
    if d > limite:
        raise ValueError(
            f'O repasse paga um mês já fechado. O último mês permitido é '
            f'{limite.strftime("%m/%Y")}.'
        )
    return d


def finalizar_repasse(repasse, competencia):
    """
    Finaliza o repasse com a competência informada (date).
    Retorna (ok, mensagem).
    """
    from django.utils import timezone

    if repasse.status == 'finalizado':
        return False, 'Esse repasse já está finalizado.'
    if not repasse.itens.filter(marcado=True).exists():
        return False, 'Marque pelo menos uma linha antes de finalizar.'

    repasse.recalcular_totais()
    repasse.status = 'finalizado'
    repasse.finalizado_em = timezone.now()
    repasse.competencia = competencia
    repasse.save(update_fields=[
        'status', 'finalizado_em', 'competencia', 'atualizado_em'])
    return True, f'Repasse finalizado (competência {competencia.strftime("%m/%Y")}).'
