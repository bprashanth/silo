# Idli Ops livestock POC

A Telegram voice-note workflow using Silo's existing Whisper, local Muse and Kokoro (`hf_alpha`). No live-call components are used. The web application runs at **http://100.82.28.38:8766**; Telegram handles microphone permission and voice recording.

## Start

```sh
livestock/setup.sh
livestock/start.sh
# After ensuring the bot has no unanswered request:
tg-bridge/start.sh
```

`livestock/start.sh stop` stops only the dashboard/API. Muse and Silo use their existing startup scripts. `LIVESTOCK_STATE` holds the bridge key and asset directory; `LIVESTOCK_DB` optionally overrides the database path. Defaults are private NVMe state under `~/.local/share/idli-bridge/livestock/`. Packages and large synthetic test artifacts are on `/mnt/seagate/silo/livestock-v2/`. No secrets or private call records belong in git.

## Demonstrate

1. Open the dashboard and Telegram side by side. Send `/livestock farmer` to Silo.
2. Send a voice note: “My cow has been unwell since yesterday. She is not eating and seems weak.” Answer the follow-up questions. Use fictional details, for example Ramesh, Neemgaon, Demo North. Text works too. Correct a detail if needed, then confirm the summary.
3. The submitted case appears in the dashboard. Open it to see the original evidence, intake, protocol and recommended vet.
4. In the vet's Telegram chat, send `/livestock vet VET-01`. For a one-account roleplay, send this in the same chat; switch back to `/livestock farmer` for farmer feedback. Same-account feedback is labeled as roleplay, not independent verification.
5. In the dashboard, select the connected vet and approve assignment. Accept the assignment in Telegram.
6. Send a visit report by voice: state that you visited, what you observed, assistance provided and whether follow-up is needed. Send a photograph and a location pin. Confirm the report when asked. A photograph or location alone never establishes a completed visit.
7. Read the farmer feedback request. Switch to `/livestock farmer` if sharing one account. Say whether the visit occurred, what was done, the animal's current condition, whether more help is needed and whether you were satisfied.
8. Inspect the updated case evidence and feedback. An operator closes it in the dashboard. Disputed or unresolved cases remain open for review.
9. Open Insights. Ask “Which villages have the most unresolved cases?” or “What percentage of reported visits were independently confirmed?” Save a query result as a dashboard if useful.
10. Send `/livestock off` to resume ordinary Silo use. Case history is retained.

For two accounts, both must be permitted by the existing Silo allow list. Each account must start the bot and opt into its role. No real personnel are seeded or contacted. The five roster entries and 150 historical cases are fictional. Live demonstration cases are created only by incoming interactions and kept separately in provenance.

## Design

- `engine.py`: SQLite records, timestamped transitions, evidence, role associations, idempotent inbound messages, and transactional outbound notifications.
- `model.py`: local Muse extraction and validated protocol/vet/query selection. Application code controls permissions, assignment, closure and calculations.
- `config.py`: questionnaire wording, demo routing protocols and fictional roster.
- `storage.py`: local asset-store interface, suitable for a later S3 implementation.
- `app.py`: FastAPI case and analytical APIs. Telegram internal endpoints require a private shared key and loopback access. The operator UI is a trusted-network POC, without production operator authentication.
- `tg-bridge/livestock_bridge.py`: opt-in route in the existing bot, reusing its Telegram transport and speech functions. Text accompanies generated voice notes as a fallback.
- `static/index.html`: case desk, evidence timeline, assignment/closure controls and district insights.

Analytics query selection uses Muse; approved read-only SQL computes the answers from the actual case database. The standard dashboard also computes from live records. Query selection is deliberately limited to supported analytical questions; monthly outcome changes are descriptive and do not establish causes. There was no existing usable Idli Ops/Intelligence web application to integrate; this module supplies that POC surface while reusing Silo's local model infrastructure.

## Validation

```sh
python3 -m unittest livestock.tests.test_engine livestock.tests.test_bridge
tg-bridge/.venv/bin/python -m livestock.tests.test_live_model --voice
```

The model integration test uses actual Muse and a scratch SQLite database, with Telegram delivery mocked explicitly. Browser and live Telegram results are recorded separately in chronology and test evidence. Large audio and screenshots stay on Seagate. Never treat mocked transport as proof of real Telegram delivery or synthetic speech as proof of human accent/noise robustness.

Before a real program pilot: operator authentication and roles, robust delivery reconciliation, approved operational protocols, consent/retention policy, durable backups, real roster ownership and human clinical oversight are required. This demonstration provides intake and evidence handling, not medical advice or actual veterinary dispatch.

## Verified run — 15 October 2026

- Actual Telegram voice-note intake, a correction and explicit unknown answer produced case `CASE-4659ADD6FA`.
- Browser approval delivered the assignment; the same Telegram account switched to vet, accepted, sent a voice report, synthetic photograph and location, and confirmed the report.
- Silo delivered the farmer feedback request; switching back resumed it. A farmer voice note completed feedback, then the operator closed the case through the browser.
- The case retained 41 evidence records and two delivered proactive notifications. Its single-account verification is labeled as roleplay. Analytics became 151 cases (150 historical + 1 live), 115 reported visits, 84 farmer confirmations, and 83 independent confirmations. The actual SQL result was 83/115 = 72.2% independently confirmed.
- Sixteen deterministic tests pass. Separate real-Muse tests with mocked Telegram delivery pass both the voiced end-to-end flow and grounded-feedback regressions. Actual browser checks covered assignment, closure, queries, saved dashboard, playable assets, mobile width, and screenshots.
- Original test speech/photo were synthetic; Telegram transport, models, records and browser actions were real. No real animal, veterinary visit, or medical service was involved. Human accent/noise robustness and a two-account live Telegram demonstration remain unverified.

See `tests/evidence/` for small sanitized evidence and `chronology/2026-10-15T2343-livestock-v2-telegram-complete.md` for the delivery issue found and fixed. Full audio/screenshots are on Seagate. Ordinary Silo mode was restored with `/livestock off`; no user history was reset.
