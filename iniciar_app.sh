#!/usr/bin/env bash
# Inicia o Conversor PDF -> Markdown no Linux ou macOS.
#
# Reaproveita um Python que ja tenha o Docling instalado; se nao houver,
# cria o ambiente virtual .venv do projeto e instala tudo.
set -uo pipefail
cd "$(dirname "$0")"

PORTA="${CONVERSOR_PORTA:-8000}"
MODO="venv"
PY=""

echo "=============================================================="
echo "  Conversor PDF para Markdown (Docling)"
echo "=============================================================="
echo

# ---------------------------------------------------------------- 1) Python
if [ -n "${CONVERSOR_PYTHON:-}" ]; then
  PY="$CONVERSOR_PYTHON"
  MODO="existente"
  echo "[1/3] Usando o Python indicado em CONVERSOR_PYTHON: $PY"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
  echo "[1/3] Usando o ambiente virtual .venv do projeto."
else
  BASE="$(command -v python3 || command -v python || true)"
  if [ -z "$BASE" ]; then
    echo "ERRO: Python nao encontrado. Instale o Python 3.10 ou superior."
    exit 1
  fi

  if "$BASE" -c "import docling" >/dev/null 2>&1; then
    echo "[1/3] Docling encontrado em: $BASE"
    echo "      Posso usar esse ambiente e instalar apenas o servidor web"
    echo "      (poucos MB), em vez de baixar o Docling de novo (mais de 2 GB)."
    read -r -p "Usar o ambiente que ja tem o Docling? (S/N) [S]: " RESPOSTA
    case "${RESPOSTA:-S}" in
      [Nn]*) PY="" ;;
      *) PY="$("$BASE" -c 'import sys; print(sys.executable)')"; MODO="existente" ;;
    esac
  fi

  if [ -z "$PY" ]; then
    echo "[1/3] Criando o ambiente virtual .venv do projeto..."
    "$BASE" -m venv .venv
    PY=".venv/bin/python"
    MODO="venv"
  fi
fi

# --------------------------------------------------------- 2) dependencias
echo
echo "[2/3] Conferindo as dependencias..."
if ! "$PY" -c "import fastapi, uvicorn, pymupdf" >/dev/null 2>&1; then
  if [ "$MODO" = "existente" ]; then
    echo "      Instalando apenas o servidor web neste ambiente..."
    "$PY" -m pip install fastapi "uvicorn[standard]" python-multipart pymupdf
  else
    echo "      Instalando tudo pela primeira vez (pode levar varios minutos)..."
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r requirements.txt
  fi
fi

if "$PY" -c "import docling" >/dev/null 2>&1; then
  echo "      Docling: OK"
else
  echo "      AVISO: o pacote 'docling' nao esta neste ambiente."
  echo "             Instale com: $PY -m pip install docling"
fi

# ------------------------------------------------------------- 3) servidor
echo
echo "[3/3] Abrindo o aplicativo em http://localhost:${PORTA}"
echo "Pressione Ctrl+C para encerrar."
echo
CONVERSOR_PORTA="$PORTA" exec "$PY" -m backend.main
