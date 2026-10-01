from django.urls import path
from .views import auth, config, painel, producao, repasse, repasse_lote, relatorios, profissionais, equipes, auditoria_view

app_name = 'siresp_app'

urlpatterns = [
    # Autenticação
    path('login/', auth.login_view, name='login'),
    path('logout/', auth.logout_view, name='logout'),
    path('', painel.home, name='home'),

    # =========================================================
    # CONFIGURAÇÕES — GRUPOS
    # =========================================================
    path('config/', config.lista_grupos, name='config_lista'),
    path('config/novo/', config.novo_grupo, name='config_novo'),
    path('config/<int:pk>/editar/', config.editar_grupo, name='config_editar'),
    path('config/excluir-varios/', config.excluir_grupos, name='config_excluir_grupos'),
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
    path('producao/tela-siresp/', producao.tela_siresp, name='producao_tela_siresp'),
    path('producao/escolher-unidade/', producao.escolher_unidade, name='producao_escolher_unidade'),
    path('producao/esquecer-unidade/', producao.esquecer_unidade, name='producao_esquecer_unidade'),
    path('producao/recarregar-captcha/', producao.recarregar_captcha, name='producao_recarregar_captcha'),
    path('producao/status-login/', producao.status_login, name='producao_status_login'),
    path('producao/fechar/', producao.fechar_sessao, name='producao_fechar'),
    path('producao/buscar-medicos/', producao.buscar_medicos, name='producao_buscar_medicos'),
    path('producao/lote/iniciar/', producao.lote_iniciar, name='producao_lote_iniciar'),
    path('producao/lote/status/', producao.lote_status, name='producao_lote_status'),
    path('producao/lote/cancelar/', producao.lote_cancelar, name='producao_lote_cancelar'),
    path('producao/lote/pendentes/', producao.lote_pendentes, name='producao_lote_pendentes'),
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
    path('repasse/lote/', repasse_lote.lote_home, name='repasse_lote'),
    path('repasse/lote/apagar/', repasse_lote.lote_apagar, name='repasse_lote_apagar'),
    path('repasse/lote/gerar/', repasse_lote.lote_gerar, name='repasse_lote_gerar'),
    path('repasse/lote/salvar/', repasse_lote.lote_salvar, name='repasse_lote_salvar'),
    path('repasse/lote/finalizar/', repasse_lote.lote_finalizar, name='repasse_lote_finalizar'),
    path('repasse/lote/relatorio/', repasse_lote.lote_relatorio, name='repasse_lote_relatorio'),
    path('repasse/lote/relatorio/pdf/', repasse_lote.lote_relatorio_pdf, name='repasse_lote_relatorio_pdf'),
    path('repasse/lote/relatorio/excel/', repasse_lote.lote_relatorio_excel,
         name='repasse_lote_relatorio_excel'),
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
    # PROFISSIONAIS (base)
    # =========================================================
    path('auditoria/', auditoria_view.lista, name='auditoria_lista'),
    path('auditoria/csv/', auditoria_view.exportar_csv, name='auditoria_csv'),
    path('equipes/', equipes.lista, name='equipes_lista'),
    path('equipes/nova/', equipes.nova, name='equipes_nova'),
    path('equipes/<int:pk>/editar/', equipes.editar, name='equipes_editar'),
    path('equipes/<int:pk>/remover/', equipes.remover, name='equipes_remover'),
    path('profissionais/', profissionais.lista, name='profissionais_lista'),
    path('profissionais/massa/', profissionais.acao_em_massa, name='profissionais_massa'),
    path('profissionais/adicionar-varios/', profissionais.adicionar_varios, name='profissionais_adicionar_varios'),
    path('profissionais/novo/', profissionais.novo, name='profissionais_novo'),
    path('profissionais/<int:pk>/alternar/', profissionais.alternar, name='profissionais_alternar'),
    path('profissionais/<int:pk>/remover/', profissionais.remover, name='profissionais_remover'),

    # =========================================================
    # RELATÓRIOS
    # =========================================================
    path('relatorios/', relatorios.home, name='relatorios_home'),
    path('relatorios/gerar-pdf/', relatorios.gerar_pdf, name='relatorios_gerar_pdf'),
    path('relatorios/gerar-excel/', relatorios.gerar_excel, name='relatorios_gerar_excel'),
    path('relatorios/reabrir-varios/', relatorios.reabrir_varios, name='relatorios_reabrir_varios'),
]