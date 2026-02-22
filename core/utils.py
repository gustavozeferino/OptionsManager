"""
Funções utilitárias para processamento de dados B3.
"""
import pandas as pd
from django.db import transaction
from decimal import Decimal, InvalidOperation
from .models import AtivoB3


def processar_cadastro_b3(file_path):
    """
    Processa um arquivo CSV da B3 e salva/atualiza os registros no modelo AtivoB3.
    
    Args:
        file_path (str): Caminho para o arquivo CSV
        
    Returns:
        dict: Estatísticas do processamento {
            'total_lidas': int,
            'filtradas': int,
            'criadas': int,
            'atualizadas': int,
            'erros': list
        }
    """
    # Lista de ativos permitidos
    ATIVOS_PERMITIDOS = ['BOVA11', 'PETR4', 'VALE3']
    
    stats = {
        'total_lidas': 0,
        'filtradas': 0,
        'criadas': 0,
        'atualizadas': 0,
        'erros': []
    }
    
    try:
        # Lê o CSV pulando as 2 primeiras linhas e usando separador ;
        df = pd.read_csv(
            file_path,
            sep=';',
            skiprows=2,
            encoding='utf-8',
            on_bad_lines='skip'
        )
        
        stats['total_lidas'] = len(df)
        
        # Filtra apenas os ativos permitidos
        df_filtrado = df[df['Ativo'].isin(ATIVOS_PERMITIDOS)].copy()
        stats['filtradas'] = len(df_filtrado)
        
        if df_filtrado.empty:
            return stats
        
        # Processa cada linha
        with transaction.atomic():
            for index, row in df_filtrado.iterrows():
                try:
                    # Extrai os dados das colunas
                    instrumento_financeiro = str(row.get('Instrumento financeiro', '')).strip()
                    ativo = str(row.get('Ativo', '')).strip()
                    codigo_isin = str(row.get('Código ISIN', '')).strip()
                    tipo_opcao = str(row.get('Tipo de opção', '')).strip()
                    
                    # Processa data de expiração
                    data_expiracao = None
                    data_str = str(row.get('Data de expiração', '')).strip()
                    if data_str and data_str != 'nan':
                        try:
                            # Tenta parsear a data (formato pode variar)
                            data_expiracao = pd.to_datetime(data_str, errors='coerce')
                            if pd.notna(data_expiracao):
                                data_expiracao = data_expiracao.date()
                        except Exception:
                            pass
                    
                    # Processa preço de exercício
                    preco_exercicio = None
                    preco_str = str(row.get('Preço de exercício', '')).strip()
                    if preco_str and preco_str != 'nan':
                        try:
                            # Remove caracteres não numéricos (exceto ponto e vírgula)
                            preco_limpo = preco_str.replace(',', '.').replace(' ', '')
                            preco_exercicio = Decimal(preco_limpo)
                        except (InvalidOperation, ValueError):
                            pass
                    
                    # Busca ou cria o registro
                    ativo_b3, created = AtivoB3.objects.update_or_create(
                        ativo=ativo,
                        codigo_isin=codigo_isin if codigo_isin else '',
                        preco_exercicio=preco_exercicio,
                        data_expiracao=data_expiracao,
                        defaults={
                            'instrumento_financeiro': instrumento_financeiro,
                            'tipo_opcao': tipo_opcao,
                        }
                    )
                    
                    if created:
                        stats['criadas'] += 1
                    else:
                        stats['atualizadas'] += 1
                        
                except Exception as e:
                    stats['erros'].append({
                        'linha': index + 3,  # +3 porque pulamos 2 linhas e index começa em 0
                        'erro': str(e),
                        'ativo': str(row.get('Ativo', 'N/A'))
                    })
    
    except Exception as e:
        stats['erros'].append({
            'linha': 'geral',
            'erro': f'Erro ao processar arquivo: {str(e)}',
            'ativo': 'N/A'
        })
    
    return stats
