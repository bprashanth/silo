#!/usr/bin/env bash
# Livestock hub: a landing page with one card per example, and the servers behind them.
#
#   run.sh [start] [--dry-run]   hub :8770, call center assist :8776, case desk :8766 (if not up),
#                                and the Buffalo Telegram bot, always restarted from this checkout
#   run.sh --no-bot              the hub and the assist only; leave the case desk and the bot alone
#   run.sh stop                  stop the hub, the assist and the bot (the case desk and Fizzy stay up)
#   run.sh status
#
# Shared services are checked, never started: local Muse on :8181. Secrets are checked to exist, never read.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(git -C "$HERE" rev-parse --show-toplevel)"
ASSIST="$HERE/call_center_assist/assist"
FULL="$HERE/full_call_center"
VSTATE="$HOME/.local/share/silo-voice"
LSTATE="${LIVESTOCK_STATE:-$HOME/.local/share/idli-bridge/livestock}"
HUB_PORT=8770 ASSIST_PORT=8776 DESK_PORT=8766
BOT_MODULE=examples.livelihoods.livestock.full_call_center.bot

cmd=start dry=0 nobot=0
for a in "$@"; do
  case "$a" in
    start|stop|status) cmd=$a ;;
    --dry-run) dry=1 ;;
    --no-bot) nobot=1 ;;
    *) echo "Usage: $0 [start|stop|status] [--dry-run] [--no-bot]" >&2; exit 2 ;;
  esac
done

say() { echo "[livestock] $*"; }
run() { if (( dry )); then say "would run: $*"; else "$@"; fi; }
up() { curl -s -m 2 -o /dev/null "$1"; }
pid_alive() { [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null; }
port_pid() { ss -ltnpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2; }
# PIDs whose command line runs the Buffalo bot module. Matches on argv, so this shell is never one of them.
bot_pids() { ps -eo pid=,args= | awk -v m="-m $BOT_MODULE" -v self=$$ '$1 != self && index($0, m) && $2 ~ /python/ {print $1}'; }
tailnet() { tailscale ip -4 2>/dev/null | head -1 || true; }

status() {
  local t; t="$(tailnet)"
  printf '  %-22s %s\n' "hub :$HUB_PORT" "$(up "http://127.0.0.1:$HUB_PORT/" && echo up || echo down)"
  printf '  %-22s %s\n' "assist :$ASSIST_PORT" "$(up "http://127.0.0.1:$ASSIST_PORT/api/config" && echo up || echo 'down (or still loading models)')"
  printf '  %-22s %s\n' "case desk :$DESK_PORT" "$(up "http://127.0.0.1:$DESK_PORT/api/health" && echo up || echo down)"
  printf '  %-22s %s\n' "Buffalo bot" "$(systemctl --user is-active silo-buffalo.service 2>/dev/null || true) (pids: $(bot_pids | tr '\n' ' '))"
  printf '  %-22s %s\n' "Muse :8181 (shared)" "$(up http://127.0.0.1:8181/health && echo up || echo 'DOWN: the assist needs it')"
  say "hub: http://127.0.0.1:$HUB_PORT${t:+  tailnet: http://$t:$HUB_PORT}"
}

stop_bot() {
  run "$FULL/bot.sh" stop || true
  local p main; main="$(systemctl --user show -p MainPID --value silo-buffalo.service 2>/dev/null || true)"
  for p in $(bot_pids); do
    (( dry )) && [[ $p == "$main" ]] && continue   # bot.sh stop takes care of the service's own process
    say "stopping a Buffalo bot outside the service (pid $p)"; run kill "$p"
  done
}

if [[ $cmd == status ]]; then status; exit 0; fi

if [[ $cmd == stop ]]; then
  if pid_alive "$VSTATE/hub.pid"; then run kill "$(cat "$VSTATE/hub.pid")"; (( dry )) || rm -f "$VSTATE/hub.pid"; fi
  run "$ASSIST/start.sh" stop || true
  stop_bot
  say "stopped the hub, the assist and the bot; the case desk and Fizzy are left running"
  exit 0
fi

# ---------- validate ----------
missing=()
for f in "$HERE/web/index.html" "$ASSIST/server.py" "$ASSIST/start.sh" "$FULL/bot.sh" "$FULL/start.sh" \
         "$VSTATE/venv/bin/python" "$LSTATE/venv/bin/python" \
         "$HOME/.config/idlisseus/telegram.json" "$HOME/.config/livestock/allowed.txt" \
         "$HOME/.config/idlisseus/openrouter.json"; do
  [[ -e $f ]] || missing+=("$f")
done
for d in /mnt/seagate/silo/voice-robust/hf /mnt/seagate/silo/livestock-v2/packages; do [[ -d $d ]] || missing+=("$d"); done
if (( ${#missing[@]} )); then say "missing, nothing started:"; printf '  %s\n' "${missing[@]}"; exit 1; fi
up http://127.0.0.1:8181/health || say "warning: Muse on :8181 is down; the assist will fall back to rules only"
mkdir -p "$VSTATE"

# ---------- call center assist (:8776) ----------
# Keep it if it is already this checkout's assist; restart one started from another checkout; never kill a stranger.
holder="$(port_pid $ASSIST_PORT || true)"
if [[ -n $holder ]]; then
  own="$(cat "$VSTATE/assist.pid" 2>/dev/null || true)"
  if [[ $holder != "$own" ]]; then say ":$ASSIST_PORT is held by pid $holder ($(ps -o args= -p "$holder" | cut -c1-80)), not our assist; stopping"; exit 1; fi
  # The directory it was started in (PWD at exec): a rename moves /proc/<pid>/cwd along, but not the paths it loaded.
  started="$(tr '\0' '\n' < "/proc/$holder/environ" 2>/dev/null | sed -n 's/^PWD=//p')"
  if [[ $started == "$ASSIST" ]]; then say "assist already running from this checkout"
  else say "assist is running from ${started:-somewhere else}; restarting it from this checkout"; run "$ASSIST/start.sh" stop; (( dry )) || sleep 2; run "$ASSIST/start.sh"; fi
else
  run "$ASSIST/start.sh"
fi

# ---------- full call center: case desk (:8766), then the bot ----------
if (( nobot )); then say "--no-bot: leaving the case desk and the Buffalo bot as they are"
else
  if up "http://127.0.0.1:$DESK_PORT/api/health"; then say "case desk already up on :$DESK_PORT"; else run "$FULL/start.sh"; fi
  say "restarting the Buffalo bot from $ROOT"
  stop_bot
  (( dry )) || sleep 1
  run "$FULL/bot.sh" start
fi

# ---------- hub (:8770) ----------
holder="$(port_pid $HUB_PORT || true)"
if [[ -n $holder ]]; then
  if [[ $holder == "$(cat "$VSTATE/hub.pid" 2>/dev/null || true)" ]]; then run kill "$holder"; (( dry )) || sleep 0.5
  else say ":$HUB_PORT is held by pid $holder, not our hub; stopping"; exit 1; fi
fi
if (( dry )); then say "would serve $HERE/web on 0.0.0.0:$HUB_PORT"
else
  setsid python3 -m http.server "$HUB_PORT" --bind 0.0.0.0 --directory "$HERE/web" > "$VSTATE/hub.log" 2>&1 < /dev/null &
  echo $! > "$VSTATE/hub.pid"
  for _ in {1..20}; do up "http://127.0.0.1:$HUB_PORT/" && break; sleep 0.25; done
fi

(( dry )) || { say "the assist loads its models in ~40 s; check with: $0 status"; status; }
