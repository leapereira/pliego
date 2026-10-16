#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo 'Falta el entorno local. Ejecuta bash scripts/setup.sh primero.'
  exit 1
fi
if [ ! -f web/dist/index.html ]; then
  npm --prefix web run build
fi
exec .venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port "${PLIEGO_PORT:-8000}"
