# Handoff

Last updated 2026-11-26. Keep this current: whoever ends a session rewrites the "State" and "Next" sections.

Current docs & evidence: [Model sizing & hardware cost narrative](../narrative/jetson-8gb-model-sizing.md) · [Alpha testing guide](../narrative/ALPHA_TESTING.md) · [WhatsApp search narrative](../narrative/whatsapp-search.md) · [Core WhatsApp v2 benchmark](../benchmarks/runs/2026-11-25-whatsapp-core-v2/README.md) · [CLI cheatsheet](../docs/cheatsheet.md) · [Team setup](../deployment/team/README.md).

## What this repo is

The Idli core: a command-line tool (`core/idli`) over a DuckDB store per sandbox, that answers questions about a
person's own email, calendar, Drive, and WhatsApp chats. It was built and measured in the io repo and copied here on 2026-11-21.
Ignore `archive/` and `examples/`: they are the old Telegram version of Silo.

## Read first

1. [goals.md](../docs/goals.md): the core as built and tested, and what isn't built.
2. [cheatsheet.md](../docs/cheatsheet.md), [cli.md](../docs/cli.md), and `core/idli help` for the commands.
3. [decisions.md](../docs/decisions.md) for design choices.
4. [The docs index](../docs/README.md) for the store, mapper, models and privacy.
5. [../todos/README.md](../todos/README.md): what's next; `../todos/core.md`: every bug, its evidence and its fix.
6. [from-io.md](../docs/from-io.md): where the evidence and the history are in io.

## How we work

- The owner tests by hand: `source .env && idli ask -v "..."` (or `cd core; IDLI_SANDBOX=~/idli-sbx/NAME ./idli ask "..."`). When something fails, find the
  cause in `<sandbox>/log.jsonl` (every command and every turn, with the prompt sent, the plan, the menu, the chips),
  check the right answer with read-only SQL (`./idli query "SELECT ..."`), and fix it so the whole class of
  questions works, never one question.
