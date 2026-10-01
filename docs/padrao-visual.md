# Padrão visual do Repasse Médico

Tudo é Bootstrap 5.3 + `static/siresp_app/css/estilo.css` (as regras estão no cabeçalho do arquivo).
Antes de criar uma tela nova, copie uma existente e siga a lista abaixo.

## Estrutura de uma tela
```django
{% extends "siresp_app/base.html" %}
{% block title %}Nome da aba{% endblock %}
{% block icone_pagina %}bi-people{% endblock %}
{% block titulo_pagina %}Título da página{% endblock %}
{% block subtitulo_pagina %}<p class="page-subtitle">Uma frase explicando a tela.</p>{% endblock %}
{% block acoes_pagina %}  {# botões do canto direito do cabeçalho #}  {% endblock %}
{% block content %} ... {% endblock %}
```
O cabeçalho (título, subtítulo, ações) é desenhado pela `base.html`. Não escreva `<h2>` no conteúdo.

## Componentes
| Para quê | Use |
|---|---|
| Explicação da tela | `<div class="dica">` (neutra: `dica dica-neutra`) |
| Mensagens do sistema | `messages` → `.alert` (já tratado na base) |
| Tabela | `.card > .table-responsive > table.table.table-hover.align-middle` (sem `table-dark`/`striped`) |
| Número / valor / horas | célula com classe `num` (alinhada à direita) |
| Situação do repasse | `{% include "siresp_app/_situacao.html" with status="finalizado" %}` (`finalizado`, `rascunho`, `extraido`, `pendente`) |
| Etiqueta pequena | `<span class="chip">` (`chip-azul`, `chip-verde`, `chip-ambar`, `chip-vermelho`) |
| Barra de filtros | `<form class="toolbar filtros">` com `form-control-sm`/`form-select-sm` |
| Lista vazia | `<div class="vazio"><i class="bi ..."></i>Texto</div>` |
| Indicadores | `.kpi-label`, `.kpi-valor`, `.kpi-sub` |
| Formulário | `<form class="card form-card">` |
| Modal | `modal-header` simples (sem cor); ícone no `modal-title` |
| Valores em reais | `{{ x\|floatformat:"2g" }}` (e `toLocaleString('pt-BR')` no JavaScript) |

## Botões
- Ação principal da tela: `btn btn-primary`.
- Secundária / voltar / cancelar: `btn btn-outline-secondary`.
- Excluir: `btn btn-outline-danger` (com confirmação).
- Exportar: Excel `btn-success`, PDF `btn-danger`.
- Dentro de cartões, barras de ferramentas e linhas de tabela: `btn-sm`.

## Cores
Azul = ação; verde = concluído/finalizado; âmbar = rascunho/atenção; vermelho = erro/exclusão; cinza = secundário.
Linhas de tabela por situação: `table-success` (finalizado) e `table-warning` (rascunho).

## Como testar
- `python manage.py test siresp_app` — testes automáticos (rápidos).
- `RUN_BROWSER_TESTS=1 python manage.py test siresp_app` — inclui o roteiro completo no Chrome
  (`tests_e2e.py`) e os testes de tela do login no SIRESP.
