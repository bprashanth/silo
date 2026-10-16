#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
state="${LIVESTOCK_STATE:-$HOME/.local/share/idli-bridge/livestock}"
unit=silo-buffalo
case "${1:-start}" in
 stop) systemctl --user stop "$unit.service"; exit ;;
 status) systemctl --user status "$unit.service" --no-pager; exit ;;
 start) ;;
 *) echo 'Usage: livestock/bot.sh [start|stop|status]' >&2; exit 2 ;;
esac
if systemctl --user is-active --quiet "$unit.service"; then echo 'Buffalo Soldiers already running'; exit 0; fi
systemctl --user reset-failed "$unit.service" 2>/dev/null || true
systemd-run --user --unit="$unit" --collect --property=Restart=on-failure --property=RestartSec=5 \
  --property="WorkingDirectory=$PWD" --setenv="PYTHONPATH=/mnt/seagate/silo/livestock-v2/packages" \
  --setenv="LIVESTOCK_STATE=$state" \
  "$state/venv/bin/python" -m livestock.bot
echo 'Buffalo Soldiers started. Logs: journalctl --user -u silo-buffalo'
