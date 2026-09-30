"""
Service pra gerenciar regras de minutos manualmente.
"""
import re
import unicodedata


def _normalizar(texto):
    if texto is None:
        return ""
    texto = str(texto)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip().upper()


def criar_ou_atualizar_regra(profissional, especialidade, minutos_lista,
                              valor_base=None, bonus=None):
    from ..models import RegraMinuto

    prof_n = _normalizar(profissional)
    esp_n = _normalizar(especialidade)

    if not prof_n or not esp_n:
        raise Exception("Profissional e especialidade são obrigatórios.")

    if not minutos_lista:
        raise Exception("Informe pelo menos um minuto.")

    obj, criado = RegraMinuto.objects.get_or_create(
        profissional_norm=prof_n,
        especialidade_norm=esp_n,
        defaults={
            'minutos': sorted(set(minutos_lista)),
            'valor_base_override': valor_base,
            'bonus_override': bonus,
        }
    )

    if not criado:
        obj.minutos = sorted(set(minutos_lista))
        obj.valor_base_override = valor_base
        obj.bonus_override = bonus
        obj.save()

    return obj, criado


def deletar_regra(regra_id):
    from ..models import RegraMinuto
    try:
        r = RegraMinuto.objects.get(pk=regra_id)
        r.delete()
        return True
    except RegraMinuto.DoesNotExist:
        return False


def buscar_minutos(profissional, especialidade):
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