#!/usr/bin/env bash
# (Re)start the Telegram bridge in the background. See docs/deployment.md.
# usage: [TG_ALLOWED=user1,user2] [IDLI_BASE_URL=...] ./start.sh
# Logs to tg_bridge.log; the pid is in tg_bridge.pid. ./start.sh stop just stops it.
set -euo pipefail
cd "$(dirname "$0")"
if [[ -f tg_bridge.pid ]] && kill -0 "$(cat tg_bridge.pid)" 2>/dev/null; then
  kill "$(cat tg_bridge.pid)"; echo "stopped $(cat tg_bridge.pid)"
fi
rm -f tg_bridge.pid
[[ ${1:-} == stop ]] && exit 0

[[ -x .venv/bin/python ]] || { uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements.txt; }
docker image inspect idli-sandbox:1 >/dev/null 2>&1 || docker build -t idli-sandbox:1 sandbox
base=${IDLI_BASE_URL:-http://127.0.0.1:8181/v1}
curl -sf "$base/models" >/dev/null || echo "warning: no model server answering at $base" >&2
[[ -n ${TG_ALLOWED:-} ]] || echo "warning: TG_ALLOWED is empty, so anyone who finds the bot can use it" >&2

setsid nohup .venv/bin/python tg_bridge.py >> tg_bridge.log 2>&1 &
echo $! > tg_bridge.pid
sleep 3
kill -0 "$(cat tg_bridge.pid)" 2>/dev/null || { tail -20 tg_bridge.log; exit 1; }
tail -1 tg_bridge.log