- Prefer code over prose (a sentence in the 9B's instructions). The prose has a size budget:
  `.venv/bin/python -m unittest tests.test_scaffold_prose` from `core/`.
- Add the owner's questions, with answers checked by SQL, to `benchmarks/bank/tasks_owner_dev.json`. Measure on the
  dev banks; claim only on a new held-out set run once on frozen code, graded blind (`benchmarks/README.md`).
- A change that can't be shown safe ships off by default.
- Plain words in anything a person reads. Say "idli-remote", never the provider's name. Never print tokens, OAuth
  files or keys.
- Long runs and grading go to Cursor `agent` or `codex exec`. Nothing under `~/.codex` is edited.
- Commit as you go; then `bash -ic 'declaude origin/main'` (it rewrites hashes; quote hashes only after it). Don't
  push: the owner reviews and pushes.

## State (2026-11-26)

- Branch `q4_quantization` (branched from `signal_tui_cli` / `main` at `116d8c3`, local-only — owner reviews and pushes; `52/52` unit & integration tests passing across `core/` (35), `bridges/signal/` (12), `bridges/onboard/` (2), and `deployment/team/` (3); prose budget under limit).
- **WhatsApp + Drive core search hardened (`e1bdee5` → `616d18c`):**
  - `@lid` contact & `@mention` backfill in `bridges/whatsapp/main.go` (numeric senders dropped `64% → 1%`, `0%` in tested work groups).
  - Repeatable `--in` scoping on `idli sync drive` and `idli sync whatsapp`.
  - Fixed systemic blind-bench gaps: multi-`OR` `body ~` folding, thread-context expansion across `--where` filters + direct replies, top-5 long `body` render (`1200` chars), 1-word ambiguous sender resolution (`--search "S"`), recency-only `summarise messages` (`"latest discussion"`), `get message --search/--in` normalization, post-latest date fallback (strictly preserving past out-of-window controls), strong unknown-chat guard, and hidden legacy aliases (`==SUPPRESS==` removed from `idli --help`).
  - **Benchmark v2 (`blind-heldout-2026-11-25`, 20 unseen cases, graded blind by `codex exec`):** `e1bdee5` first pass `11/4/5` (exposed 4 general bugs) → `616d18c` post-fix **`17 correct / 3 partial / 0 wrong`**, `15/16 (93.8%)` positive evidence, `4/4` controls. Prior blind v1 rose to `14/16` evidence + `4/4` controls. Google owner regression (`tasks_owner_dev.json`, 19 turns): **`0` errors, `0` WA leaks**.
- **Stage 1 Team Laptop CLI verified end-to-end by owner:**
  - Repo-local, idempotent `./setup.sh` (`deployment/team/install.py`) creates `.env`, `bin/idli`, and `.silo/{config,sandbox,wa}` (all gitignored; zero global installs; fails fast if `IDLI_GOOGLE_ACCOUNT` is unset).
  - Multi-arch (`linux/amd64,linux/arm64`) distroless read-only WhatsApp image published to **`docker.io/bprashanth/silo-wa-sync:latest`** and auto-started idempotently by `./setup.sh` (with clean Docker-missing guard and `--no-whatsapp`/`--whatsapp` flags).
  - DGX `muse-prefix-proxy.service` (`io` repo) now routes `/v1/embeddings` (`:8293`) and `/v1/rerank` (`:8294`) alongside `idli-9b` (`:8291`) over `https://silo.idli.cc` behind Cloudflare Access (`silo.json`).
  - Private bundles ready on DGX (outside Git): `/home/beeps/idli-shares/silo/silo-team-config.tar.gz` (`0600`) and `/home/beeps/idli-shares/silo/silo-cli-9b71452.tar.gz`.
- **Stage 2 Alpha Signal Onboarding built & Playwright-verified (`bridges/onboard/`, `bridges/signal/bridge.py`, `deployment/alpha/signal.agent.md`):**
  - 4-step mobile & desktop web flow (Connect Google PKCE OAuth / WhatsApp QR+code → `--in` folder/group checkboxes → Role & intended use saved to private `profile.json` → scoped sync + 6-digit Signal DM `confirm <code>`).
  - Verified mixed Google + `--in`-scoped WhatsApp queries over `bridges/signal/bridge.py` and two-tester canary isolation.
- **Jetson 8GB Quantization & Smaller-Model Shootout completed ([2026-11-26 run](../benchmarks/runs/2026-11-26-jetson-quant-shootout/README.md), 435 blind-graded turns across WA `blind-v3`, Mixed Google+WA, Google `owner_dev`, and Google `heldout`):**
  - `Qwen3.5-9B-Q4_K_M` (`5.23 GiB` GPU, `-c 8192 -np 1`, no `mmproj`: **`41/26/20`**, `0` mixed leaks, `14/16` WA ev) and `Qwen3.5-9B-IQ4_XS` (`4.75 GiB` GPU: **`44/23/20`**, `0` mixed leaks, `12/16` WA ev) matched the DGX `Q5_K_M` baseline (`8.39 GiB` GPU: `41/25/21`) with `0` context overflows at `8k` ctx (`peak_prompt_chars = 16,841`).
  - Both 4B models (`Qwen3.5-4B-Q5_K_M`: `24/22/41`, 28 errors; `Gemma-4-E4B-it-Q5_K_M`: `30/22/35`, 27 compose fallbacks) collapsed on CLI mapping and are ruled out.
  - **Settled edge choice & live DGX swap:** `Qwen3.5-9B-Q4_K_M` (default) or `IQ4_XS` (500 MiB headroom fallback) for headless 8 GB Jetson (`-c 8192 -np 1`, no `mmproj`, embed/rerank offloaded). Narrative + INR hardware frontier chart at [narrative/jetson-8gb-model-sizing.md](../narrative/jetson-8gb-model-sizing.md) and [chronology/2026-11-26T1950-q4-swap-embed-tightening-and-frontier-chart.md](../chronology/2026-11-26T1950-q4-swap-embed-tightening-and-frontier-chart.md).
  - **Live DGX stack behind `https://silo.idli.cc` (`8.73 GiB` total GPU RAM, down from `57.79 GiB` — `49.1 GiB` freed):**
    - `idli-9b` (`:8291`): `Qwen3.5-9B-Q4_K_M` (`5,561 MiB`, `-c 16384 -np 2`, no `mmproj`, `-fa on --cache-type-k q8_0 --cache-type-v q8_0`).
    - `idli-embed` (`:8293`): `Qwen3-Embedding-0.6B-Q8_0` (`2,449 MiB`, tightened to `-fa on -c 4096 -ub 2048 -b 2048 -np 2`; verified `200 OK` on single query, 32-item batch, and 6,000-char max item).
    - `idli-rerank` (`:8294`): `bge-reranker-v2-m3-Q8_0` (`929 MiB`).
    - Stopped (not removed): `idli-muse` (`25,162 MiB`) and `idli-9b-bf16` (`17,987 MiB`). Keyword/phrase/Porter stemming (BM25) runs purely in local DuckDB `fts`.
- **Docs updated:** `README.md` streamlined into Quickstart + index, linked to `docs/cheatsheet.md`, `deployment/team/README.md`, and `narrative/ALPHA_TESTING.md`.

## Next

1. **Multi-message synthesis + cross-app (`Drive ↔ WA`) quality pass:** Now that `Qwen3.5-9B` (`Q5` on DGX, `Q4_K_M`/`IQ4_XS` on 8 GB Jetson) is settled, improve `compose()`/`summarise_messages()` multi-turn attribution and fix the two shared `wa_blind_v3` errors (saved-history count wording & multi-turn synthesis).
2. **Stage 2 live owner test & public `silo.idli.cc` onboarding route:** Owner tests local `bridges/onboard` preview, then wire `/setup/*` and `/oauth/google/callback` on `silo.idli.cc` with a registered Google Web OAuth client and per-tester container isolation.
3. **Commit the 6-line `muse_prefix_proxy.py` routing change in the `io` repo** (`/v1/embeddings` + `/v1/rerank`).
4. **Team feedback triage:** Fold Stage 1 laptop feedback from the team into general fixes or bounded workflows under `proposals/workflows/`.
