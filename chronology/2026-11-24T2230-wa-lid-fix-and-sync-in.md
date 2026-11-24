# 2026-11-24 22:30 IST — WhatsApp `@lid` contact backfill, search polish, and `sync --in`

## What the owner tested and reported

After the Step 1 core WhatsApp retrieval milestone ([2026-11-24T0140-whatsapp-core-results.md](2026-11-24T0140-whatsapp-core-results.md)), the owner ran live CLI queries against `~/idli-sbx/wa-test` (synced from the read-only `whatsmeow` sidecar) and noted two confusing behaviors:

1. A group summary surfaced raw 15-digit numeric IDs (`@<lid>`) in place of sender names and mentions.
2. Searching a group for a colleague's follow-up Google Doc ranked an unrelated mention above the colleague's actual link; on a follow-up query, the 9B mapper filtered `source_type = 'document'` (which matched 0 rows because shared Google Doc URLs have `source_type = 'text'`), and on another turn emitted three separate `list messages --search` commands where only the last command's rows reached the answer.
3. For initial testers, the owner asked for a repeatable `--in` flag on `idli sync` to scope ingestion to specific Drive folders or WhatsApp groups/chats.

## Root cause & changes

1. **`bridges/whatsapp/main.go` (`@lid` resolution + startup backfill):**
   - `whatsmeow` emits WhatsApp's newer `@lid` JIDs for many group senders and `@<lid>` mentions. `whatsmeow_lid_map` already mapped 100% of those LIDs to phone-number JIDs in `whatsmeow_contacts`, so resolving LID → PN before contact lookup and rewriting `@<lid>` mentions in message bodies fixed both symptoms without requiring re-pairing.
   - Added startup + post-HistorySync backfill on cached `snapshot.json`. Rebuilt `silo-wa-sync` and restarted `silo-wa-smoke`: backfilled 1,377 cached messages immediately, dropping numeric senders across the live snapshot from **64.0% → 1.0%** (0% in the tested work groups) and raw numeric mentions from **87 → 1**.
2. **`core/lib/idlicli.py` (`_merge_list_searches` + `sync --in`):**
   - Merged consecutive same-scope unquoted `idli list <resource> --search ...` commands in `run_plan()` into one `--search` so Stage 1 high-recall OR + Stage 3 cross-encoder reranking sees all terms together instead of overwriting prior step results.
   - Added repeatable `--in` / `--folder` to `idli sync`, wired to `sync whatsapp` (fuzzy chat/group matching via `_chat_matches_selector` in `core/lib/searchkit.py`) and `sync drive` (folder path/name filtering in `core/lib/recstore.py`).
3. **`core/lib/recstore.py` (`source_type` note + shared-link fallback):**
   - Clarified `FIELD_NOTES['messages']['source_type']` so `idli help messages` and `menu()` distinguish uploaded file attachments from shared URLs.
   - In `fused_messages()`, when `--where` filters `source_type = 'document'` and finds no strong attachment match, automatically retries in the same scope with `(source_type = 'document' OR links <> '')` with an explicit note (`No uploaded file attachments matched; searched messages with shared links.`). Raw `idli query` SQL remains strict.
4. **Docs & tests:** Updated `docs/cli.agent.md` for `sync --in` and added 3 regression tests in `core/tests/test_whatsapp_search.py` (`29/29` core + `10/10` Signal bridge passing, prose budget unchanged and passing).

## Verification

- Re-synced `~/idli-sbx/wa-test` (`65 chats, 1,944 messages, 548 episodes` in `19.8s`) and verified `--in` scoped sync (`2 chats, 187 messages, 50 episodes` in `1.8s`).
- Re-ran the owner's live queries with `--output humanize`:
  - Follow-up doc query now resolves the colleague's display name + `@mention` names and ranks the follow-up reply, original call message, and Google Doc URL in the top 3 results.
  - Group summary now displays real participant names with zero raw `@<lid>` numbers.
  - Standalone `"who sent the ... google doc ...?"` query now recovers the Google Doc at #1 via the shared-link fallback, though without parent-message expansion when `--where` excludes the non-link parent (noted as an open item for the next pass).

## Open items (next overnight candidates)

1. Allow episode/parent context expansion in `search_messages` to pull the immediate quoted parent even when `--where` narrowed candidates (e.g., `links <> ''`), so the reader sees why a link answers a thread question.
2. Remaining blind-benchmark gaps from `2026-11-24`: single-letter/ambiguous sender disambiguation when 9B omits `sender ~`, `compose()` wording/caveat fidelity, and `summarise --search` recency handling on `"latest discussion"` prompts.
3. Live WhatsApp + Google mixed sandbox over `bridges/signal/bridge.py`, and multi-user Signal + Google Web OAuth + per-user `whatsmeow` onboarding (`deployment/alpha/signal.md`).
