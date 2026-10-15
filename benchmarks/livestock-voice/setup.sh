#!/usr/bin/env bash
set -euo pipefail
ROOT=/mnt/seagate/silo/livestock-voice
STATE="$HOME/.local/share/silo-livestock-voice"
mkdir -p "$ROOT/packages" "$STATE"
# exFAT cannot hold the venv symlinks; only its small launcher lives on NVMe.
python3 -m venv --system-site-packages "$STATE/venv"
"$STATE/venv/bin/pip" install --cache-dir "$ROOT/pip-cache" --target "$ROOT/packages" -r "$(dirname "$0")/requirements.lock"
PYTHONPATH="$ROOT/packages" "$STATE/venv/bin/python" - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download('Systran/faster-whisper-base.en',local_dir='/mnt/seagate/silo/livestock-voice/models/whisper-base.en',allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary*','preprocessor*'])
PY
