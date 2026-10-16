#!/usr/bin/env bash
set -euo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
state="${LIVESTOCK_STATE:-$HOME/.local/share/idli-bridge/livestock}"
mkdir -p "$state"
chmod 700 "$state"
if [[ ${1:-} == stop ]]; then
  if [[ -f "$state/server.pid" ]]; then kill "$(cat "$state/server.pid")" 2>/dev/null || true; rm -f "$state/server.pid"; fi
  exit 0
fi
if [[ -f "$state/server.pid" ]] && kill -0 "$(cat "$state/server.pid")" 2>/dev/null; then echo 'Idli Ops already running'; exit 0; fi
python="${LIVESTOCK_PYTHON:-$state/venv/bin/python}"
export PYTHONPATH="/mnt/seagate/silo/livestock-v2/packages:${PYTHONPATH:-}"
setsid nohup "$python" -m uvicorn livestock.app:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8766}" > "$state/server.log" 2>&1 < /dev/null &
echo $! > "$state/server.pid"
for attempt in {1..30}; do
  if curl --max-time 2 -fs "http://127.0.0.1:${PORT:-8766}/api/health" >/dev/null; then
    echo "Idli Ops: http://100.82.28.38:${PORT:-8766}"
    exit 0
  fi
  if ! kill -0 "$(cat "$state/server.pid")" 2>/dev/null; then
    echo "Idli Ops did not start. See $state/server.log" >&2
    exit 1
  fi
  sleep 1
done
echo "Idli Ops startup timed out. See $state/server.log" >&2
exit 1
