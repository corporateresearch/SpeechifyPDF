#!/usr/bin/env bash
# Dev launcher: starts the FastAPI backend
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_ENV="speechifyPDF"

echo "▶ Starting Kokoro TTS on http://127.0.0.1:8000 ..."
cd "$ROOT/backend"
conda run --no-capture-output -n "$CONDA_ENV" uvicorn app:app --host 127.0.0.1 --port 8000
