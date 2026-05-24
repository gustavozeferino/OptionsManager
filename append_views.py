append_code = """
from django.http import JsonResponse, HttpResponse
from django.db import connections
import csv

@user_passes_test(apenas_admin)
def db_viewer(request):
    \"\"\"View principal do visualizador de tabelas.\"\"\"
    tables_info = []
    # Lista todas as conexões disponíveis (default, b3_data, etc)
    for db_alias in connections:
        conn = connections[db_alias]
        try:
            tables = conn.introspection.table_names()
            for t in sorted(tables):
                tables_info.append({'db': db_alias, 'table': t})
        except Exception:
            pass # ignora bancos desconectados
            
    return render(request, 'core/db_viewer.html', {'tables_info': tables_info})

@user_passes_test(apenas_admin)
def db_viewer_data(request):
    \"\"\"API para DataTables (Server-side processing).\"\"\"
    db_alias = request.GET.get('db', 'default')
    table_name = request.GET.get('table')
    
    # DataTables params
    draw = int(request.GET.get('draw', 1))
    start = int(request.GET.get('start', 0))
    length = int(request.GET.get('length', 25))
    search_value = request.GET.get('search[value]', '').strip()
    
    if not table_name:
        return JsonResponse({'error': 'No table specified'})

    try:
        conn = connections[db_alias]
    except KeyError:
        return JsonResponse({'error': 'Invalid database alias'})
        
    with conn.cursor() as cursor:
        # Obter schema/colunas
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 0")
        columns = [col[0] for col in cursor.description]
        
        # Filtro Global
        where_clause = ""
        params = []
        if search_value:
            conditions = []
            for col in columns:
                conditions.append(f'"{col}"::text ILIKE %s')
                params.append(f'%{search_value}%')
            if conditions:
                where_clause = "WHERE " + " OR ".join(conditions)
        
        # Contagem Total
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        recordsTotal = cursor.fetchone()[0]
        
        # Contagem Filtrada
        recordsFiltered = recordsTotal
        if where_clause:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name} {where_clause}", params)
            recordsFiltered = cursor.fetchone()[0]
        
        # Ordenação
        order_col_idx = request.GET.get('order[0][column]')
        order_dir = request.GET.get('order[0][dir]', 'asc')
        order_clause = ""
        if order_col_idx is not None and order_col_idx.isdigit():
            idx = int(order_col_idx)
            col_name = request.GET.get(f'columns[{idx}][data]')
            if col_name in columns:
                if order_dir.lower() not in ['asc', 'desc']:
                    order_dir = 'asc'
                order_clause = f'ORDER BY "{col_name}" {order_dir}'

        # Busca Dados Paginados
        query = f"SELECT * FROM {table_name} {where_clause} {order_clause} LIMIT %s OFFSET %s"
        cursor.execute(query, params + [length, start])
        rows = cursor.fetchall()

        # Montar os dados como lista de dicionários
        data = []
        for row in rows:
            # Converto os valores p/ string pra evitar erros de serialização no JSON (Decimal, Data, etc)
            row_dict = {}
            for col, val in zip(columns, row):
                row_dict[col] = str(val) if val is not None else ''
            data.append(row_dict)
            
    return JsonResponse({
        "draw": draw,
        "recordsTotal": recordsTotal,
        "recordsFiltered": recordsFiltered,
        "columns": columns,
        "data": data
    })

@user_passes_test(apenas_admin)
def db_viewer_export(request):
    \"\"\"Exporta CSV dos dados (respeitando o limite e o filtro).\"\"\"
    db_alias = request.GET.get('db', 'default')
    table_name = request.GET.get('table')
    search_value = request.GET.get('search', '').strip()
    
    if not table_name:
        return HttpResponse('Tabela não especificada', status=400)

    try:
        conn = connections[db_alias]
    except KeyError:
        return HttpResponse('Banco não especificado', status=400)
        
    with conn.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 0")
        columns = [col[0] for col in cursor.description]
        
        where_clause = ""
        params = []
        if search_value:
            conditions = []
            for col in columns:
                conditions.append(f'"{col}"::text ILIKE %s')
                params.append(f'%{search_value}%')
            if conditions:
                where_clause = "WHERE " + " OR ".join(conditions)
        
        # Limite de segurança: 50 mil linhas para exportação
        query = f"SELECT * FROM {table_name} {where_clause} LIMIT 50000"
        cursor.execute(query, params)
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{table_name}_export.csv"'
        
        # BOM para Excel ler utf-8
        response.write(u'\\ufeff'.encode('utf8'))
        writer = csv.writer(response, delimiter=';')
        writer.writerow(columns)
        
        for row in cursor.fetchall():
            writer.writerow([str(r) if r is not None else '' for r in row])
            
    return response

"""

with open(r'c:\Users\Usuario\Projetos\OptionsManager\core\views.py', 'a', encoding='utf-8') as f:
    f.write('\n' + append_code)
print("Sucesso!")
