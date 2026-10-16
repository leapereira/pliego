#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then
  uv venv --allow-existing .venv
  uv pip install --python .venv/bin/python -r requirements.txt
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
npm --prefix web ci
npm --prefix web run build
echo 'Listo. Ejecuta bash scripts/start.sh y abre http://127.0.0.1:8000'
