# Alpha Testing Guide — Silo (Stage 1 CLI & Stage 2 Signal)

This guide covers the two alpha testing tracks for the team: **Stage 1** for engineers/builders running the inner `idli` CLI on their laptop, and **Stage 2** for non-engineers testing Silo over Signal.

For retrieval architecture and benchmark evidence behind this release, see [whatsapp-search.md](whatsapp-search.md) and the [2026-11-25 v2 blind benchmark](../benchmarks/runs/2026-11-25-whatsapp-core-v2/README.md) (`17/20` strict correct, `3/20` partial, `0` wrong on 20 unseen WhatsApp cases; `0` errors on the 19-turn Google regression).

---

## Stage 1: Team Inner CLI Loop (Engineers / Technical Team)

Everything installs **inside your cloned `silo/` folder** (`.env`, `bin/idli`, `.silo/` — all gitignored). Nothing is installed globally, and `./setup.sh` is idempotent.

### 1. Setup on your laptop

Ask the maintainer for your private config archive (`silo-team-config.tar.gz`, containing `io_oauth_client_gcp.json` and `silo.json`).

```bash
git clone <repo-url> && cd silo
./setup.sh --config ~/Downloads/silo-team-config.tar.gz --account you@example.org
# Optional custom sandbox: add --sandbox_path /path/to/sandbox
```

*(If you omit `--account`, `./setup.sh` writes `.env` with `IDLI_GOOGLE_ACCOUNT=""` and `./bin/idli` will prompt you to set it before running.)*

In any new terminal:

```bash
source .env
idli help
```

### 2. Sync only what you are comfortable sharing (`--in`)

```bash
idli sync gmail -v                                         # opens browser OAuth once, saves token in .silo/config/
idli sync gcalendar -v
idli sync drive --in "Strategy Classics" --in "Leads" -v   # omit or add --no-embed if embed route isn't live yet
```

**Optional — WhatsApp (read-only, last 14 days, requires Docker):**

If Docker is running, `./setup.sh` automatically pulls and starts `bprashanth/silo-wa-sync:latest` in `.silo/wa/` and prints the browser QR / 8-digit code URL (re-run `./setup.sh` anytime to restart it if stopped; pass `--no-whatsapp` to skip). After pairing:

```bash
idli sync whatsapp --in "Jam Buns" --in "Acumen" -v
```

### 3. Walk through the basics (deterministic first, then `ask`)

1. **Inspect the store directly (zero LLM):**
   - `idli size` — exact row counts per resource (`mail`, `events`, `files`, `chats`, `messages`).
   - `idli list folders` / `idli list chats` — confirm **only** your `--in` folders/groups were ingested.
   - `idli list files --group-by kind` — exact breakdown.
   - `idli list messages --in "Jam Buns" --where "links <> ''" --count` — exact count on full table.
2. **Direct search & thread reading:**
   - `idli list files --search "border effects"` and `idli summarise --search "border effects"`.
   - `idli list messages --in "Jam Buns" --search "dice"` and `idli get message <ref>` (shows quoted parent, replies, ±3 neighbors, full URLs).
   - `idli summarise messages --in "Acumen" --search "latest discussion"`.
3. **Natural-language `ask` (watch every command with `-v`):**
   - `idli ask -v "how many PDFs are in Strategy Classics?"`
   - `idli ask -v "there was a doc abhi sent as a followup to a dice call, can you find it in jam buns"`
   - `idli ask -v "summarize the latest discussion in acumen"`
   - Follow-up turn (no `--new`): `idli ask -v "who sent that doc?"`
   - Preview-only draft: `idli ask -v "draft a reply to <sender> saying I'll review it Friday"` (never sent).

### What engineers should check & report
- Run with `-v` and check whether the generated CLI command matched your intent.
- Test **trust controls**: ask about an unshared group/folder (should report not found, never leak), ask about an out-of-window month like July 2026 (should cite cached coverage dates), and ask about an ambiguous initial/name (should ask which person you mean).
- If a query surprises you, note the exact question and the corresponding entry in `<sandbox>/log.jsonl` (never paste private message content into Git).

---

## Stage 2: Alpha Tester Setup on Signal (Non-Engineers)

Non-engineers install **nothing** — no CLI, no Docker, no config files. Every tester gets an isolated private sandbox and (when WhatsApp is enabled) a dedicated ~10 MiB read-only container on the DGX. See [deployment/alpha/signal.md](../deployment/alpha/signal.md) and [signal.agent.md](../deployment/alpha/signal.agent.md).

### Onboarding flow (4 steps on phone or desktop)

1. **DM Idli on Signal:** Send `"hi"` (or `"invite <code>"` when invite-only is enabled). Idli replies with an expiring, single-use setup link bound to your Signal account.
2. **Connect accounts (strictly read-only):**
   - **Google:** OAuth sign-in (`drive.readonly`, `gmail.readonly`, `calendar.readonly`), with toggles to include or exclude Gmail and Calendar.
   - **WhatsApp:** Link read-only device (last 14 days only; never sends messages or read receipts) via 8-digit phone code (single-phone friendly) or QR code.
3. **Pick only the folders & groups you are comfortable sharing (`--in`):**
   - Simple checkboxes for Drive folders and WhatsApp groups (personal/family chats stay unchecked by default).
   - Live privacy summary confirms exact counts before syncing.
4. **Describe how you plan to use AI in your role (optional):**
   - Role selector (`Insights`, `Partnerships`, `Marketing`, `Operations`, `Other`) plus clickable examples and a freeform textarea.
   - Matching Drive folders/groups and pasted Drive links are highlighted automatically.
   - Saved privately in `<sandbox>/profile.json` (`0600`) to guide future workflow tools — **never injected into the 9B mapper prompt**, so it cannot degrade search reliability.
5. **Confirm in Signal:**
   - Send the 6-digit `confirm <code>` message back in your original Signal DM with Idli (a forwarded link alone can never activate a workspace).
   - Once active, send `status` anytime to check coverage, `setup` to adjust shared folders/groups, or `disconnect` to unlink and delete sandbox data.

### Starter test queries for Signal alpha testers

- **Find a link/doc from a group thread:** *"Can you find the doc `<name>` shared after the `<topic>` call in `<group>`?"* — look for real sender names (no raw numbers), clickable link, and right date.
- **Catch-up summary:** *"Summarize the latest discussion in `<group>`"* — look for the most recent days (not stale earlier threads) and clear distinction between proposals and decisions.
- **Cross-app lookups:** *"How many files are in `<folder>`?"*, *"What did I last send to `<colleague>`?"*, *"When is my next meeting with `<person>`?"*
- **Trust & boundary checks:** Ask about a chat you did **not** check during setup, ask about a month before the 14-day window, or send an attachment / ask to send an email (Idli should cleanly refuse write/upload actions).

### Running the Stage 2 local preview on DGX

```bash
python3 -m bridges.onboard.server \
  --state ~/.local/share/silo-onboard-preview \
  --port 18770 --demo \
  --demo-google-sandbox ~/idli-sbx/silo-smoke \
  --wa-snapshot ~/.local/share/silo-owner-pilot/whatsmeow-smoke/snapshot.json \
  --wa-pair-url "$(cat ~/.local/share/silo-owner-pilot/whatsmeow-smoke/url)" \
  --no-embed --print-demo-url
```
