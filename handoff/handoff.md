# Handoff

Last updated 2026-11-24. Keep this current: whoever ends a session rewrites the "State" and "Next" sections.

Current architecture & evidence: [WhatsApp search narrative](../narrative/whatsapp-search.md) · [Core WhatsApp benchmark](../benchmarks/runs/2026-11-24-whatsapp-core/README.md) · [Architecture proposal](../proposals/architecture/whatsapp-search.md).

## What this repo is

The Idli core: a command-line tool (`core/idli`) over a DuckDB store per sandbox, that answers questions about a
person's own email, calendar and Drive. It was built and measured in the io repo and copied here on 2026-11-21.
Ignore `archive/` and `examples/`: they are the old Telegram version of Silo.

## Read first

1. [goals.md](../docs/goals.md): the core as built and tested, and what isn't built.
2. [cli.md](../docs/cli.md) and `core/idli help` for the commands.
3. [decisions.md](../docs/decisions.md) for design choices.
4. [The docs index](../docs/README.md) for the store, mapper, models and privacy.
5. [../todos/README.md](../todos/README.md): what's next; `../todos/core.md`: every bug, its evidence and its fix.
6. [from-io.md](../docs/from-io.md): where the evidence and the history are in io.

## How we work

- The owner tests by hand: `cd core; IDLI_SANDBOX=~/idli-sbx/NAME ./idli ask "..."`. When something fails, find the
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

## State (2026-11-24)

- Branch `signal_tui_cli`. Core frozen and verified at `345e74d` (`26/26` core unit tests + `10/10` Signal bridge tests passing; prose budget `5243 / 6836 / 1329`, under original baseline).
- **First-class WhatsApp/chat search shipped in `core/`:** `chats`, `messages`, `chat_members`, `message_episodes` tables + `core/lib/searchkit.py` (DuckDB FTS BM25 + fuzzy fallback + `Qwen3-Embedding-0.6B` episode vectors + optional local `bge-reranker-v2-m3` cross-encoder on `127.0.0.1:8294`, `idli-rerank` container) + deterministic `--in CHAT` / sender / date-coverage resolvers + Signal `--output humanize` message receipts.
- **Verified results (`345e74d`):**
  - Dev WhatsApp bank (`ask-LMunvw`): **5/8 prior, 12/12 new, 12/12 repeat, 3/4 controls** (vs stock `0/8, 0/12`; median `5.0s`).
  - Blind held-out WhatsApp bank (`blind-heldout-2026-11-24`, 20 unseen cases, graded blind by `codex exec`): **13/16 (81%) positive evidence**, **12/20 strict correct + 3/20 partial (0 wrong on multi-message)**, **3/4 controls**.
  - Google regression (`tasks_owner_dev.json`, 19 turns on `silo-smoke`): **0 errors, 0 WhatsApp routing leaks**. Mixed Google + live `whatsmeow` store routed cleanly under `--output humanize`.
- **Read-only `whatsmeow` sidecar (`bridges/whatsapp/`):** Built (`silo-wa-sync`), paired live against owner’s WhatsApp at **9.8 MiB RAM** (zero write/send methods), synced 21 groups + 42 DMs (1,874 messages, 14-day window) in ~5s (`silo-wa-smoke` container).

## Next

1. **Signal + WhatsApp CLI live test:** Pair a mixed sandbox with `bridges/signal/bridge.py` and test natural WhatsApp + Google queries end-to-end over Signal DM (including italic coverage footers & message receipts).
2. **Multi-user Signal onboarding flow ([deployment/alpha/signal.md](../deployment/alpha/signal.md)):** Build the invite-link web service on `silo.idli.cc` combining Google Web OAuth (PKCE) + per-user containerized `whatsmeow` pairing (QR + 8-digit phone code), bound to the Signal sender ACI with isolated per-user sandboxes.
3. **Two targeted core follow-ups:** (a) make ambiguous single-letter sender queries (`V`, `S`) reliably trigger `resolve_sender` instead of `--search`; (b) tighten reader/wording grounding so `compose()` preserves caveats from retrieved messages.
4. See [../todos/README.md](../todos/README.md) for Mini v0, subtables, and local Clef.
