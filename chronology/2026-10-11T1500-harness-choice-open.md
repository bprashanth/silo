# Open question: our harness or io's Codex harness

The plan is a confidential agent ("silo") on local Muse. Two candidates:

- **The bridge's own harness:** about 100 lines and one tool (`python`) in a
  no-network Docker container. Easy to audit; every capability has to be built by hand.
- **io's Codex harness** (`../io`): Codex under a bubblewrap wall with an
  io-written profile, approval escalation closed, a toolbox server outside the
  wall, and a PII-masking proxy for model traffic. io reports 17/17 sandbox
  conformance on this DGX as of 2026-10-11, after an AppArmor grant for bwrap.
  An earlier note here that bwrap "cannot run on the DGX" came from a
  stale comment in `codex.js` and is superseded.

Checked today: the local llama.cpp server answers the OpenAI Responses API
(`/v1/responses`), which Codex uses, so Codex can in principle drive local Muse.
Whether Muse handles Codex's tool protocol and prompts well is untested.

Possible split: Telegram for field use (data entry and quick questions,
through the simple harness), io/Codex for heavier work like dashboards. To be
decided by a correctness and auditability eval of both harnesses on more
realistic, messier workbooks.
