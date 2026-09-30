"""
Script pra limpar os dados mantendo:
  - Usuários web (superuser)
  - Grupo Padrão
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'siresp_project.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

from siresp_app.models import (
    GrupoValor, EspecialidadeGrupo, EspecialidadeConhecida,
    ConfiguracaoLogin, RegraMinuto,
    SessaoSiresp, Extracao, ItemProducao,
    Repasse, ItemRepasse,
)

print("=" * 60)
print("LIMPEZA DE DADOS")
print("=" * 60)

# Confirma
resp = input("Apagar TODOS os dados (mantém users e Padrão)? (s/N): ")
if resp.lower() != 's':
    print("Cancelado.")
    sys.exit(0)

# Contadores
print()
print("Antes:")
print(f"  Grupos de valor: {GrupoValor.objects.count()}")
print(f"  Especialidades conhecidas: {EspecialidadeConhecida.objects.count()}")
print(f"  Regras de minutos: {RegraMinuto.objects.count()}")
print(f"  Extrações: {Extracao.objects.count()}")
print(f"  Itens de produção: {ItemProducao.objects.count()}")
print(f"  Repasses: {Repasse.objects.count()}")
print(f"  Itens de repasse: {ItemRepasse.objects.count()}")
print()

# Apaga em ordem (pra respeitar foreign keys)
ItemRepasse.objects.all().delete()
Repasse.objects.all().delete()
ItemProducao.objects.all().delete()
Extracao.objects.all().delete()
SessaoSiresp.objects.all().delete()
RegraMinuto.objects.all().delete()
EspecialidadeConhecida.objects.all().delete()
ConfiguracaoLogin.objects.all().delete()

# Grupos: apaga todos exceto Padrão
GrupoValor.objects.exclude(nome__iexact='Padrão').delete()
# Limpa as especialidades dos grupos restantes
EspecialidadeGrupo.objects.all().delete()

print("Depois:")
print(f"  Grupos de valor: {GrupoValor.objects.count()}")
print(f"  Especialidades conhecidas: {EspecialidadeConhecida.objects.count()}")
print(f"  Regras de minutos: {RegraMinuto.objects.count()}")
print(f"  Extrações: {Extracao.objects.count()}")
print(f"  Itens de produção: {ItemProducao.objects.count()}")
print(f"  Repasses: {Repasse.objects.count()}")
print(f"  Itens de repasse: {ItemRepasse.objects.count()}")
print()
print("=" * 60)
print("LIMPEZA CONCLUÍDA!")
print("=" * 60)