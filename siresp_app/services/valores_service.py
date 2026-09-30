"""
Lógica de resolução de valores por especialidade,
seguindo a mesma regra do app desktop:

  1) Match exato de especialidade
  2) Match por prefixo (o mais longo ganha)
  3) Fallback pro grupo 'Padrão'

E também:
  - registrar_regras (importação)
  - limpar_regras
  - buscar_minutos
"""
import re
import unicodedata


# =========================================================
# NORMALIZAÇÃO
# =========================================================
def _normalizar(texto):
    if texto is None:
        return ""
    texto = str(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip().upper()


# =========================================================
# RESOLVER VALORES POR ESPECIALIDADE
# =========================================================
def resolver_valores(especialidade):
    """
    Retorna dict:
      {
        'valor_base': float,
        'bonus_cheio': float,
        'grupo_nome': str,
        'grupo_id': int | None,
      }
    """
    from ..models import GrupoValor

    esp_norm = _normalizar(especialidade)

    # Pega o grupo Padrão (fallback)
    padrao = None
    for g in GrupoValor.objects.prefetch_related('especialidades').all():
        if _normalizar(g.nome) == _normalizar('Padrão'):
            padrao = g
            break

    # 1) Match exato
    for g in GrupoValor.objects.prefetch_related('especialidades').all():
        if _normalizar(g.nome) == _normalizar('Padrão'):
            continue
        for esp in g.especialidades.all():
            if _normalizar(esp.nome) == esp_norm:
                return {
                    'valor_base': float(g.valor_base),
                    'bonus_cheio': float(g.bonus),
                    'grupo_nome': g.nome,
                    'grupo_id': g.pk,
                }

    # 2) Match por prefixo (mais longo ganha)
    candidatos = []
    for g in GrupoValor.objects.prefetch_related('especialidades').all():
        if _normalizar(g.nome) == _normalizar('Padrão'):
            continue
        for esp in g.especialidades.all():
            esp_n = _normalizar(esp.nome)
            if esp_n and esp_norm.startswith(esp_n):
                candidatos.append((len(esp_n), g))

    if candidatos:
        candidatos.sort(key=lambda x: x[0], reverse=True)
        g = candidatos[0][1]
        return {
            'valor_base': float(g.valor_base),
            'bonus_cheio': float(g.bonus),
            'grupo_nome': g.nome,
            'grupo_id': g.pk,
        }

    # 3) Fallback
    if padrao:
        return {
            'valor_base': float(padrao.valor_base),
            'bonus_cheio': float(padrao.bonus),
            'grupo_nome': padrao.nome,
            'grupo_id': padrao.pk,
        }

    return {
        'valor_base': 0.0,
        'bonus_cheio': 0.0,
        'grupo_nome': 'Sem grupo',
        'grupo_id': None,
    }


# =========================================================
# REGRAS DE MINUTOS
# =========================================================
def registrar_regras(linhas_planilha):
    """
    Recebe lista de (profissional, especialidade, minutos) e faz upsert
    na tabela RegraMinuto (agregando minutos por par).

    Também popula EspecialidadeConhecida com as especialidades encontradas.

    Retorna dict com estatísticas: {'linhas', 'pares', 'novas_esp'}
    """
    from ..models import RegraMinuto, EspecialidadeConhecida

    agrupado = {}
    especialidades_set = set()

    for prof, esp, minutos in linhas_planilha:
        prof_n = _normalizar(prof)
        esp_n = _normalizar(esp)
        if not prof_n or not esp_n:
            continue

        chave = (prof_n, esp_n)
        agrupado.setdefault(chave, set()).add(minutos)
        especialidades_set.add(esp.strip())

    pares_atualizados = 0
    for (prof_n, esp_n), minutos_set in agrupado.items():
        obj, criado = RegraMinuto.objects.get_or_create(
            profissional_norm=prof_n,
            especialidade_norm=esp_n,
            defaults={'minutos': sorted(minutos_set)},
        )
        if not criado:
            atuais = set(obj.minutos)
            antes = len(atuais)
            atuais |= minutos_set
            if len(atuais) > antes:
                obj.minutos = sorted(atuais)
                obj.save(update_fields=['minutos'])
        pares_atualizados += 1

    novas_esp = 0
    for esp in especialidades_set:
        _, criada = EspecialidadeConhecida.objects.get_or_create(nome=esp)
        if criada:
            novas_esp += 1

    # Base de profissionais (nome original da primeira ocorrência)
    from .profissionais_service import garantir_profissional
    novos_prof = 0
    vistos = set()
    for prof, _esp, _min in linhas_planilha:
        n = _normalizar(prof)
        if not n or n in vistos:
            continue
        vistos.add(n)
        _, criado = garantir_profissional(prof)
        if criado:
            novos_prof += 1

    return {
        'linhas': len(linhas_planilha),
        'pares': pares_atualizados,
        'novas_esp': novas_esp,
        'novos_prof': novos_prof,
    }


def limpar_regras():
    """Apaga todas as regras de minutos."""
    from ..models import RegraMinuto
    qtd = RegraMinuto.objects.count()
    RegraMinuto.objects.all().delete()
    return qtd


def buscar_minutos(profissional, especialidade):
    """
    Retorna lista de minutos para (profissional, especialidade), ou [].
    """
    from ..models import RegraMinuto
    prof_n = _normalizar(profissional)
    esp_n = _normalizar(especialidade)

    try:
        obj = RegraMinuto.objects.get(
            profissional_norm=prof_n,
            especialidade_norm=esp_n,
        )
        return list(obj.minutos)
    except RegraMinuto.DoesNotExist:
        return []