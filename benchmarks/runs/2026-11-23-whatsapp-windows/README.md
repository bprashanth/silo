# Finding evidence across WhatsApp messages

A 23 November 2026 development benchmark on the owner’s linked DGX client, with the CLI at 64396b5. The [13 questions](cases.json) include eight positive lookups and five controls. Cases were selected with knowledge of the history. This run can guide an experiment on fresh cases; it does not estimate user-facing accuracy.

## What was tested

The [collector](../2026-11-22-whatsapp-groups/snapshot.py) read locally cached text, image captions and reply metadata from 26 groups active in the last calendar month. It retained 2,783 messages. Date filters apply in IST. On Monday Nov 23, “last week” means Nov 16–22. The initial CLI run used one independent shell turn per question, the local compressed 9B and local judge, no hosted chips. It used a clean copy of the WhatsApp-only DuckDB. The private stock log records the actual plans, answers and struggle signals. No source was written.

The [retrieval harness](trial.py) reads the same snapshot and uses the existing local Idli embedder and answer writer. It takes explicit group and date slots to isolate retrieval from natural-language parsing. The exact-link count uses DuckDB. The resolver matches normalized token prefixes against the scoped directory. The control with an ambiguous sender returns choices. This is assisted input and a structured result in a benchmark, not a shipped clarification flow.

The initial arms used two token-overlap hits, two message embeddings, ±5 chronological neighbors of those same semantic hits, a reply-aware packet from those hits, or the three highest-ranked conversation bursts. A burst contains up to five same-group messages with gaps of at most five minutes. The reply packet includes in-cache parent/direct-reply edges, nearby same-sender posts within five minutes, and ±3 chronological neighbors. A final arm asked the local judge to select evidence from the entire scope if at most 50 messages, otherwise from the reply packet. Results are candidate-message IDs plus the unchanged answer writer’s output or guard rejection. The writer has its existing 4,000-character input cap. Ranking and context assembly here use in-memory arrays, so this trial gives no DuckDB expansion latency claim.

For each positive case the [reference](reference.json) lists the source records that establish the answer. Each inner set contains alternatives; all sets must be represented. Form retrieval gets credit for Tejasa’s actual document link. A claim to have read the full questionnaire is graded separately. The orgs case tests three specifically discussed partner leads, distinct from names in the pasted conference agenda.

## First comparison

| Measure across eight positives | Literal | Message embedding | ±5 | Reply-aware | Burst embedding | Local judge |
|---|---:|---:|---:|---:|---:|---:|
| Cases with all reference evidence retrieved | 2 | 2 | 2 | 2 | 2 | 2 |

The two successes in every column were the roster and Nadhi. A plain message embedding plus the existing answer writer reproduced the roster and its lead. The Nadhi attendance-eligibility note was retrievable, yet the writer also folded an unrelated discussion of future calls into its summary. Burst retrieval picked up one of three partner leads. For the remaining cases, expanding two low-quality hits mostly provided more unrelated text. The stock CLI produced no complete, grounded answer on the eight positive cases.

For controls, binding Jam Buns by its abbreviated title gave the correct six HTTP(S)-bearing rows. A nonexistent group yielded suggestions rather than a count. The weak similarity suggestions included unrelated groups. Matching “V” across any token produced six sender choices, including surname and interior tokens. Choices still need ranking. September yielded zero captured records, so the IAF question has no coverage in this snapshot. Record the coverage gap, not a negative claim about IAF. For actual Royal Enfield attendance, the reply-aware writer introduced unsupported attendee counts. No final attendance was established. The stock `struggled` signal flagged the sender command failure; it missed the confidently wrong zero count for the unknown group.

## Same linked post, different evidence

For Tejasa and Abhiram we tested a bound group, a unique sender-prefix match within that group, and a nonempty links column. Each DuckDB lookup returned exactly one post. This was an assisted artifact lookup; the stock mapper failed both. With Abhiram’s post as the anchor, ±5 retrieved his preceding decline but missed the earlier DICE invitation. Adding the parent of the neighboring decline returned all three references in 12 rows versus 11. The relationship-aware 9B returned the correct link but its explanation ended mid-sentence. Judging before answering dropped the decline entirely. Preserve the relationship in the result shown to the user.

For Tejasa the source was a Google Doc, while the later Pune link was a spreadsheet shared by the owner. Reading the exact Doc through the configured Google test account returned HTTP 404. The surrounding group messages mention AI use and the organisation’s thematic focus, and say the website question was included. Neither a plausible Pune question nor a citation to the review link verifies a complete Royal Enfield questionnaire. The chronological answer incorrectly listed Pune examples as the requested questions. Explicit relationships helped identify the right link but did not establish the document contents.

