# 2026-11-25 22:40 IST — Laptop Stage 1 verified end-to-end, live CF Access embed/rerank, multi-arch WA image, and README index

## What happened

The owner pushed `signal_tui_cli`, pulled on their laptop, and tested the Stage 1 team CLI flow with `/home/beeps/idli-shares/silo/silo-team-config.tar.gz`:

- **Worked on first try:** `./setup.sh` installed repo-locally (`.env`, `bin/idli`, `.silo/`), Google OAuth + Drive sync read 144/145 docs (1 malformed PDF font entry skipped cleanly), and the 9B generated 140 cards over `https://silo.idli.cc` via Cloudflare Access.
- **Issues caught during the laptop test & fixed (`2b83a57`, `9b71452`, `116d8c3`):**
  1. **`embeddings skipped (HTTPError)` on laptop:** `muse-prefix-proxy.service` (`io` repo, `127.0.0.1:8185` behind `silo.idli.cc`) only intercepted `/v1/messages` and `/v1/chat/completions`, letting `/v1/embeddings` and `/v1/rerank` fall through to Muse (`:8181`). Added 6 lines to forward `/v1/embeddings → 127.0.0.1:8293` and `/v1/rerank → 127.0.0.1:8294`, restarted `muse-prefix-proxy.service`, and verified all 3 endpoints return `200 OK` live through `https://silo.idli.cc` with `silo.json`.
  2. **`No WhatsApp snapshot found` + extra start command:** Built and pushed multi-arch (`linux/amd64,linux/arm64`) distroless `docker.io/bprashanth/silo-wa-sync:latest` (`sha256:10f007d9fe366f81b52c7d8829c7a8429bb415dcff4c3765b5c23b0cca5d7ab4`), updated `bridges/whatsapp/start.sh` to pull it with `--user "$(id -u):$(id -g)"` and reuse an already-running container, and folded idempotent WhatsApp bridge startup directly into `./setup.sh` (auto-skips gracefully with a note if Docker is absent; `--no-whatsapp` / `--whatsapp` flags available).
  3. **`==SUPPRESS==` in `idli --help`:** Python 3.12 `argparse` printed literal `==SUPPRESS==` for legacy subcommand aliases (`count`, `explain`, `describe`, `read`). Omitting `help=` hides them cleanly while preserving CLI compatibility.
  4. **`README.md` streamlined:** Kept everything above `## Current State` untouched and turned the rest into a concise Quickstart (`./setup.sh` → `docs/cheatsheet.md` → `deployment/team/README.md` / `narrative/ALPHA_TESTING.md`) + index to active rollout plans, benchmarks/regression checks, and repo layout.
- Owner confirmed the updated laptop flow works and pushed to `origin/signal_tui_cli`.

## Open discussion

- Evaluating `Qwen3.5-9B-Q4_K_M` (`5.3 GB`, already on DGX) and smaller `4B` models against a unified WA + Drive + Gmail + Calendar benchmark for **NVIDIA Jetson Orin Nano Super 8GB** feasibility, plus selecting the next overnight run.
