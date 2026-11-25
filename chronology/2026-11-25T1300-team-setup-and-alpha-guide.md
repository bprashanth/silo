# 2026-11-25 13:00 IST — Repo-local idempotent team setup, CF Access embed/rerank, and Alpha Testing guide

## What the owner asked for

Prepare Silo for two stages of team testing (Stage 1 laptop CLI for engineers, Stage 2 Signal alpha for non-engineers) so the owner can push to `main`, pull on a laptop, and test end-to-end:

1. Keep Stage 1 setup completely repo-local (`.env`, `bin/idli`, `.silo/` — no global installs), idempotent, with sensible defaults and fail-fast when `IDLI_GOOGLE_ACCOUNT` is unset in `.env`.
2. Support `~/.config/idlisseus/silo.json` directly (Cloudflare Access `client_id` + `client_secret`, defaulting `"url"` to `https://silo.idli.cc` if omitted) and route `/v1/embeddings` + `/v1/rerank` through Cloudflare Access alongside the 9B.
3. Add a clean fail-fast Docker check for optional laptop WhatsApp sidecar startup (`bridges/whatsapp/start.sh`).
4. Pack a private config tarball outside Git for laptop testing, update `narrative/ALPHA_TESTING.md` and `chronology/`, and commit locally ready for push.

## Changes

- **`core/lib/muse.py`:** Searches `$IDLI_HOME/config/{silo.json,silo-access.json,muse-access.json}` (and `$IDLI_GOOGLE_CONFIG/`), defaults `"url"` to `https://silo.idli.cc`, and provides `embed_upstream()` / `rerank_upstream()` with automatic `CF-Access-Client-Id` / `CF-Access-Client-Secret` headers.
- **`deployment/team/install.py` + `setup.sh`:** Rewritten to be 100% repo-local and idempotent (`.env`, `bin/idli`, `.silo/{config,sandbox,wa}`). Accepts `--config <tar.gz|zip>` containing `io_oauth_client_gcp.json` + `silo.json` (or `muse-access.json`), optional `--account` and `--sandbox_path`, preserves existing `.env` values on re-run, and makes `./bin/idli` source `.env` and fail fast (exit 2) if `IDLI_GOOGLE_ACCOUNT` is unset.
- **`bridges/whatsapp/start.sh`:** Fails cleanly with an actionable message if `docker` is missing or the daemon is stopped; runs `silo-wa-sync` with state in `.silo/wa/` and prints the browser QR/8-digit code URL.
- **`.gitignore`:** Explicitly ignores `/.env`, `/.silo/`, `/bin/`, and private config/release archives (`silo.json`, `io_oauth_client_gcp.json`, `silo-team-config*.tar.gz`).
- **Docs & tests:** Added [narrative/ALPHA_TESTING.md](../narrative/ALPHA_TESTING.md), updated [deployment/team/README.md](../deployment/team/README.md), and expanded [deployment/team/test_install.py](../deployment/team/test_install.py) (`52/52` total tests passing across `deployment/team`, `core`, `bridges/signal`, and `bridges/onboard`).

## Private laptop bundles created on DGX (outside Git, `0600`)

- Config bundle: `/home/beeps/idli-shares/silo/silo-team-config.tar.gz` (packed from `~/.config/idlisseus/io_oauth_client_gcp.json` + `~/.config/idlisseus/silo.json`).
- Fresh source release tarball: `/home/beeps/idli-shares/silo/silo-cli-<rev>.tar.gz`.

## Next

- Owner pushes to `main`, pulls on laptop, tests Stage 1 with `silo-team-config.tar.gz` and Stage 2 onboarding preview, and confirms `silo.idli.cc` routes `/v1/embeddings` and `/v1/rerank` (or we keep `--no-embed` note until those routes are added).
