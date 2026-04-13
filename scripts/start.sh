#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source ".venv/bin/activate"

if [ ! -f ".venv/.deps-installed" ]; then
  pip install -e '.[dev]'
  touch ".venv/.deps-installed"
fi

exec uvicorn app.main:app --reload