## Rewritten retrieval and scope-then-judge

One exploratory arm let the local 9B rewrite the question for content search. It interleaved lexical hits, message embeddings and burst embeddings, expanded nearby and linked records, and passed at most 50 candidates through the local judge in batches of eight. A structured local answer writer received the selected evidence, capped at 16,000 characters. This changed both ranking and reading budget. We cannot attribute the improvement to query rewriting alone. The roster rewrite returned malformed JSON twice and fell back to the original question.

| Case | Full reference evidence in hybrid packet | What the answer got right or wrong |
|---|---|---|
| RE session length | Yes | Returned the second session’s hour and omitted the first session’s 30 minutes. A full-group judge found both but also gave a misleading total for the conference. |
| Tej’s review document | No | Found discussion of sending the questions. The separately bound author/link lookup recovered the exact review document. |
| Futures roster | Yes | Found the posted list and named Yash as lead. The initial hit-only answer also reproduced the roster. |
| DICE document | Partial | Recovered the link and decline, but added an unsupported reason for absence. The directed parent control above recovered the missing invitation. |
| Partner organisations | Yes | Found EFI, Roots and Branches and the SESTA message. The answer blurred SESTA with its Climate Coalition connection. |
| Nadhi | Yes | Accurately qualified the participant note; the cache does not establish a complete event brief. |
| Two field crews | Yes | Retrieved Rinju’s Nov 19 post and both destinations. Wording incorrectly made Jency a co-lead. Shiks led Pooja and Jency. |
| Practice runs | No | Answered 12. A full-group judge retrieved the owner’s “at least 2 rehearsals” and answered correctly. |

**Hybrid retrieval met the complete evidence criterion for 5/8 positives**, against 2/8 initially. These are evidence scores. Six separately scoped local-judge runs (two bound authors and four complete group/date scopes) retained all reference evidence on five cases. Even with all 99 Namma Team rows in scope and the field update retained, the final writer denied there was evidence of anyone working away. The full Royal Enfield scope was 121 rows. These costlier passes were explicit benchmark controls above the proposed automatic budget.

A direct CLI literal control for the owner’s original word “field”, using the resolved group and week, returned exactly the correct source row. Even then the stock writer mentioned only the Pune team and confused “today” in the historical message with the query date. See private `literal-controls.json` for both the field and duration commands, evidence and wording guard output. This isolates a reader failure from a search failure.

## Candidate core extensions

1. Resolve a group or sender to a stable local ID, show the binding and distinguish an unknown entity from zero matching records. Benchmark automatic slot extraction separately from the assisted bindings used here.
2. Preserve reply-parent references and let existing list/get results expose the source link, sender, posted date and related messages. Offer chronological context for resources with a natural order only after testing another resource. The 12-row DICE control is the argument for preserving explicit relationships.
3. Evaluate mixed lexical and semantic candidate retrieval behind existing search. Preserve matched records and structural evidence through judging. Measure evidence recall, factual wording, incomplete coverage, latency and abstention separately on fresh questions.
4. Show a short source excerpt alongside high-risk answers about numbers, lists or commitments. A private screenshot is an optional user-controlled receipt. This benchmark did not test model-selected captures or Signal delivery.

## Replay and evidence access

Private frozen input and outputs are on the owner’s DGX at `~/.local/share/silo-owner-pilot/windows-xTcFis`. `fresh.json` supplies source records and relations, `sandbox/` holds the imported views, and `stock/log.jsonl` contains the shell audit. `result-*.json` captures all initial packets and actual wording. `rewrite-*.json` and `scope-*.json` preserve later retrieval traces and citations. `shots.json` maps four receipts to exact message refs; the PNGs remain private under `shots/`.

To repeat, create a private directory and copy only `fresh.json` and `sandbox/` from that frozen run. With Idli’s local 9B on 8291 and embedder on 8293, run from the repository root:

```sh
suite=benchmarks/runs/2026-11-23-whatsapp-windows
OPENBLAS_NUM_THREADS=1 core/.venv/bin/python "$suite/trial.py" "$trial"
```

Here `trial` is the private directory. The harness validates the snapshot checksum, caches local vectors and skips completed case files. The [screenshot helper](screenshot.py) needs system Python with Playwright, a linked profile, Chromium, and the pinned WA-JS archive. Pass the source snapshot, private manifest, and a private output folder. It launches a disposable copy, loads the client, switches offline before navigating to any group, verifies the group header and message ID, and captures only the matching row. We visually inspected all four PNGs. No chat images went to a model.
