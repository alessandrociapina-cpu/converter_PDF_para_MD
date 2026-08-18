@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Conversor PDF para Markdown
cd /d "%~dp0"

set "PORTA=%CONVERSOR_PORTA%"
if "%PORTA%"=="" set "PORTA=8000"
set "MODO=venv"

echo ==============================================================
echo   Conversor PDF para Markdown (Docling)
echo ==============================================================
echo.

rem ===============================================================
rem  1) Descobrir qual Python usar
rem ===============================================================
set "PY="

if defined CONVERSOR_PYTHON goto :usar_variavel
if exist ".venv\Scripts\python.exe" goto :usar_venv_existente
goto :procurar_python

:usar_variavel
set "PY=%CONVERSOR_PYTHON%"
set "MODO=existente"
echo [1/3] Usando o Python indicado na variavel CONVERSOR_PYTHON:
echo       %PY%
goto :checar_dependencias

:usar_venv_existente
set "PY=%~dp0.venv\Scripts\python.exe"
echo [1/3] Usando o ambiente virtual .venv do projeto.
goto :checar_dependencias

:procurar_python
set "BASE="
py -3 -c "import sys" >nul 2>nul
if !errorlevel! equ 0 set "BASE=py -3"
if not defined BASE (
    python -c "import sys" >nul 2>nul
    if !errorlevel! equ 0 set "BASE=python"
)
if not defined BASE goto :erro_sem_python

rem O Docling ja esta instalado neste Python?
%BASE% -c "import docling" >nul 2>nul
if !errorlevel! neq 0 goto :criar_venv

echo [1/3] Docling encontrado no Python padrao deste computador.
echo.
echo       Posso usar esse mesmo ambiente e instalar apenas o servidor web
echo       (poucos MB), em vez de baixar o Docling e o PyTorch de novo
echo       em um ambiente novo (mais de 2 GB).
echo.
set "RESPOSTA="
set /p "RESPOSTA=Usar o ambiente que ja tem o Docling? (S/N) [S]: "
if /i "!RESPOSTA!"=="N" goto :criar_venv

for /f "delims=" %%P in ('%BASE% -c "import sys; print(sys.executable)"') do set "PY=%%P"
set "MODO=existente"
echo       Ambiente escolhido: !PY!
goto :checar_dependencias

:criar_venv
echo [1/3] Criando o ambiente virtual .venv do projeto ...
%BASE% -m venv .venv
if not exist ".venv\Scripts\python.exe" goto :erro_venv
set "PY=%~dp0.venv\Scripts\python.exe"
set "MODO=venv"
goto :checar_dependencias

rem ===============================================================
rem  2) Conferir/instalar as dependencias
rem ===============================================================
:checar_dependencias
echo.
echo [2/3] Conferindo as dependencias ...

"%PY%" -c "import fastapi, uvicorn, pymupdf" >nul 2>nul
if !errorlevel! equ 0 goto :conferir_docling

if "%MODO%"=="existente" goto :instalar_servidor

echo       Instalando tudo pela primeira vez. Isso pode levar varios minutos.
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if !errorlevel! neq 0 goto :erro_pip
goto :conferir_docling

:instalar_servidor
echo       Instalando apenas o servidor web neste ambiente (poucos MB) ...
"%PY%" -m pip install fastapi "uvicorn[standard]" python-multipart pymupdf
if !errorlevel! neq 0 goto :erro_pip

:conferir_docling
"%PY%" -c "import docling" >nul 2>nul
if !errorlevel! equ 0 (
    echo       Docling: OK
) else (
    echo.
    echo       AVISO: o pacote 'docling' nao esta neste ambiente.
    echo              O app abre, mas a conversao vai falhar.
    echo              Instale com: "%PY%" -m pip install docling
    echo.
)

rem ===============================================================
rem  3) Subir o servidor e abrir o navegador
rem ===============================================================
echo.
echo [3/3] Abrindo o aplicativo em http://localhost:%PORTA%
echo.
echo Deixe esta janela aberta enquanto usar o aplicativo.
echo Para encerrar, feche a janela ou pressione Ctrl+C.
echo.

set "CONVERSOR_PORTA=%PORTA%"
"%PY%" -m backend.main

echo.
echo Servidor encerrado.
pause
exit /b 0

rem ===============================================================
rem  Mensagens de erro
rem ===============================================================
:erro_sem_python
echo.
echo ERRO: nao encontrei o Python neste computador.
echo.
echo Se voce ja usa o Docling em um ambiente virtual, informe o caminho
echo do python.exe dele antes de rodar este arquivo. Exemplo:
echo.
echo     set CONVERSOR_PYTHON=C:\Users\Voce\docling\.venv\Scripts\python.exe
echo     iniciar_app.bat
echo.
echo Ou instale o Python 3.10+ em https://www.python.org/downloads/
echo marcando a opcao "Add Python to PATH".
echo.
pause
exit /b 1

:erro_venv
echo.
echo ERRO: falha ao criar o ambiente virtual .venv.
pause
exit /b 1

:erro_pip
echo.
echo ERRO: nao foi possivel instalar as dependencias.
echo Verifique a conexao com a internet e tente novamente.
pause
exit /b 1
