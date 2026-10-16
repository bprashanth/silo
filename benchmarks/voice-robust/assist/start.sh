#!/usr/bin/env bash
# Start/stop the operator-assist console on :8776 (does not touch :8775, the Telegram bot or :8765).
set -euo pipefail
cd "$(dirname "$0")"
STATE="$HOME/.local/share/silo-voice"; mkdir -p "$STATE"
PID="$STATE/assist.pid"
if [[ "${1:-}" == stop ]]; then [[ -f "$PID" ]] && kill "$(cat "$PID")" 2>/dev/null; rm -f "$PID"; exit 0; fi
if [[ -f "$PID" ]] && kill -0 "$(cat "$PID")" 2>/dev/null; then echo "Already running: http://localhost:${PORT:-8776}"; exit 0; fi
export HF_HOME=/mnt/seagate/silo/voice-robust/hf HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VR_NEMO_CUDA_GRAPHS=0
setsid "$STATE/venv/bin/python" -u server.py > "$STATE/assist.log" 2>&1 < /dev/null &
echo $! > "$PID"; echo "Starting http://localhost:${PORT:-8776} (models load in ~40 s); log: $STATE/assist.log"
