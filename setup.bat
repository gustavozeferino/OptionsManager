@echo off
echo ========================================
echo OptionsManager - Setup Inicial
echo ========================================
echo.

REM Verificar se Python está instalado
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado!
    echo Por favor, instale Python 3.11+ e tente novamente.
    pause
    exit /b 1
)

echo [1/5] Criando ambiente virtual...
python -m venv venv
if errorlevel 1 (
    echo [ERRO] Falha ao criar ambiente virtual
    pause
    exit /b 1
)

echo [2/5] Ativando ambiente virtual...
call venv\Scripts\activate.bat

echo [3/5] Instalando dependencias...
pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERRO] Falha ao instalar dependencias
    pause
    exit /b 1
)

echo [4/5] Criando migracoes...
python manage.py makemigrations
if errorlevel 1 (
    echo [ERRO] Falha ao criar migracoes
    pause
    exit /b 1
)

echo [5/5] Aplicando migracoes...
python manage.py migrate
if errorlevel 1 (
    echo [ERRO] Falha ao aplicar migracoes
    pause
    exit /b 1
)

echo.
echo ========================================
echo Setup concluido com sucesso!
echo ========================================
echo.
echo Proximos passos:
echo 1. Crie um superusuario: python manage.py createsuperuser
echo 2. Execute o servidor: python manage.py runserver
echo 3. Acesse: http://127.0.0.1:8000
echo.
pause
