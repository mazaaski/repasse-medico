# Repasse Médico

Sistema web interno (Django) para acompanhar a **produção médica** no SIRESP e calcular o **repasse** (pagamento por produção) dos profissionais.

O sistema faz o seguinte:

1. **Extrai** a produção por especialidade e profissional direto do portal SIRESP, usando Selenium em modo headless. O login exige CAPTCHA, que é exibido na própria interface web para ser digitado pelo usuário.
2. **Converte** a produção em minutos e valores, usando as regras cadastradas (minutos por tipo de atendimento, grupos de valor, bônus e exceções).
3. **Monta os repasses** por profissional, com edição manual dos itens, arredondamento, recálculo e finalização.
4. **Gera relatórios** em PDF e Excel, por repasse ou por lote de repasses.
5. **Registra auditoria** das ações feitas no sistema e controla acesso por usuário e papel.

## Stack

- Python 3 + Django 5.0
- SQLite (banco padrão, `db.sqlite3`)
- Selenium + webdriver-manager (automação do SIRESP)
- pandas, openpyxl, xlrd (planilhas e Excel)
- reportlab (PDF)
- Bootstrap 5.3 e CSS próprio em `static/siresp_app/css/estilo.css`

## Estrutura do projeto

```
siresp_project/      configurações do Django (settings, urls, wsgi/asgi)
siresp_app/
  models.py          modelos: grupos de valor, especialidades, profissionais,
                     regras de minuto, extrações, repasses, auditoria etc.
  views/             telas, agrupadas por área (painel, producao, repasse,
                     repasse_lote, relatorios, config, equipes, profissionais...)
  services/          regras de negócio (scraper, repasse, regras, valores,
                     planilhas, PDF, auditoria, dashboard...)
  templates/         HTML das telas
  migrations/        migrações do banco
siresp_scraper.py    lógica de navegação e extração no SIRESP (Selenium)
limpar_dados.py      apaga dados de teste/produção, mantendo usuários e o grupo Padrão
diagnostico.py       gera um relatório de diagnóstico do projeto
servico.py           inicializa o servidor como serviço do Windows
redirect.py / redirect_http.py   redirecionamentos HTTP → HTTPS
*.bat                instalar/remover o serviço Windows (NSSM)
docs/padrao-visual.md  padrão visual e componentes das telas
```

## Como rodar localmente

Pré-requisitos: Python 3.12 e Google Chrome instalado (usado pelo Selenium).

```bash
python -m venv venv
source venv/bin/activate        # no Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Por padrão `DEBUG` vem ligado (`DJANGO_DEBUG=1`). Em produção, defina `DJANGO_DEBUG=0`.

Hosts permitidos (`ALLOWED_HOSTS`): `127.0.0.1`, `localhost`, `172.16.0.20` e `repasse-medico.alsf.org.br`.

## Testes

```bash
# testes automáticos (rápidos)
python manage.py test siresp_app

# inclui o roteiro completo no Chrome e os testes de tela do login no SIRESP
RUN_BROWSER_TESTS=1 python manage.py test siresp_app
```

## Execução como serviço no Windows

Os scripts `instalar_servico.bat` e `remover_servico.bat` registram o sistema como serviço usando o [NSSM](https://nssm.cc/). Eles devem ser executados como administrador e esperam o projeto em `C:\ProjetoSiresp`.

O `servico.py` sobe o servidor na porta fixa **8002**, com HTTPS quando os arquivos `cert.pem` e `key.pem` estão em `C:\ProjetoSiresp`, e HTTP caso contrário. Os logs ficam em `servico.log`.

## Dados e arquivos sensíveis

Não versionar (já estão no `.gitignore`):

- `db.sqlite3` e demais bancos locais
- arquivos `.env` e `local_settings.py`
- certificados e chaves (`*.pem`, `*.key`, `*.crt`)
- `media/`, `staticfiles/`, logs

Credenciais do SIRESP são salvas na tabela de configuração de login do próprio sistema. Não coloque senhas no código.

## Padrão visual

Antes de criar uma tela nova, siga [docs/padrao-visual.md](docs/padrao-visual.md). Ele descreve a estrutura base dos templates, os componentes disponíveis e o uso de cores.
