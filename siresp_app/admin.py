from django.contrib import admin
from .models import (
    GrupoValor, EspecialidadeGrupo,
    EspecialidadeConhecida, ConfiguracaoLogin,
    RegraMinuto,
    SessaoSiresp, Extracao, ItemProducao,
    Repasse, ItemRepasse,
)


# =========================================================
# CONFIGURAÇÕES (grupos e especialidades)
# =========================================================
class EspecialidadeGrupoInline(admin.TabularInline):
    model = EspecialidadeGrupo
    extra = 0


@admin.register(GrupoValor)
class GrupoValorAdmin(admin.ModelAdmin):
    list_display = ('nome', 'valor_base', 'bonus', 'valor_hora_100', 'e_padrao')
    inlines = [EspecialidadeGrupoInline]
    ordering = ('ordem', 'nome')


@admin.register(EspecialidadeConhecida)
class EspecialidadeConhecidaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'criado_em')
    search_fields = ('nome',)


@admin.register(ConfiguracaoLogin)
class ConfiguracaoLoginAdmin(admin.ModelAdmin):
    list_display = ('usuario_web', 'usuario', 'origem', 'atualizado_em')
    search_fields = ('usuario_web__username', 'usuario')


@admin.register(RegraMinuto)
class RegraMinutoAdmin(admin.ModelAdmin):
    list_display = ('profissional_norm', 'especialidade_norm', 'minutos_formatados')
    search_fields = ('profissional_norm', 'especialidade_norm')
    list_filter = ()


# =========================================================
# PRODUÇÃO
# =========================================================
@admin.register(SessaoSiresp)
class SessaoSirespAdmin(admin.ModelAdmin):
    list_display = ('usuario_web', 'status', 'atualizada_em')
    list_filter = ('status',)
    search_fields = ('usuario_web__username',)


class ItemProducaoInline(admin.TabularInline):
    model = ItemProducao
    extra = 0
    fields = ('ordem', 'especialidade')
    readonly_fields = ('ordem', 'especialidade')
    can_delete = False
    max_num = 0
    show_change_link = True


@admin.register(Extracao)
class ExtracaoAdmin(admin.ModelAdmin):
    list_display = ('medico_nome', 'medico_crm', 'data_ini', 'data_fim', 'total_itens', 'criada_em', 'usuario_web')
    list_filter = ('usuario_web', 'criada_em')
    search_fields = ('medico_nome', 'medico_crm')
    inlines = [ItemProducaoInline]
    readonly_fields = ('criada_em',)


@admin.register(ItemProducao)
class ItemProducaoAdmin(admin.ModelAdmin):
    list_display = ('extracao', 'especialidade', 'ordem')
    search_fields = ('especialidade', 'extracao__medico_nome')
    list_filter = ()


# =========================================================
# REPASSE
# =========================================================
class ItemRepasseInline(admin.TabularInline):
    model = ItemRepasse
    extra = 0
    fields = (
        'ordem', 'especialidade', 'oferta', 'minutos',
        'valor_base', 'bonus_cheio', 'bonus_percent',
        'valor_hora', 'horas_real', 'total_real', 'marcado',
    )
    readonly_fields = ('valor_hora', 'horas_real', 'total_real')
    can_delete = False
    max_num = 0


@admin.register(Repasse)
class RepasseAdmin(admin.ModelAdmin):
    list_display = (
        'extracao', 'status',
        'horas_total_real', 'horas_total_final',
        'valor_total_real', 'valor_total_final',
        'criado_em', 'usuario_web',
    )
    list_filter = ('status', 'usuario_web', 'criado_em')
    search_fields = ('extracao__medico_nome',)
    readonly_fields = ('criado_em', 'atualizado_em')
    inlines = [ItemRepasseInline]


@admin.register(ItemRepasse)
class ItemRepasseAdmin(admin.ModelAdmin):
    list_display = (
        'repasse', 'especialidade', 'oferta', 'minutos',
        'valor_base', 'bonus_cheio', 'bonus_percent',
        'valor_hora', 'total_real', 'marcado',
    )
    list_filter = ('marcado', 'bonus_percent', 'faltou_regra')
    search_fields = ('especialidade', 'repasse__extracao__medico_nome')