# Can Idli find a link or its sender in WhatsApp groups?

On 22 November 2026 we tested the existing Silo core at `0609c9b` against a snapshot from the owner's linked DGX session. The month selects **groups**. Within each eligible group we took available cached text history, including older messages, with up to 2,000 records per group. The window started 22 October at 13:00 IST. Activity was the timestamp on the WhatsApp chat model.

## What we could verify

The Jam Buns smoke test found 167 texts. Across all 26 eligible groups we collected 2,701 texts. Two groups had no cached text. No group hit the cap. Repeating the snapshot yielded the same message IDs, bodies, timestamps and senders. Each group's count matched the browser cache's text-record count, and the newest cached text ID was present wherever there was one. The phone may hold earlier history.

We reused WA-JS 4.8.2 on the existing browser profile. After the linked client loaded, the benchmark switched the browser context offline, selected group models, checked group IDs and activity, and used scoped history reads. It compared unread counts before and after each group. It opened no conversations or external URLs. Only plain text messages were retained, including HTTP(S) links in their bodies. Private chats, attachments, captions, link previews, voice and videos were excluded. A sender is the available display name, and can be unknown. [WA-JS history reads](https://wppconnect.io/wa-js/functions/chat.getMessages.html)

An initial WA-JS history read returned zero for Jam Buns because the group had no default history anchor in this fresh session. We selected the newest locally cached text ID using read-only group-key ranges, then paged relative to that ID. A cached text count gives us an independent check on silent omissions. This depends on the WhatsApp Web cache schema. [Collector](groups.js)

## Results

Six direct CLI checks passed against reference computations on the source snapshot: group count, link-bearing message count, latest URL and sender, two scoped literal searches and an absent phrase. A named DuckDB view with `list --where --fields --order --limit` implements the latest-link operation. The benchmark adds two views to a private sandbox. Production core remains at the baseline revision.

Each natural-language case ran independently in humanized mode, with the loopback Qwen 3.5 9B mapper and judge, and automatic confirmations disabled. These are development cases. [Question bank](../../bank/tasks_wa_groups_dev.json)

| Case | Evidence and observed reply |
|---|---|
| W01 · nature walks link | No captured Jam Buns text contained “walk”. Four contained “nature”, with no URL in those messages or within two neighboring captured texts. The mapper used the abbreviated title as an exact filter. “I couldn’t find a match” gave no coverage. Semantic relevance of a bare URL still needs owner review. |
| W02 · Tata Trust sender | The 34 captured CC OGs texts contained neither “Tata” nor “Trust”. The mapper searched Gmail. Its empty reply had no WhatsApp evidence. |
| W03 · most recent link | Direct retrieval returned an exact URL. The conversational plan used exact equality on an abbreviated group name and omitted the link filter. It returned no match. |
| W04 · active groups | Answered 26, matching the reference. |
| W05 · number of link-bearing texts | Reference 5. The mapper asked the groups view for total text count and returned no match. |
| W06 · absent control phrase | The phrase was absent. The reply did not tell the user it had searched only captured text. |
| W07 · sender of most recent link | The sender was available. Exact group-name matching and an omitted link filter produced no match. |

As a diagnostic we repeated W03, W05 and W07 with the full display name and explicit HTTPS wording. The sender and count were recovered. The latest-URL answer still missed the reference. These assisted prompts are recorded privately and excluded from the ordinary wording results.

## Owner check on the DGX

From the repository root, use the frozen sandbox. Start with a link whose identity you can verify in WhatsApp on your phone.

```sh
export IDLI_SANDBOX="$HOME/.local/share/silo-owner-pilot/groups-CCXqKzmd/sandbox"
export IDLI_9B_URL=http://127.0.0.1:8291 IDLI_CHIPS=0
core/idli ask --new --mapper nine_compressed --judge nine_compressed --output humanize "What was the last link shared in Jam Buns? Give me the URL."
core/idli list wa_messages --where "group_name ILIKE '%jam buns%' AND links <> ''" \
  --fields sent_at,sender,links --order 'sent_at desc' --limit 1
```

Compare the URL, timestamp and sender. For the remembered nature-walk link, record its date on the phone first. The captured Jam Buns texts span 28 October to 20 November. An older phone match tests history coverage. A match inside this range tests ingestion and retrieval separately. For CC OGs the captured text spans 2–19 November. A no-match answer should say which group and period it searched.

## Replay

Private source snapshots, answers, diagnostic prompts and sandbox live under the DGX owner's mode-700 run directory above. Obtain access from the owner. From the repo root:

```sh
umask 077
d=benchmarks/runs/2026-11-22-whatsapp-groups
run="$HOME/.local/share/silo-owner-pilot/groups-CCXqKzmd"
core/.venv/bin/python "$d/check.py" "$run/groups.json" "$run/sandbox" "$run/answers.jsonl" "$run/repeat.json"
```

For a fresh capture, use system Python with Playwright, the headed Chromium executable, a linked test profile and the npm archive from `npm pack --ignore-scripts @wppconnect/wa-js@4.8.2`. The collector checks its SHA-512. Substitute private paths and choose new output names:

```sh
python3 "$d/snapshot.py" --profile "$PROFILE" --chrome "$CHROME" --wa-js-tgz "$TGZ" --out "$NEW/smoke.json"
python3 "$d/snapshot.py" --profile "$PROFILE" --chrome "$CHROME" --wa-js-tgz "$TGZ" --out "$NEW/groups.json" --all-active
core/.venv/bin/python "$d/import_snapshot.py" "$NEW/groups.json" "$NEW/sandbox"
IDLI_9B_URL=http://127.0.0.1:8291 IDLI_CHIPS=0 core/.venv/bin/python benchmarks/bench.py run \
  --tasks "$PWD/benchmarks/bank/tasks_wa_groups_dev.json" --sandbox "$NEW/sandbox" --out "$NEW/answers.jsonl" \
  --mapper nine_compressed --judge nine_compressed --output humanize --no-yes >"$NEW/bench.log"
```

## What to try next

Keep a local snapshot per group and give the mapper a way to resolve partial group names. Benchmark a message resource with timestamp, sender, stable reference, body and links. Existing predicates handle link presence. Generic views currently lack a date field mapping for `--since`. Compare the same bank after those changes before adding verbs. For polling, use stable group and message IDs, re-read an overlapping window for edits and deletions, and report last successful refresh and coverage per group. A single manual no-media export could serve as the reference for an older remembered link. [WhatsApp export instructions](https://faq.whatsapp.com/1180414079177245/)

WhatsCLI is a terminal client built on whatsmeow and supports sending and attachments. Whatsmeow offers a separate multidevice client. Both would introduce another session for this test. WhatsApp-web.js also has browser-based history reads. WA-JS supplied the group selection and message reads that worked here with the already-linked session. [WhatsCLI](https://github.com/normen/whatscli) · [whatsmeow](https://github.com/tulir/whatsmeow) · [whatsapp-web.js](https://github.com/wwebjs/whatsapp-web.js)
