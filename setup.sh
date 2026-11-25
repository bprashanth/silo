#!/usr/bin/env bash
# Idempotent, repo-local Silo CLI + optional local WhatsApp bridge setup for team laptops.
# Examples:
#   ./setup.sh --config ~/Downloads/silo-team-config.tar.gz --account you@example.org
#   ./setup.sh                    # re-run anytime to verify env & start WhatsApp bridge if stopped
#   ./setup.sh --no-whatsapp      # skip starting the local Docker WhatsApp bridge
#   ./setup.sh --whatsapp         # require Docker & fail if WhatsApp bridge cannot start
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WA_MODE="auto"   # auto | require | skip
PASS_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --no-whatsapp) WA_MODE="skip" ;;
    --whatsapp)    WA_MODE="require" ;;
    *)             PASS_ARGS+=("$arg") ;;
  esac
done

python3 "$ROOT/deployment/team/install.py" "${PASS_ARGS[@]}"

if [ "$WA_MODE" = "skip" ]; then
  exit 0
fi

# Skip starting the WhatsApp bridge if the caller only asked for --help
for arg in "${PASS_ARGS[@]+"${PASS_ARGS[@]}"}"; do
  case "$arg" in
    -h|--help) exit 0 ;;
  esac
done

if [ "$WA_MODE" = "require" ]; then
  "$ROOT/bridges/whatsapp/start.sh"
else
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    "$ROOT/bridges/whatsapp/start.sh"
  else
    echo ""
    echo "Note: Docker is not installed or running — skipped local WhatsApp bridge."
    echo "      Gmail, Calendar, and Drive work without Docker. Install/start Docker and re-run ./setup.sh to enable WhatsApp."
  fi
fi
