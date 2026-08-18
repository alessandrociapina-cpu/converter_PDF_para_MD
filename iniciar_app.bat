@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
title Conversor PDF para Markdown
cd /d "%~dp0"

set "PORTA=%CONVERSOR_PORTA%"
if "%PORTA%"=="" set "PORTA=8000"

echo ==============================================================
echo   Conversor PDF para Markdown (Docling)
echo ==============================================================
echo.

rem ---------------------------------------------------------------
rem 1) Localiza o Python do ambiente virtual (.venv)
rem ---------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Ambiente virtual nao encontrado. Criando .venv ...
    where py >nul 2>nul
    if !errorlevel! equ 0 (
        py -3 -m venv .venv
    ) else (
        where python >nul 2>nul
        if !errorlevel! neq 0 (
            echo.
            echo ERRO: Python nao foi encontrado neste computador.
            echo Instale o Python 3.10 ou superior em https://www.python.org/downloads/
            echo e marque a opcao "Add Python to PATH" durante a instalacao.
            echo.
            pause
            exit /b 1
        )
        python -m venv .venv
    )
    if not exist ".venv\Scripts\python.exe" (
        echo ERRO: falha ao criar o ambiente virtual.
        pause
        exit /b 1
    )
)

set "PY=.venv\Scripts\python.exe"

rem ---------------------------------------------------------------
rem 2) Instala as dependencias na primeira execucao
rem ---------------------------------------------------------------
"%PY%" -c "import fastapi, uvicorn, pymupdf" >nul 2>nul
if !errorlevel! neq 0 (
    echo [2/3] Instalando dependencias ^(pode levar varios minutos na primeira vez^) ...
    "%PY%" -m pip install --upgrade pip
    "%PY%" -m pip install -r requirements.txt
    if !errorlevel! neq 0 (
        echo.
        echo ERRO: nao foi possivel instalar as dependencias.
        echo Verifique sua conexao com a internet e tente novamente.
        pause
        exit /b 1
    )
) else (
    echo [2/3] Dependencias ja instaladas.
)

"%PY%" -c "import docling" >nul 2>nul
if !errorlevel! neq 0 (
    echo.
    echo AVISO: o pacote 'docling' nao esta instalado neste ambiente.
    echo        Rode: .venv\Scripts\python.exe -m pip install docling
    echo.
)

rem ---------------------------------------------------------------
rem 3) Sobe o servidor local e abre o navegador
rem ---------------------------------------------------------------
echo [3/3] Iniciando o servidor em http://localhost:%PORTA%
echo.
echo Deixe esta janela aberta enquanto usar o aplicativo.
echo Para encerrar, feche a janela ou pressione Ctrl+C.
echo.

set "CONVERSOR_PORTA=%PORTA%"
"%PY%" -m backend.main

echo.
echo Servidor encerrado.
pause
