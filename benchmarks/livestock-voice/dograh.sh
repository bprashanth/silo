#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
state="$HOME/.local/share/silo-livestock/dograh"
artifacts="${LIVESTOCK_ARTIFACTS:-/mnt/seagate/silo/livestock-voice}"
venv="$HOME/.local/share/silo-livestock-voice/venv"
compose=(docker compose -p silo-livestock-dograh --env-file "$state/private.env" -f dograh-compose.yaml)
case "${1:-start}" in
 start)
  mkdir -p "$state" "$artifacts/evidence"
  if [[ ! -f "$state/private.env" ]]; then
   (umask 077; python3 -c 'import secrets; print("OSS_JWT_SECRET="+secrets.token_urlsafe(48))' > "$state/private.env")
  fi
  "${compose[@]}" up -d postgres redis minio api ui
  python3 dograh_local_network.py
  "${compose[@]}" restart api
  if [[ -f "$state/speech.pid" ]] && kill -0 "$(cat "$state/speech.pid")" 2>/dev/null; then exit 0; fi
  python3 - "$venv/bin/python" "$artifacts" "$state" <<'PYLAUNCH'
import os, pathlib, subprocess, sys
python, artifacts, state = sys.argv[1:]
env = {**os.environ, 'PYTHONPATH': artifacts + '/packages'}
with open(artifacts+'/evidence/dograh-speech.log','ab') as log:
    process = subprocess.Popen([python, 'dograh_speech.py'], stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env, start_new_session=True)
pathlib.Path(state+'/speech.pid').write_text(str(process.pid))
PYLAUNCH
  ;;
 stop)
  "${compose[@]}" stop
  if [[ -f "$state/speech.pid" ]]; then kill "$(cat "$state/speech.pid")" 2>/dev/null || true; rm -f "$state/speech.pid"; fi
  ;;
 status) "${compose[@]}" ps ;;
 *) echo 'Usage: dograh.sh [start|stop|status]' >&2; exit 2 ;;
esac
