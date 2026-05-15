# OptionsManager

Sistema de gerenciamento de opções financeiras desenvolvido com Django.

## Requisitos

- Python 3.11+
- Django 4.2+

## Instalação

1. Crie e ative o ambiente virtual:
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

2. Instale as dependências:
```bash
pip install -r requirements.txt
```

3. Execute as migrações:
```bash
python manage.py makemigrations
python manage.py migrate
```

4. Crie um superusuário:
```bash
python manage.py createsuperuser
```

5. Execute o servidor de desenvolvimento:
```bash
python manage.py runserver
```

## Estrutura do Projeto

- `users/`: App para gerenciamento de usuários com Custom User Model
- `core/`: App principal com modelos Estrutura e Ordem
- `templates/`: Templates HTML com Bootstrap 5

## Modelos

### Estrutura
- Agrupa múltiplas ordens relacionadas
- Campos: nome, descricao, user, ativa

### Ordem
- Representa uma ordem de compra ou venda
- Campos: estrutura, ativo, data, tipo, quantidade, preco

## Testes

Execute os testes com:
```bash
python manage.py test
```

# Próximos passos

* Analisar pré-requisitos para colocar em produção no vecel
* Implementar sistema de gestão de senha para o usuário (reset, etc.)
* Colocar no log mensagens de erro
* Identificar vencimento semanal ou mensal e colocar no banco de dados (ou criar uma tabela de vencimentos)

## Página de opções
* Colocar um menu de meses na parte de cima (menu horizontal). Quando o usuário escolhe um mês, mostrar os vencimentos dentro deste e selecionar por padrão o vencimento mensal.
* Organizar as opções no formato de strike no meio, calls na direita e put na esquerda com último preço e última data negociado

## Importação de ordens
* Implementar importação via tabela de ordens do profit e
* tabela gerada no site da B3

Scripts de Linha de Comando (Management Commands):

Comandos para execução via terminal, cada um com barra de progresso e impressão do resumo ao final:
python manage.py upload_cadastro "caminho/do/arquivo.csv"
python manage.py upload_negocios "caminho/do/arquivo.csv"
python manage.py upload_posicoes "caminho/do/arquivo.csv"



1. Reposicionamento de Models
Renomeamos o modelo NegocioDiario original para BoletimNegocioDiario que funcionará como repositório dos dados brutos em formato CSV.
Criamos o modelo CotacaoHistorica para armazenar o parsing bruto do arquivo TXT/ZIP posicional (COTAHIST).
Refizemos o modelo NegocioDiario para servir como o Golden Source, a tabela consolidada com os campos definidos (preco_vwap, etc.), de acordo com a estrutura solicitada.
As "migrations" já foram executadas e aplicadas ao banco de dados com sucesso.
2. Ingestão de Dados (COTAHIST)
Rotina Posicional: Centralizamos a rotina de fatiamento no arquivo dadosb3/services.py, aplicando os mesmos cortes definidos no script original b3_to_csv.py, efetuando divisões por 100 para converter os decimais e traduzindo strings para datas de forma segura.
Interface Web: Modificamos o template dadosb3/templates/dadosb3/upload.html adicionando a opção "Cotação Histórica B3 (TXT/ZIP)". Também configuramos a lógica e threading assíncrona no dadosb3/views.py para processar a ingestão dos dados sem travar o front-end.
Linha de Comando (CLI): Criamos o arquivo dadosb3/management/commands/import_cothist.py para realizar a importação através do comando python manage.py import_cothist --file caminho/do/arquivo.zip.
3. Protocolo de Consolidação (Golden Source)
Implementamos o script dadosb3/management/commands/consolidate_negocios.py.
Idempotência: A rotina percorre ambas as tabelas fontes (CotacaoHistorica e BoletimNegocioDiario) e aplica os dados de forma idenpotente, dando prioridade ou apenas preenchendo os campos faltantes sem criar duplicações.
Normalização: Foi implementada a função que normaliza o campo segmento (CASH, EQUITY CALL, EQUITY PUT, MERCADO FRACIONÁRIO) baseado nas colunas CODBDI e TPMERC.
Performance: A rotina roda todo o processamento de consolidação e executa salvamentos utilizando bulk_create e bulk_update para ganhar mais escalabilidade no momento de inserção.
A consolidação pode ser chamada tanto pelo comando $ python manage.py consolidate_negocios --date YYYY-MM-DD para uma data específica, quanto usando --all para consolidar o histórico completo.
Toda a arquitetura proposta para a melhoria de ingestão e tolerância de redundâncias foi finalizada.