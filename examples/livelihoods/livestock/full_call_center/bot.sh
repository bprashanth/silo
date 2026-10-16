#!/usr/bin/env bash
set -euo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
state="${LIVESTOCK_STATE:-$HOME/.local/share/idli-bridge/livestock}"
unit=silo-buffalo
case "${1:-start}" in
 stop) systemctl --user stop "$unit.service"; exit ;;
 status) systemctl --user status "$unit.service" --no-pager; exit ;;
 start) ;;
 *) echo 'Usage: examples/livelihoods/livestock/full_call_center/bot.sh [start|stop|status]' >&2; exit 2 ;;
esac
if systemctl --user is-active --quiet "$unit.service"; then echo 'Buffalo Soldiers already running'; exit 0; fi
systemctl --user reset-failed "$unit.service" 2>/dev/null || true
systemd-run --user --unit="$unit" --collect --property=Restart=on-failure --property=RestartSec=5 \
  --property="WorkingDirectory=$PWD" --setenv="PYTHONPATH=/mnt/seagate/silo/livestock-v2/packages" \
  --setenv="LIVESTOCK_STATE=$state" \
  --setenv="LIVESTOCK_DASHBOARD_URL=${LIVESTOCK_DASHBOARD_URL:-http://100.82.28.38:8766}" \
  "$state/venv/bin/python" -m examples.livelihoods.livestock.full_call_center.bot
echo 'Buffalo Soldiers started. Logs: journalctl --user -u silo-buffalo'
