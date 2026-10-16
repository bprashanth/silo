#!/usr/bin/env bash
# Start/stop the isolated robust-voice call server on :8775 (does not touch the Telegram bot or :8765).
set -euo pipefail
cd "$(dirname "$0")"
STATE="$HOME/.local/share/silo-voice"; mkdir -p "$STATE"
if [[ "${1:-}" == stop ]]; then [[ -f "$STATE/server.pid" ]] && kill "$(cat "$STATE/server.pid")" 2>/dev/null; rm -f "$STATE/server.pid"; exit 0; fi
if [[ -f "$STATE/server.pid" ]] && kill -0 "$(cat "$STATE/server.pid")" 2>/dev/null; then echo "Already running: http://localhost:${PORT:-8775}"; exit 0; fi
export HF_HOME=/mnt/seagate/silo/voice-robust/hf HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VR_NEMO_CUDA_GRAPHS=0
setsid "$STATE/venv/bin/python" -u server.py > "$STATE/server.log" 2>&1 < /dev/null &
echo $! > "$STATE/server.pid"; echo "Starting http://localhost:${PORT:-8775} (models load in ~40 s); log: $STATE/server.log"
