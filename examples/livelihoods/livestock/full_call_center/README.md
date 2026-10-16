# Buffalo Soldiers livestock POC — frozen example

Canonical source: `examples/livelihoods/livestock/full_call_center/`. There is no root compatibility symlink. Python modules use `examples.livelihoods.livestock.full_call_center` directly. Run commands from the repository root.

Frozen after commit `39340af` (16 October 2026), with relocation and documentation changes only. The proposed conversational checklist agent is **not implemented**. Clarification requests and partial answers can still repeat questions. See the [narrative](../../../../narrative/call_center_automation.md).

Current trial: English input, English replies and Kokoro `af_heart` (`en-us`). The Hindi implementation and validation below describe the preceding trial; Hindi is not currently enabled in the Telegram adapter. Existing case records are retained.

Send an English voice note to [@Buffalosoldiers_bot](https://t.me/Buffalosoldiers_bot). The bot asks for missing details, reads back a summary, and submits a case after confirmation. Replies include English text and Kokoro speech (`af_heart`). The [case desk](http://100.82.28.38:8766) handles assignment, evidence, feedback and closure. Telegram records voice notes; there is no browser microphone or live-call setup.

## Independent bot

All Buffalo code lives in `examples/livelihoods/livestock/full_call_center/`: `bot.py`, `transport.py`, `client.py`, and `speech.py`. The original Silo bot stays in `tg-bridge/`, running its restored code without a livestock menu or routing. Buffalo has its own polling state and service; both share the existing local Muse endpoint at `127.0.0.1:8181` and local speech models.

The new token is read from `livestock_botfather_api_key` in `~/.config/idlisseus/telegram.json`. Private-chat access uses the numeric Telegram account IDs in `~/.config/livestock/allowed.txt`, currently permitting only the owner. This is an account-ID allow list, not phone-number matching. No channel or second account is needed for the current demonstration. Never commit either configuration file.

## Run

From the repository root:

```sh
examples/livelihoods/livestock/full_call_center/setup.sh             # Install the independent environment if needed
examples/livelihoods/livestock/full_call_center/start.sh             # Case desk/API on 0.0.0.0:8766
examples/livelihoods/livestock/full_call_center/bot.sh start         # Dedicated systemd user service
examples/livelihoods/livestock/full_call_center/bot.sh status
# Optional case board:
examples/livelihoods/livestock/full_call_center/fizzy.sh start
```

`examples/livelihoods/livestock/full_call_center/bot.sh stop` stops only Buffalo; `examples/livelihoods/livestock/full_call_center/start.sh stop` stops only the case desk/API. Logs are available with `journalctl --user -u silo-buffalo` and the private `server.log`. These commands do not restart or modify the original bot.

Private database, key, assets and Buffalo state live under `~/.local/share/idli-bridge/livestock/` by default (`LIVESTOCK_STATE`; optional `LIVESTOCK_DB`). Packages and large synthetic artifacts live under `/mnt/seagate/silo/livestock-v2/`. The independent Python environment is `$LIVESTOCK_STATE/venv`, not `tg-bridge/.venv`.

## Demonstrate the current English trial

1. Open Buffalo and the case desk side by side. Send an English voice note directly, for example: “My cow has been weak since yesterday.” A new account automatically enters the farmer role.
2. Answer the questions about the animal, symptoms, urgent signs, onset, number affected, prior treatment, name, village and district. English text works too. Unknown answers and corrections are supported. Confirm the summary to submit the case.
3. Open the case in the desk to inspect its details and original evidence. Draft intake records remain distinguishable from submitted cases.
4. For the same-account vet roleplay, send `/vet VET-01`. Approve assignment to that connected vet in the desk, then accept it in Telegram.
5. Report the visit by voice, including observations, assistance and whether another visit is needed. Send a photograph and location, then confirm the report. Media alone does not prove a completed visit.
6. Switch back with `/farmer` to answer the feedback request. Report whether the vet came, what happened, the animal's condition, satisfaction and further help needed. The operator reviews the case and closes it in the desk; disputes remain open.

Same-account feedback is explicitly roleplay, not independent verification. The roster and historical seed cases are fictional. Adding a second tester requires allowing their account ID and having them start Buffalo first.

## Optional Fizzy board and rollback

[Fizzy setup and limitations](fizzy.md) describe the local instance on port **8767**. Use the Fizzy link in the case desk to open its shared board. It mirrors confirmed cases one way; assignment and other operational actions remain in the case desk. No case data is uploaded to fizzy.do. Drafts, historical seeds, raw transcripts, Telegram identifiers and media are excluded.

`examples/livelihoods/livestock/full_call_center/fizzy.sh stop` disables the mirror and board while leaving both bots and the case desk running. The existing desk remains the fallback; disabling Fizzy requires no case database restore.

The Git tag **`livestock-v2-before-buffalo-hindi`** checkpoints the preceding implementation. A private database checkpoint is stored under `~/.local/share/idli-bridge/livestock/checkpoints/`. Restoring that database would discard later case changes, so it is not part of disabling Fizzy. Code rollback and database restore are separate operations.

## Implementation and validation

At freeze, 29 deterministic tests pass. Use `PYTHONPATH=/mnt/seagate/silo/livestock-v2/packages` with the private venv when running the tests. Historical Hindi tests do not change the active English bot.

- `engine.py` controls case state, grounded extraction, permissions, confirmation, evidence and notifications.
- `config.py` defines the questionnaire, fictional roster and routing protocols.
- `hindi.py` provides fixed Hindi questions and local Muse translation. Original Hindi remains in evidence; English canonical text is labeled separately. `model.py` sends readable Unicode to Muse.
- `app.py` and `static/index.html` provide the case desk and bounded analytical queries. Internal bot requests use a private key and loopback access.

Run tests from the repository root:

```sh
export PYTHONPATH=/mnt/seagate/silo/livestock-v2/packages
livestock_python="$HOME/.local/share/idli-bridge/livestock/venv/bin/python"
"$livestock_python" -m unittest discover -s examples/livelihoods/livestock/full_call_center/tests -p 'test_*.py'
"$livestock_python" -m unittest examples.livelihoods.livestock.full_call_center.fizzy_test
# Explicit integration tests; these call local models:
"$livestock_python" -m examples.livelihoods.livestock.full_call_center.tests.test_hindi_live
"$livestock_python" -m examples.livelihoods.livestock.full_call_center.tests.test_hindi_speech --generate /mnt/seagate/silo/livestock-v2/buffalo-tests/fixtures
```

The Hindi model integration test has passed intake through explicit unknown, negative warning answer, corrections and confirmed submission. It uses actual Muse with a scratch database, not Telegram transport. Synthetic Hindi speech tests exercise Kokoro and Whisper separately. The actual Buffalo Hindi Telegram run created and closed `CASE-A27665EA9D` through intake, vet acceptance/report and farmer feedback. All 26 deterministic tests pass. See `../../../../chronology/2026-10-16T0830-buffalo-hindi-fizzy.md` and `tests/evidence/buffalo-hindi-live.json`. That completed test left no open case; subsequent user testing created an unfinished intake.

The 15 October English end-to-end run in `tests/evidence/` and `../../../../chronology/2026-10-15T2343-livestock-v2-telegram-complete.md` is historical evidence from the former Silo integration. It verified real Telegram delivery and browser workflow using synthetic media; it does not establish validation of the new Buffalo Hindi deployment.

This is a trusted-network POC without production operator authentication, clinical protocols or real veterinary dispatch. Speech recognition and translation can make mistakes; the farmer's confirmation and operator's original-evidence review remain necessary. Synthetic speech tests do not establish performance with human accents, background noise or independent farmer/vet accounts.
