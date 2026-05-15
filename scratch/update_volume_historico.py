import os
import sys
import django

sys.path.insert(0, r'C:\Users\Usuario\Projetos\OptionsManager')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'optionsmanager.settings')
django.setup()

from dadosb3.models import NegocioDiario
from core.models import HistoricoPreco, AtivoB3

print("Carregando mapa NegocioDiario (isin, data_pregao) -> volume_financeiro...")
mapa_volume = {}
for nd in NegocioDiario.objects.values('isin', 'data_pregao', 'volume_financeiro'):
    if nd['volume_financeiro'] is not None:
        mapa_volume[(nd['isin'], nd['data_pregao'])] = nd['volume_financeiro']

print(f"  -> {len(mapa_volume)} entradas carregadas do NegocioDiario.")

print("Carregando HistoricoPreco com ISIN do AtivoB3...")
historicos = list(
    HistoricoPreco.objects
    .select_related('ativo')
    .values('id', 'data_pregao', 'ativo__codigo_isin', 'volume_financeiro')
)
print(f"  -> {len(historicos)} entradas em HistoricoPreco.")

# Monta lista de objetos para atualizar em bulk
to_update = []
nao_encontrados = 0
sem_alteracao = 0
CHUNK = 2000

print("Processando...")
batch = []
total_updated = 0

for h in historicos:
    chave = (h['ativo__codigo_isin'], h['data_pregao'])
    vol_novo = mapa_volume.get(chave)

    if vol_novo is None:
        nao_encontrados += 1
        continue

    if h['volume_financeiro'] == vol_novo:
        sem_alteracao += 1
        continue

    obj = HistoricoPreco(id=h['id'], volume_financeiro=vol_novo)
    batch.append(obj)

    if len(batch) >= CHUNK:
        HistoricoPreco.objects.bulk_update(batch, ['volume_financeiro'])
        total_updated += len(batch)
        print(f"  -> {total_updated} atualizados ate agora...")
        batch = []

if batch:
    HistoricoPreco.objects.bulk_update(batch, ['volume_financeiro'])
    total_updated += len(batch)

print(f"\nConcluido!")
print(f"  Atualizados:     {total_updated}")
print(f"  Sem alteracao:   {sem_alteracao}")
print(f"  Nao encontrados: {nao_encontrados}")
