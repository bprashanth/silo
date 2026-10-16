# Livestock hub: call center assist moves next to the full call center

**What moved.**
- `benchmarks/voice-robust/` moved whole, with `git mv` so history is kept, to
  `examples/livelihoods/livestock/call_center_assist/`. Codex's `full_call_center/` is its sibling.
- The old top README (the agent-call measurement record) is now `agent_call.md`.
- The operator assist's README is now the example's `README.md`, with run instructions, requirements, layout and
  how it was measured.
- `benchmarks/README.md` points to the new place. Chronology entries before this one keep the old path.

**Branch.**
- New branch `call-center-assist`, cut from `merging` (71a7dc6, Codex's latest, one commit ahead of
  `origin/main`), with `poc/voice-robust` merged in.
- The conflicts were `.gitignore` and `narrative/README.md`; both sides were kept.
- Call audio under the example is ignored, along with Codex's existing rules.

**Hub.**
- `examples/livelihoods/livestock/run.sh` serves `web/index.html` on :8770 with two cards:
  - **Call center assist** opens :8776.
  - **Full call center** opens `t.me/Buffalosoldiers_bot`, with a case desk link to :8766.
- Each card shows a live up/down dot. The links use the page's own host, so they work over the tailnet.
- `run.sh` does the following:
  - Validates files and secrets (exists only), and checks Muse.
  - Starts the assist, or restarts it if it was started from another checkout (read from the process's PWD,
    because `/proc/<pid>/cwd` follows a rename).
  - Starts the case desk only if it is down.
  - Always restarts the Buffalo bot from this checkout via `full_call_center/bot.sh`, stopping any stray bot
    process by PID first.
  - Flags: `--dry-run`, `--no-bot`, `status`, `stop`.

**Verified.**
- The 54 unit tests pass from the new path.
- The assist and the agent call (:8775) were restarted from the new path.
- The live young-jowar role-play scored the same as before the move: 10/11 fields, protocol QA 13/15.
- The hub screenshot is fine at 1100 px and has no horizontal scroll at 390 px.
- `run.sh --dry-run` shows the right actions. `run.sh --no-bot` started the hub and restarted the assist.
- **Not run:** the bot restart itself, because it would cut the live bot over to this worktree. It is the
  user's first `run.sh` after pushing.
