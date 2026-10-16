#!/usr/bin/env bash
set -euo pipefail
state="${LIVESTOCK_STATE:-$HOME/.local/share/idli-bridge/livestock}"
packages="/mnt/seagate/silo/livestock-v2/packages"
mkdir -p "$state" "$packages"
chmod 700 "$state"
uv venv --allow-existing --python python3 "$state/venv"
uv pip install --python "$state/venv/bin/python" --target "$packages" 'fastapi==0.135.1' 'uvicorn==0.41.0' 'numpy==2.5.3' 'faster-whisper==1.2.1' 'kokoro-onnx==0.6.1' 'soundfile==0.14.0' 'telethon==1.45.0'
