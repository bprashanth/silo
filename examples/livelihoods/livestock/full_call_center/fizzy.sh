#!/usr/bin/env bash
set -euo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
state="$HOME/.local/share/silo-livestock-fizzy"
mkdir -p "$state"
case "${1:-start}" in
  stop)
    systemctl --user disable --now silo-livestock-fizzy-sync.service 2>/dev/null || true
    docker compose -p livestock -f examples/livelihoods/livestock/full_call_center/fizzy-compose.yaml stop
    ;;
  start)
    test -f "$state/config.json" || { echo 'Run the bootstrap instructions in examples/livelihoods/livestock/full_call_center/fizzy.md first.'; exit 1; }
    docker compose -p livestock -f examples/livelihoods/livestock/full_call_center/fizzy-compose.yaml up -d
    python3 - <<'PYCONFIG'
import json
from pathlib import Path
config = json.loads((Path.home()/'.local/share/silo-livestock-fizzy/config.json').read_text())
public = Path.home()/'.local/share/idli-bridge/livestock/fizzy/public.json'
public.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
public.write_text(json.dumps({'public_url': config['board_url']}))
public.chmod(0o600)
PYCONFIG
    mkdir -p "$HOME/.config/systemd/user"
    cat > "$HOME/.config/systemd/user/silo-livestock-fizzy-sync.service" <<EOF
[Unit]
Description=Optional local livestock Fizzy mirror
After=network-online.target
[Service]
WorkingDirectory=$PWD
ExecStart=/usr/bin/python3 $PWD/examples/livelihoods/livestock/full_call_center/fizzy_sync.py
Restart=on-failure
RestartSec=5
UMask=0077
StandardOutput=append:$state/sync.log
StandardError=append:$state/sync.log
[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now silo-livestock-fizzy-sync.service
    ;;
  *) echo 'Usage: examples/livelihoods/livestock/full_call_center/fizzy.sh [start|stop]'; exit 2;;
esac
