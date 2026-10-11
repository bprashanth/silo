# Proposal: an audit record and checker for every answer

**Status:** proposed, 2026-10-11. **Evidence:** the `audit` field in
`benchmarks/harness-compare` (`receipt.py:audit`), 268 jobs.

## Problem

Silo's privacy promise is that data never leaves the box without the user's consent.
The sandbox **enforces** this:
- the bridge's `python` tool runs in `docker --network none` with files read-only;
- io's Codex profile runs behind a bubblewrap wall with the network off.

Enforcement alone isn't **verifiable**. A user, or someone vouching to them, should be
able to see what the agent did for an answer, and an operator should hear about any
attempt to get past the wall, even a failed one. An agent that keeps trying to reach the
network is a signal worth acting on, whether the wall held or not.

The goal in the README ("users can verify the steps taken to produce the result") also
needs a record that a person can read.

## Proposal

### 1. An audit record per answer

For each message the bot answers, append one JSON line to
`$AUDIT_ROOT/<chat>/<date>.jsonl`:
- **when and who:** time, chat id, Telegram user id;
- **which model:** the model key, the model file's sha256, and the server URL, which must
  be local unless the user picked an external model, in which case that choice is recorded;
- **what code:** the harness name and git commit;
- **which files:** the name and sha256 of every input file;
- **what ran:** every action, as the code or command, its output (truncated, with the
  hash of the full output), its exit status and its duration;
- **the result:** the final reply, the `ANSWER` value, and the correctness badge from
  [correctness-receipt.md](correctness-receipt.md);
- **audit flags:** see below.

Each line carries the sha256 of the line before it. Editing or deleting a line then
breaks the chain, which a nightly job can check. That's tamper-evident, not
tamper-proof, which is enough for a single trusted box.

For Codex, the record is built from its `--json` event stream (`command_execution`,
`agent_message`, `error`), as `benchmarks/harness-compare/run.py` already does.

### 2. Letting the user see the steps

`/how` replies with the steps behind the last answer:
- the files used (names and hashes);
- each piece of code that ran, shortened, with its key output line;
- the model and harness versions;
- the correctness badge.

`/how full` sends the full record as a `.txt` file. That's how "verifiable" becomes
something a non-coder can forward to someone who can read code.

