#!/usr/bin/env bash
# Inicia o Conversor PDF -> Markdown no Linux ou macOS.
set -euo pipefail
cd "$(dirname "$0")"

PORTA="${CONVERSOR_PORTA:-8000}"

echo "=============================================================="
echo "  Conversor PDF para Markdown (Docling)"
echo "=============================================================="

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/3] Criando ambiente virtual (.venv)..."
  python3 -m venv .venv
fi

PY=".venv/bin/python"

if ! "$PY" -c "import fastapi, uvicorn, pymupdf" >/dev/null 2>&1; then
  echo "[2/3] Instalando dependencias (pode levar varios minutos na primeira vez)..."
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r requirements.txt
else
  echo "[2/3] Dependencias ja instaladas."
fi

if ! "$PY" -c "import docling" >/dev/null 2>&1; then
  echo "AVISO: o pacote 'docling' nao esta instalado. Rode: $PY -m pip install docling"
fi

echo "[3/3] Servidor em http://localhost:${PORTA}"
echo "Pressione Ctrl+C para encerrar."
CONVERSOR_PORTA="$PORTA" exec "$PY" -m backend.main
