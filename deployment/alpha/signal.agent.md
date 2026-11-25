# Signal alpha — implementation status (2026-11-24)

Implementation companion to [signal.md](signal.md) (`AGENTS.md` sibling convention).

## What is implemented

| Area in [signal.md](signal.md) | Implementation | Status |
|---|---|---|
| **Invite and route** | `bridges/onboard/store.py` (`create_invite`, `redeem_invite`, `create_setup_session`) + `bridges/signal/bridge.py` (`handle_multi_turn`, `serve_multi`, activated via `IDLI_ONBOARD_STATE`). Single-use transactional invites bound to verified `sourceUuid`; uninvited strangers ignored when `IDLI_ONBOARD_INVITE_ONLY=1`. | Implemented & tested (`bridges/onboard/test_onboard.py`, `bridges/signal/test_bridge.py`). |
| **Private per-tester state** | Each tester receives a dedicated `0700` directory under `<state>/testers/<tester_id>/` holding `store.duckdb`, `google_oauth_token.json` (`0600`), `profile.json` (`0600`), session, and logs. `bridge.ask()` passes explicit `IDLI_SANDBOX` and `IDLI_GOOGLE_ACCOUNT` to each CLI child and defaults `IDLI_CHIPS=0`. | Implemented & canary-isolation tested across two simultaneous testers. |
| **Connect Google & WhatsApp (read-only)** | `bridges/onboard/server.py` implements Google Web OAuth with PKCE (`S256`) + expiring `state` (`/setup/<token>/google/start` & `/oauth/google/callback`) plus read-only WhatsApp pairing via `bridges/whatsapp` (`silo-wa-sync`, QR and 8-digit phone code). Includes `--demo` local preview mode when no public HTTPS callback is configured. | Implemented & Playwright-verified (desktop + 390px mobile). |
| **Scoped sync (`--in`)** | Onboarding Step 2 lets testers check only the Drive folders and WhatsApp groups/chats they are comfortable sharing (e.g., 2–5 items) and executes `core/idli sync ... --in ...` into their private sandbox. | Implemented & verified end-to-end on real DuckDB stores. |
| **Role & intended use (`profile.json`)** | Onboarding Step 3 provides role pills + 3 clickable examples (Insights, Partnerships, Marketing) + freeform textarea. Deterministically extracts Drive links and matching folder/group names to suggest scopes and writes `<sandbox>/profile.json` (`0600`). Kept strictly outside the 9B mapper prompt so it informs workflow triage without hurting core CLI accuracy. | Implemented & Playwright-verified. |
| **Signal DM confirmation & disconnect** | Step 4 displays a 6-digit `confirm <code>` command bound to the original `signal_aci` (forwarded URLs cannot activate another tester's workspace). Active testers can send `status`, `setup`, or `disconnect` (deletes sandbox data) in Signal DM. | Implemented & tested. |
| **Mixed Google + WhatsApp over Signal** | Verified `bridges/signal/bridge.py:ask()` against a mixed Google (`silo-smoke`) + `--in`-scoped WhatsApp sandbox (`Jam Buns`, `Acumen`) with zero cross-source routing leaks and clean `--output humanize` receipts. | Verified live on DGX. |

## Still needed before public `silo.idli.cc` launch

- Register the production Google Web OAuth client and HTTPS reverse proxy callback (`https://silo.idli.cc/oauth/google/callback`) while keeping model endpoints loopback-only.
- Per-tester container isolation for `silo-wa-sync` + worker execution (current local prototype isolates per-tester `0700` directories on host; production multi-user should run one unprivileged worker container per tester as described in [signal.md](signal.md)).
- Two-account live phone acceptance pass with two disposable Google + WhatsApp accounts over real Signal DMs.
