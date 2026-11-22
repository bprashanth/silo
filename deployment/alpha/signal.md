# Signal alpha

An invited tester should be able to DM Idli, connect a Google test account in a browser, then ask “What did I last send to Asha?” or “How much did we spend on travel in March?” The first release should cover finding, reading and counting. A useful answer names the person, document or tab it used and gives the tester a way to open the source.

Today the DGX runs a numberless bot paired with one tester and one copy of a synced DuckDB store. Its Signal account ID (ACI) identifies the bot. A second, verified ACI identifies the allowed sender. Other senders and groups are ignored. See the [bridge setup](../../bridges/signal/README.md) and [Google and model setup](../../README.md#try-it).

## From one tester to several

| Work | Acceptance check |
|---|---|
| **Invite and route.** Keep one receiver for the bot. Have a maintainer issue a short-lived, single-use invite. On redemption, transactionally bind the authenticated sender ACI to an internal tester ID. Route by this binding on every turn. | An unknown sender gets onboarding at most. Replaying or forwarding a redeemed invite cannot open the original tester’s sandbox. |
| **Create private state.** Allocate a fresh directory per tester for DuckDB, Google credentials, logs, session and pending confirmations. Pass the bound Google account and directories explicitly to each CLI child. | Two testers can both say “yes” at the same time and resume only their own pending actions. A new tester starts with an empty store. |
| **Connect Google.** Provide a browser OAuth flow usable from a phone. Bind expiring state and PKCE to the invite redemption. Use a registered callback and validate the Google identity and granted scopes. Store refresh tokens only in that tester’s protected config directory. | Tester cancels, retries, reconnects and disconnects from their own DM. A callback opened or replayed for another tester cannot switch which mailbox a DM reads. |
| **Sync and report coverage.** Sync Gmail, Calendar, Drive metadata, readable document text and spreadsheet tabs per account. Show last successful sync, date windows, skipped attachments/tabs and connector errors. Serialize sync with that tester’s DuckDB writes. | A stale or partial sync gets a qualified answer, such as “I couldn’t find that in the email I have since Monday.” A failed Drive sync leaves Gmail usable. |
| **Queue, isolate and revoke.** Key inbound deduplication by sender and message ID/timestamp, persist destination with each outgoing reply, serialize turns per tester and retry delivery. Restrict worker access to its own files and credentials, including SQL file access. Disable hosted content judging for real accounts until its use is agreed. Review the current Gmail/Calendar scopes for the read-only pilot. | Plant different canary documents in two accounts. Exercise concurrent DMs, groups, restarts, swapped names, and a revoked invite. Neither sender receives the other’s content, links or confirmations. Disconnecting stops future sync and supports deletion. |

## What makes a short answer trustworthy

- **People.** Resolve a name against sender names, addresses and outgoing recipients in the tester’s synced mail. Ask for the exact address when two people match. For “what did I respond with last?”, inspect outgoing messages to that address in descending sent time. For a reply, look for an earlier incoming message from that person in the same thread. Incomplete sync history can hide a reply. Give the date, subject, actual message and Gmail thread link. An incoming message later in the same thread is a different answer.
- **Event PDFs.** Look in Drive and the relevant Gmail conversation. A filename or event invite matching the organizer and date is stronger evidence than separate word hits in an unrelated PDF. For weak evidence, ask for the date or organizer. Gmail attachment names, MIME types and attachment IDs still need indexing. A Gmail thread link lets the tester inspect the conversation while attachment retrieval is pending.
- **Numbers.** Identify the workbook and tab before computing. Similar filenames, copies and subtotal rows can change an answer. Return the value, unit, period and source. If two workbooks fit, show both links and ask which one to use.
- **Calendar.** Interpret “next” against the current instant in the tester’s timezone. Match guests when available, and distinguish an event title mentioning someone from a verified attendee. Give the local date and time.
- **Photos and sharing.** The pilot acknowledges an actual Signal attachment and explains the upload limitation. Enabling this later needs attachment download and size/type limits, folder selection, scoped Drive upload permission, recipient disambiguation and a preview naming the file, destination, recipient and access level. Require confirmation before granting access. Persist the uploaded file ID so a failed permission grant can retry without uploading twice. Verify the resulting permission before reporting success.

## Pilot observations on 22 November 2026

These are development checks on the paired test account. Messages went from the personal Signal account to the bot and replies were observed back on the personal linked device.

| DM | What happened |
|---|---|
| “Show me what I responded to Asha with last.” | The mailbox did not identify Asha. Idli asked for the email address. With a known test correspondent supplied, the returned message body and Gmail thread ID matched the newest qualifying outgoing reply in DuckDB. A separate fixture covers two people named Asha. |
| “Show me the Leads spreadsheets in my Drive with links.” | Two similar names produced two distinct URLs. Both IDs matched the workbook records. The first iteration failed when the mapper requested a nonexistent link column. |
| Named vegetation workbook and tab | The outline reported 1,876 data rows. Counting distinct block codes initially failed because the mapper used the wrong command. The retest returned **2 distinct nonblank block codes** and the workbook link, matching SQL on that tab. |
| “When’s my next meeting with Asha?” | An initial answer selected a past event. The corrected list query returned the upcoming event on 23 November at noon local time. Asha appeared in the event title; the guest list alone did not establish her attendance. |
| “Show me the PDF from the Royal Enfield event.” | Neither a file name nor a PDF passage established the requested event. Separate hits for the two words in an unrelated PDF are insufficient. The tester needs a filename, organizer or date to narrow this. |
| Picture with “upload this … and share it with Asha” | A real image and caption reached the bot. It explained the upload limitation and skipped the CLI turn. |

Source URLs identify the stored Google objects. Opening them still depends on the Google account signed in on the tester’s phone. Team isolation, browser consent and offboarding need a two-account acceptance run before inviting alpha users.

## How to test an invite

Use the [Signal development cases](../../benchmarks/bank/tasks_signal_dev.json) alongside the [original question banks](../../benchmarks/README.md). Expected outcomes describe fixture requirements. Use two disposable Google accounts for isolation and write-action tests. Put two contacts named Asha in one mailbox, seed sent and received messages out of order, create similar-looking budget sheets, and place one event PDF only in Gmail and another only in Drive.

Send turns from the tester’s Signal account to the bot username. Check the reply on the receiving Signal device. Compare dates, amounts and IDs with the tester’s store, then open links while signed in as that tester. For the photo case, send an image with its caption and check the destination Drive folder and permissions. The JSON bench can replay text; actual Signal DMs exercise sender routing, link rendering and attachments.

To replay a text case from the repository root, use a fresh output path and a copy of the matching fixture sandbox:

```bash
core/.venv/bin/python benchmarks/bench.py run --mapper nine_compressed --output humanize --no-yes \
  --tasks "$PWD/benchmarks/bank/tasks_signal_dev.json" --only A11 \
  --sandbox "$IDLI_SANDBOX" --out "$HOME/signal-a11.jsonl"
```
