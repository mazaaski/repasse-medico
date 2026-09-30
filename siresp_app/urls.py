from django.urls import path
from .views import auth, config, producao, repasse, relatorios

app_name = 'siresp_app'

urlpatterns = [
    # Autenticação
    path('login/', auth.login_view, name='login'),
    path('logout/', auth.logout_view, name='logout'),
    path('', auth.home_view, name='home'),

    # =========================================================
    # CONFIGURAÇÕES — GRUPOS
    # =========================================================
    path('config/', config.lista_grupos, name='config_lista'),
    path('config/novo/', config.novo_grupo, name='config_novo'),
    path('config/<int:pk>/editar/', config.editar_grupo, name='config_editar'),
    path('config/<int:pk>/remover/', config.remover_grupo, name='config_remover'),

    # Especialidades conhecidas
    path('config/especialidades/', config.lista_especialidades, name='config_especialidades'),
    path('config/especialidades/nova/', config.nova_especialidade, name='config_nova_esp'),

    # Importação
    path('config/importar/', config.importar_planilha, name='config_importar'),

    # Regras
    path('config/regras/', config.lista_regras, name='config_regras'),
    path('config/regras/limpar/', config.limpar_regras, name='config_limpar_regras'),
    path('config/regras/nova/', config.nova_regra, name='config_nova_regra'),
    path('config/regras/<int:pk>/editar/', config.editar_regra, name='config_editar_regra'),
    path('config/regras/<int:pk>/deletar/', config.deletar_regra, name='config_deletar_regra'),

    # =========================================================
    # PRODUÇÃO
    # =========================================================
    path('producao/', producao.producao_home, name='producao_home'),
    path('producao/credenciais/', producao.salvar_credenciais, name='producao_salvar_cred'),
    path('producao/login/', producao.login_siresp, name='producao_login'),
    path('producao/enviar-captcha/', producao.enviar_captcha, name='producao_enviar_captcha'),
    path('producao/recarregar-captcha/', producao.recarregar_captcha, name='producao_recarregar_captcha'),
    path('producao/status-login/', producao.status_login, name='producao_status_login'),
    path('producao/fechar/', producao.fechar_sessao, name='producao_fechar'),
    path('producao/buscar-medicos/', producao.buscar_medicos, name='producao_buscar_medicos'),
    path('producao/extrair/', producao.extrair_producao, name='producao_extrair'),
    path('producao/status-extracao/<int:pk>/', producao.status_extracao, name='producao_status_extracao'),
    path('producao/ver/<int:pk>/', producao.ver_extracao, name='producao_ver_extracao'),
    path('producao/historico/', producao.historico, name='producao_historico'),
    path('producao/excluir/<int:pk>/', producao.excluir_extracao, name='producao_excluir_extracao'),
    path('producao/excluir-varias/', producao.excluir_varias, name='producao_excluir_varias'),
    path('producao/<int:pk>/csv/', producao.exportar_csv, name='producao_exportar_csv'),
    path('producao/<int:pk>/json/', producao.exportar_json, name='producao_exportar_json'),

    # =========================================================
    # REPASSE
    # =========================================================
    path('producao/<int:extracao_pk>/repasse/', repasse.abrir_repasse, name='producao_ir_repasse'),
    path('repasse/<int:pk>/', repasse.ver_repasse, name='repasse_ver'),
    path('repasse/<int:pk>/excel/', repasse.exportar_excel, name='repasse_excel'),
    path('repasse/<int:pk>/finalizar/', repasse.finalizar_repasse, name='repasse_finalizar'),
    path('repasse/<int:pk>/reabrir/', repasse.reabrir_repasse, name='repasse_reabrir'),
    path('repasse/item/<int:pk>/atualizar/', repasse.atualizar_item, name='repasse_atualizar_item'),
    path('repasse/<int:pk>/marcar-todas/', repasse.marcar_todas, name='repasse_marcar_todas'),
    path('repasse/<int:pk>/arredondar/', repasse.arredondar, name='repasse_arredondar'),
    path('repasse/<int:pk>/recalcular/', repasse.recalcular, name='repasse_recalcular'),
    path('repasse/<int:pk>/zerar/', repasse.zerar_valores, name='repasse_zerar'),
    path('repasse/item/<int:pk>/escolher-minuto/', repasse.escolher_minuto, name='repasse_escolher_minuto'),

    # =========================================================
    # RELATÓRIOS
    # =========================================================
    path('relatorios/', relatorios.home, name='relatorios_home'),
    path('relatorios/gerar-excel/', relatorios.gerar_excel, name='relatorios_gerar_excel'),
    path('relatorios/reabrir-varios/', relatorios.reabrir_varios, name='relatorios_reabrir_varios'),
]