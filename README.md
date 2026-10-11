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

## Current state

- **A Telegram bot** (`tg-bridge/`) that the team can message, send spreadsheets, PDFs and
  images to, and get answers and charts back from.
  - It runs against a model served on this box: Muse Glimmer 30B.
  - io's Codex answers, behind io's offline bubblewrap profile.
  - The bridge's own one-tool harness checks each answer independently, computing in a
    Docker container with no network and read-only files.
  - Every reply carries a badge (verified, disagrees, unverified, nothing to
    check), and `/how` shows the audit record behind it.
- **Measurements** (`benchmarks/`) of how we develop our understanding of useful and trustable. 
- **Proposals** for the correctness receipt and the audit trail that the "trustable" goals need.

**To run it:** [docs/deployment.md](docs/deployment.md) explains how to point the bridge at a
local model and start it.

## Layout

```text
tg-bridge/     the Telegram bot, its python-tool harness and sandbox image, test and eval scripts
wa-bridge/     the abandoned WhatsApp bridge (see chronology)
docs/          how to deploy and operate
proposals/     designs: correctness receipt, audit checker (both now built in tg-bridge)
chronology/    append-only log, one file per step, YYYY-MM-DDTHHMM-slug.md
benchmarks/    reproducible experiments: cases, scripts, raw run output
narrative/     longer notes drawn from several chronology entries and benchmark runs
```

## Relation to io

The bridge's answers come from io's pinned Codex binary under io's own sandbox profile
(`tg-bridge/io_config.js` calls io's `writeConfig`), and `benchmarks/harness-compare` uses the
same code. So a checkout of io next to this repo (`../io`, or `IO_APP`) is needed. Those
pieces are about 3.6 GB (the Codex binaries and the Python runtime) plus io's config code, so
they're referenced rather than copied. Without io the bot still runs, and its replies come from
the checker alone, marked unverified.
