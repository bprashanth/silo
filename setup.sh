#!/usr/bin/env bash
# One-command Silo CLI setup for team laptops.
# Example:
#   ./setup.sh --config ~/Downloads/silo-team-config.tar.gz \
#     --account you@example.org \
#     --sandbox_path ~/idli-sbx/pilot
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/deployment/team/install.py" "$@"
