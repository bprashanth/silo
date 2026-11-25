#!/usr/bin/env bash
# Start (or reuse if already running) the local read-only WhatsApp sidecar inside <repo>/.silo/wa.
# Fails cleanly if Docker is not installed or the Docker daemon is not running.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STATE_DIR="$ROOT/.silo/wa"
PORT="${IDLI_WA_PORT:-18766}"
DAYS="${IDLI_WA_DAYS:-14}"
NAME="${IDLI_WA_CONTAINER:-silo-wa-local}"
IMAGE="${IDLI_WA_IMAGE:-bprashanth/silo-wa-sync:latest}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: Docker is required for local WhatsApp syncing, but 'docker' was not found on PATH." >&2
  echo "Install Docker Desktop / Docker Engine first (Gmail, Calendar, and Drive sync do NOT need Docker)." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Error: Docker is installed, but the Docker daemon is not running (or not accessible by this user)." >&2
  echo "Start Docker Desktop / dockerd and re-run ./setup.sh." >&2
  exit 1
fi

umask 077
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

if docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
  PAIR_URL="$(cat "$STATE_DIR/url" 2>/dev/null || echo "http://127.0.0.1:${PORT}")"
  echo "Read-only WhatsApp bridge already running ($NAME): $PAIR_URL"
  exit 0
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "Pulling read-only WhatsApp image ($IMAGE)..."
  if ! docker pull "$IMAGE"; then
    echo "Pull failed; building local image ($IMAGE)..."
    docker build -t "$IMAGE" "$ROOT/bridges/whatsapp"
  fi
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$NAME"; then
  docker rm -f "$NAME" >/dev/null
fi

docker run -d --name "$NAME" \
  --user "$(id -u):$(id -g)" \
  -p "127.0.0.1:${PORT}:18766" \
  -v "$STATE_DIR:/state" \
  "$IMAGE" --state /state --days "$DAYS" --public-base "http://127.0.0.1:${PORT}" --listen 0.0.0.0:18766 >/dev/null

for _ in $(seq 1 20); do
  if [ -f "$STATE_DIR/url" ]; then
    break
  fi
  sleep 0.5
done

PAIR_URL="$(cat "$STATE_DIR/url" 2>/dev/null || echo "http://127.0.0.1:${PORT}")"
echo ""
echo "Read-only WhatsApp sidecar running ($NAME, last ${DAYS} days)."
echo "  Open in your browser to scan QR or enter an 8-digit phone code:"
echo "    $PAIR_URL"
echo ""
echo "Once paired and synced, import only the groups you want with:"
echo "  source .env"
echo "  idli sync whatsapp --in \"<Group Name>\" -v"
