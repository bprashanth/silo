# Codex can drive local Muse

Feasibility probe for the Codex path. Plain `codex exec` 0.162.1 (not io's pinned
0.154 build or its profile), with an isolated `CODEX_HOME` and a custom provider
pointing at llama.cpp's `/v1/responses` on 127.0.0.1:8181. Settings:
`approval_policy = "never"`, `sandbox_mode = "workspace-write"`. Task: the
Transactions total of the NGO workbook.

Result: `ANSWER: 39794400`, which is correct, in 111 s and 17.9k tokens. The model ran 16 shell
commands for one sum, including a find, header dumps, several `python3 -c`
one-liners (one a syntax error) and a heredoc. The bridge's own harness usually takes 1 or 2
tool calls for the same question.

Observations that matter for the harness decision:

- Codex warns "Model metadata for `muse-glimmer-30b` not found", which means fallback
  prompts and settings were used. It works, but it isn't tuned for this model.
- `codex exec` waits on stdin unless it is given `< /dev/null`.
- `CODEX_HOME` does not isolate everything: it still tried to load skills from
  `~/.agents/skills`.
- Stock `workspace-write` blocks writes and network, but not reads outside the
  folder. Read denial needs io's own profile, which the bwrap backend enforces.
- Every action is a raw `bash -lc` string, rather than one typed `python` call,
  so the audit surface is the shell.

Evidence: `benchmarks/ngo-workbook-correctness/runs/2026-10-11-codex-local-probe/`.
