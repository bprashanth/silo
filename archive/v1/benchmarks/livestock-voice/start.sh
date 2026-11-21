#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
STATE="$HOME/.local/share/silo-livestock-voice"
mkdir -p "$STATE"
if [[ "${1:-}" == stop ]]; then
  [[ ! -f "$STATE/server.pid" ]] || kill "$(cat "$STATE/server.pid")"
  exit 0
fi
if [[ -f "$STATE/server.pid" ]] && kill -0 "$(cat "$STATE/server.pid")" 2>/dev/null; then
  echo 'Already running: http://localhost:8765'; exit 0
fi
export PYTHONPATH="/mnt/seagate/silo/livestock-voice/packages${PYTHONPATH:+:$PYTHONPATH}"
export HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false NUMBA_CACHE_DIR=/mnt/seagate/silo/livestock-voice/numba-cache
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=1
export HOST="${HOST:-0.0.0.0}"
setsid "$STATE/venv/bin/python" -u server.py > "$STATE/server.log" 2>&1 < /dev/null &
echo $! > "$STATE/server.pid"
echo 'Starting http://localhost:8765; log:' "$STATE/server.log"
