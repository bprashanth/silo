# Buffalo Soldiers: independent Hindi intake and optional Fizzy

The user requested a separate owner-only livestock bot, preserving the original io/Silo bot, Hindi voice-note intake and replies, and a reversible Fizzy demonstration.

## Checkpoint and isolation

Before migration, tag `livestock-v2-before-buffalo-hindi` preserves commit `e938b1b`. A mode-600 SQLite backup is at `~/.local/share/idli-bridge/livestock/checkpoints/before-buffalo-hindi/cases.db`. No private configuration or database is committed.

The original `tg-bridge/tg_bridge.py` and `speech.py` exactly match pre-livestock commit `13f3677`; the livestock adapter was removed. Its process remains running and Telegram getMyCommands confirms `/livestock` is absent. Its token and user conversation history are retained. All new bot code is under `livestock/`, without tg-bridge imports. Buffalo uses only the new livestock token, a separate numeric allowlist with exactly one owner account, private-chat checks, independent persistent inbox/offset and a systemd user service. Message IDs are namespaced to prevent collisions with original-bot history. The existing case database is retained.

## Hindi behavior and issues found

Ordinary Hindi voice or text starts farmer intake without a mode command. Original Hindi/audio is retained alongside separately labeled English canonical extraction. Muse remains the existing local service. Whisper uses Hindi; Kokoro uses Hindi `hf_alpha`. Devanagari combining marks are preserved in spoken text.

Actual model testing caught JSON Unicode escaping causing Muse to mistranslate Hindi. Sending readable Unicode fixed the failure. Tests cover unknown answers, negative warning signs, corrections and confirmation. The animal question is asked when missing; a complaint explicitly naming a cow already supplies that field. Eight synthetic speech fixtures exercised Kokoro-to-Whisper round trips. Synthetic round trips do not establish human-accent or noisy-recording performance.

## Real Telegram verification

`CASE-A27665EA9D` was created through the actual Buffalo bot using synthetic Hindi voice notes. The bot asked about urgent signs, count, identity and confirmation, and returned Hindi text and real voice messages. The returned urgency question audio was decoded and transcribed back to Hindi: valid mono Opus, 6.13 seconds, non-silent RMS 0.161.

The same authorized account switched to vet, accepted an operator assignment, sent a Hindi voice report, clarified an explicit visit and observations in Hindi text, and confirmed the report. The bot delivered the farmer feedback request. Switching back to farmer and sending the Hindi feedback fixture produced visit confirmation, improvement, satisfaction and no further help. The operator closed the case. There are 42 evidence records; verification is labeled `single-account roleplay`, excluded from independent-confirmation metrics. The account is left in farmer mode with no open case, ready for a fresh voice-note test. No real veterinary visit occurred.

Twenty-six deterministic tests pass, covering engine behavior, Hindi handling, transport retries, owner/group isolation, Devanagari speech and Fizzy recovery. Actual model and Telegram results are separate from mocked transport tests. Some full voice responses take tens of seconds; this is asynchronous voice-note intake, not real-time calling. Live test collection was corrected to await both reply text and audio, avoiding a delayed voice reply being attributed to the next input.

Small sanitized evidence: `livestock/tests/evidence/buffalo-hindi-live.json`. Audio, session logs and speech verification: `/mnt/seagate/silo/livestock-v2/buffalo-tests/`. Model progression: `/mnt/seagate/silo/livestock-v2/tests/hindi-intake/actual-muse-human-progression.json`.

## Fizzy and fallback

Official Fizzy is self-hosted locally on port 8767, using its pinned ARM64 image. No cases were uploaded to fizzy.do. An independent one-way polling worker mirrors submitted live cases, excluding draft intake, historical seeds, Telegram IDs, transcripts and media. Card field labels/status are Hindi; canonical field values and native navigation can be English. The existing desk on port 8766 remains authoritative for assignment and closure.

Native API tests covered create, repeat sync, move, close, cache-loss recovery and reopen. Browser testing caught a missing account prefix in the public URL and duplicate closed cards from an open-only API listing; both were fixed. Browser inspection opened card 19 for the new Hindi case, verified its active status and followed its link to the correct selected desk case without JavaScript errors. A final browser check verified the closed case under Done, Hindi status बंद, and a working direct public card link. Screenshots are `/mnt/seagate/silo/livestock-v2/fizzy-hindi-*.png`.

To revert the optional board only, run `livestock/fizzy.sh stop`; both bots, the case desk and case history remain. No database restoration is needed. The preceding-code tag and private database checkpoint are separate full rollback artifacts; restoring the database would discard later cases and is not part of disabling Fizzy.
