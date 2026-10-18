#!/usr/bin/env bash
# Start API + note how to start the React UI.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

if [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
else
  PY=python3
fi

export PYTHONPATH=src
echo "API → http://127.0.0.1:8088"
echo "Then in another terminal:"
echo "  cd src/company_match/web && npm install && npm run dev"
echo "UI  → http://localhost:5173"
exec "$PY" -m uvicorn company_match.api:app --app-dir src --reload --host 127.0.0.1 --port 8088
