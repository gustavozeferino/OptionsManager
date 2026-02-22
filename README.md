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
