#!/usr/bin/env bash
# (Re)start the local Muse Glimmer server on 127.0.0.1:8181.
# usage: [NP=4] [CTX=262144] serve_muse.sh <model.gguf> [drafter.gguf] [extra llama-server args...]
# CTX is shared across the NP parallel slots (4 x 64k by default).
set -euo pipefail
M=/mnt/seagate/models/Muse-Glimmer-30B-GGUF
model=$1; shift
draft=()
if [[ $# -gt 0 && $1 == *.gguf ]]; then draft=(-md "/m/$1" -ngld 999); shift; fi
docker rm -f idli-muse >/dev/null 2>&1 || true
docker run -d --name idli-muse --restart unless-stopped --gpus all -p 127.0.0.1:8181:8080 -v "$M":/m:ro \
  ghcr.io/ggml-org/llama.cpp:server-cuda13 -m "/m/$model" --mmproj /m/mmproj-Muse-Glimmer-30B-BF16.gguf \
  --alias muse-glimmer-30b -ngl 999 -c "${CTX:-262144}" -np "${NP:-4}" --jinja --reasoning-format deepseek -fa on \
  --host 0.0.0.0 --port 8080 "${draft[@]}" "$@" >/dev/null
for i in $(seq 200); do curl -sf 127.0.0.1:8181/health >/dev/null && { echo "up: $model ${draft[*]:-} $*"; exit 0; }
  docker ps -q -f name=idli-muse | grep -q . || { docker logs idli-muse 2>&1 | tail -20; exit 1; }; sleep 3; done
echo "timeout"; docker logs idli-muse 2>&1 | tail -20; exit 1
