# Silo

<img width="687" height="714" alt="Screenshot from 2026-10-11 22-41-33" src="https://github.com/user-attachments/assets/155accd1-e514-4fa9-a18e-15fccdbd2fd9" />


Silo is the first product prototype to come out of the event [io](https://github.com/bprashanth/io)
was built for.

It's a confidential assistant for a small NGO team. People talk to a model that runs
on a "confidential VM", the model computes over their files in a sandbox.

## Goals

1. Trustable
2. Useful
3. Cheap

AI.

**Trustable** means:
- **private:** data never leaves the laptop `<->` our servers without the user's consent.
- **correct:** two or more models verify each answer independently.
- **reproducible:** the same question asked again gets the same answer.
- **verifiable:** users can check the steps taken to produce the result.

**Useful** means:
- it works on field data formats: messy spreadsheets, pictures, chat logs, voice notes...
- it assumes users aren't coders, and shows visuals first.
- it brings in Indian context without being asked.

**Cheap** is self-explanatory.

Why is privacy a challenge? Because the agent harness is extremely powerful:
1. it can try things;
2. it can backtrack and try more things.

That same power lets it pursue a goal at any cost, even when the cost turns out to be
"send data to a remote server". The chance is small but not zero, so we need measures that
guarantee privacy. The failproof one is to block network access. That can only be done
reliably on the server, because the user base's Windows machines vary too much.

## Prerequisites 

Prerequisites to run the stack locally:     
1. Python 3, [uv](https://docs.astral.sh/uv/)
2. A maintainer-issued `silo-team-config.tar.gz`
3. and Docker.

## Quickstart (Team Laptop CLI)


```bash
git clone <repo-url> && cd silo
./setup.sh --config ~/Downloads/silo-team-config.tar.gz --account you@example.org
source .env
idli sync gmail -v
idli sync drive --in "<Folder Name>" -v
```

- **Commands to try next:** follow the [CLI cheatsheet](docs/cheatsheet.md) (`sync --in`, `list`, `summarise`, `ask -v`).
- **More setup details & maintainer bundles:** [deployment/team/README.md](deployment/team/README.md).
- **Non-engineer Signal testing:** [narrative/ALPHA_TESTING.md](narrative/ALPHA_TESTING.md) (DM -> onboarding link -> `--in` folder/group picker -> Signal confirmation).

## Active Testing & Deployment Plans

| Track | What it covers | Doc |
|---|---|---|
| Stage 1 — Team CLI | Repo-local laptop setup, scoped `--in` sync, inner CLI loop | [deployment/team/README.md](deployment/team/README.md) |
| Stage 2 — Alpha testing guide | Engineer CLI checklist + non-engineer Signal onboarding & test queries | [narrative/ALPHA_TESTING.md](narrative/ALPHA_TESTING.md) |
| Signal alpha rollout | Multi-user isolation, OAuth PKCE, confirmation codes, acceptance checks | [deployment/alpha/signal.md](deployment/alpha/signal.md); [status](deployment/alpha/signal.agent.md) |
| Connectors & onboarding | Read-only WhatsApp sidecar, Signal bridge, onboarding web UI | [bridges/whatsapp](bridges/whatsapp/README.md); [bridges/signal](bridges/signal/README.md); [bridges/onboard](bridges/onboard/README.md) |

## Benchmarks & Regression Testing

Masure retrieval claims on a blind held-out bank (see [benchmarks/README.md](benchmarks/README.md) for banks, runner, and grading rubric):

```bash
# Fast unit + contract checks (prose budget, CLI output, WhatsApp search, Signal, onboarding, installer)
(cd core && .venv/bin/python -m unittest discover -s tests)
PYTHONPATH=. python3 -m unittest discover -s bridges/signal
PYTHONPATH=. core/.venv/bin/python -m unittest discover -s bridges/onboard
PYTHONPATH=. core/.venv/bin/python -m unittest discover -s deployment/team
```

- **Google regression (`tasks_owner_dev.json`):** `core/.venv/bin/python benchmarks/bench.py run --mapper nine_compressed --no-yes --tasks benchmarks/bank/tasks_owner_dev.json --sandbox <COPY> --out /tmp/run.jsonl`
- **WhatsApp retrieval & blind held-out runs:** [2026-11-24 core run](benchmarks/runs/2026-11-24-whatsapp-core/README.md) and [2026-11-25 v2 blind verification](benchmarks/runs/2026-11-25-whatsapp-core-v2/README.md).
- **Rule of thumb:** iterate on dev banks, never overfit to one question, and validate claims once on frozen code with a blind grader ([docs/decisions.md](docs/decisions.md)).

## Docs & Repo Layout

- **Core design & usage:** [docs/README.md](docs/README.md) (reading order); [docs/cheatsheet.md](docs/cheatsheet.md); [docs/cli.md](docs/cli.md); [docs/decisions.md](docs/decisions.md); [docs/search.md](docs/search.md); [agent companions](docs/README.agent.md)
- **Context & evidence:** [narrative/](narrative/) (readable summaries, e.g. [whatsapp-search.md](narrative/whatsapp-search.md)); [chronology/](chronology/) (dated logs); [AGENTS.md](AGENTS.md) (placement & workflow rules)

```text
core/          CLI and DuckDB record store per sandbox (core/idli, core/lib/, core/tests/)
bridges/       channel & source connectors (signal/, whatsapp/, onboard/)
deployment/    rollout guides & team installer (team/, alpha/, beta/, ga/)
benchmarks/    question banks (bank/), runner (bench.py), grader rubric, dated runs (runs/)
docs/          design docs, CLI reference, cheatsheet, and *.agent.md companions
proposals/     workflows/ for reusable chains; pilots/ for outcomes to benchmark; architecture/
narrative/     readable summaries of findings and testing guides (ALPHA_TESTING.md, whatsapp-search.md)
chronology/    timestamped decision and experiment logs
handoff/       continuation notes for active tracks
todos/         owner review queue and open bug lists
archive/v1/    earlier Telegram bot prototype (old)
examples/      frozen livestock call-center examples from v1 (still running a service)
```

## History

Silo started as a Telegram bot on a 30B model with answer checking (October 2026), now in `archive/v1/`. The core was built and measured in the `io` repo in November 2026 and moved here; see [docs/from-io.md](docs/from-io.md).
