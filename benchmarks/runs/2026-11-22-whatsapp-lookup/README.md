# Can the current CLI find a fact in a WhatsApp conversation?

Seven independent questions on Silo `49aa3c7`, 22 November 2026. Five came from the owner. Two controls reuse a phone-verified caption and a count with an exact answer. We froze the [questions and acceptance criteria](cases.json) before inspecting this capture. This is a diagnostic development set, with one trial per configuration and manual grading.

The linked DGX WhatsApp Web cache supplied 2,783 text or image-caption rows from 26 groups active in the preceding calendar month. No group read failed or reached the 2,000-record cap. Jam Buns supplied 172 rows, starting 28 October at 20:37 IST. Those limits describe this cache. Group membership history, personal chats, downloaded media, and a populated Google account were outside the experiment. Natural questions without a channel cue really can refer to Calendar or Drive. Here we tested whether an answer present in WhatsApp was recovered.

## Answers against the source

| Case | Evidence checked in the cache | Stock 9B | Short menu, same 9B | Redacted remote |
|---|---|---|---|---|
| Abhi’s DICE doc | On Nov 20 his 13:12 decline quotes the DICE post. At 13:13 the same sender shares a Google Docs link. The second post is adjacent, with no verified reply edge tying the document itself to DICE. | Files, no hit | Same | Mail and files, no hit |
| Website V mentioned | On Nov 18 Vidya mentions Rainmatter, then posts the bare domain in the next message. Four distinct sender labels start with V across the capture. Asking which V or which group would meet the rubric. | Document summary, no hit | Same | Mail and files, no clarification |
| CC futures call time | On Nov 19 the group discusses the following day. 11am and 1pm appear first. The last timing suggestion in that exchange is “2:30/3” phrased as a question. An agreed time is unverified. | Empty Calendar | **Wrong time.** Returned the opening message and called its posting time the meeting time. | Empty Calendar |
| Calls to arrange last week | Nov 9–15 is the preceding calendar week. The owner’s Nov 11 list mentions IndusInd FO with a spelling variant, CC and DICE. That verifies a relevant list, without claiming exhaustive coverage. | Correct date range, empty Calendar | Calendar query failed, then asked which week or type of call | Mail, no hit |
| Vidya’s Insight Out list | A Nov 6 message has multiple headings. The requested people are in one section. The sender and the posted list matter here. | Searched Sheets | Looked for senders of a group with that name | Mail and files |
| Young Birders’ Month signup | The Nov 2 image caption contains the signup domain and a distinct WhatsApp channel URL. | Empty WhatsApp search | Empty WhatsApp search | Empty WhatsApp search |
| Messages with links | Six Jam Buns rows contain HTTP(S) links. A row with several URLs counts once. | 0 | 111 | 0 |

**Zero complete answers in each arm.** The short menu increased use of WhatsApp from two to four questions. Its additional retrieval exposed a confidently wrong answer. On the count, all three assumed the informal name was the exact group title. Stock also omitted the link condition. The short menu emitted an unparenthesised OR that admitted rows from other groups.

## What the shell and Clef actually did

The stock mapper sees both saved views, their purpose and their columns. The WhatsApp message view exposes reference, group name, timestamp, sender, body and links. It has no reply-parent field or directory of group aliases. The short arm kept the existing views and date lines, leaving the system grammar intact. Median first logged user-prompt lengths were 3,062 characters stock, 587 short and 3,050 remote. Menu size alone did not rescue these tasks. The upstream menu study also found that showing fewer columns could cost answers. [io menu experiment](https://github.com/bprashanth/io/tree/main/benchmarks/runs/2026-11-21-menu-regression)

Clef labelled all 21 pseudonymised questions **lookup**. No plan ran a row judge or established a pending clarification. The shell suggested remote for stock calls and roster, and short-menu calls and caption. Struggle signalled command trouble. It missed the incorrect posting-time answer and both incorrect local counts. The short-menu request for a week came after a failed query. Neither mapper asked who V was.

In a separate [row-judge test](row_judge.py), we submitted four reviewed minimal projections of the real timing exchange to Clef. We hand-labelled them before running it. For the opening question without a time, initial concrete proposals, personal availability, and final concrete proposal, its probabilities for “proposes a time” were **0.02, 0.94, 0.21, 0.94**. All four labels matched. This small selected test supports trying Clef on retrieved candidates. It does not establish meeting confirmation or evaluate retrieval.

## What the 9B could answer with the evidence supplied

A [local control](context_control.py) used ordinary CLI queries to select three hand-located time windows and passed the resulting rows to the unchanged 9B answer writer. Given the two website posts it correctly named Vidya and returned the domain. Given the eight timing messages it attributed 2:30 or 3 PM to Vidya as a suggestion, although its “tomorrow” was relative to the historical exchange. Given the decline and next document post, its wording was rejected by the existing number guard. Reply-parent text was absent from those two rows. These windows use hindsight and receive no end-to-end credit.

## Search and privacy implications

With the ordinary CLI, a partial group-name filter plus literal search returned 15 rows for DICE, three for Rainmatter and one each for the opening call phrase, the roster heading, the Birders caption and the observed IndusInd spelling. The following command returned the verified count of six.

```sh
core/idli list wa_messages --where "group_name ~ 'Jam Buns' AND links <> ''" --count
```

The roster and caption already have usable anchors. Rainmatter needs the next message, and the link extractor only recognises HTTP(S). DICE needs a reply parent plus a nearby same-sender document link. The benchmark separately verified that the browser cache exposes the quoted parent in this case. The stock DuckDB projection drops it. The call needs time-ordered neighbouring messages and evidence of agreement. Semantic similarity previously recovered the birding paraphrase after including captions. It cannot by itself establish which proposal the group accepted. [Caption and semantic controls](../2026-11-22-whatsapp-search/README.md)

The remote arm used real hosted first-turn mapping with the stock menu and local rehydration. We pre-seeded typed tokens for known private slots in the questions, including V. The runner compared the outgoing mapper messages to a schema-only control before allowing dispatch. All seven first requests passed. Three later requests (doc, website, roster) fell outside the reviewed envelope and were withheld. Remote results on those cases cover only that constrained interaction. This experiment tested feasibility of masked mapping, without comparing private raw prompts or approving arbitrary transcripts. The earlier unseeded GLiNER test missed nicknames, group names and message content. [Privacy audit](../2026-11-22-whatsapp-search/README.md#shell-chips-and-remote-privacy)

The next comparison should hold out fresh questions and give the same 9B three ways to retrieve candidates: current search with resolved group/sender, semantic search, and either search followed by a bounded reply/chronological window. Grade source selection, evidence retrieval, and the final answer separately. Include an ambiguous initial and an unconfirmed meeting. A user-selected contact chip could bind a local sender identity before redaction. The suite did not test chip UX or prove it needs a new verb.

## Reproduction

The owner’s private artifact directory is `~/.local/share/silo-owner-pilot/lookup-bkoiNu/` on the benchmark machine. Maintainers with authorised access can replay against the frozen inputs. It contains `groups.json`, the separate group-local reply check in `relations.json`, `base/store.duckdb`, approved projections, and per-arm shell output, `turns.jsonl` and `log.jsonl`. The logs contain private source data. For capture and import use the [group benchmark](../2026-11-22-whatsapp-groups/README.md) with image captions; use the single-group capture with `--message-relations` for the independent reply check.

From the repo root, create a fresh private run directory, copy the frozen base and reviewed inputs, and use the existing local 9B and scanner tunnels on ports 8291 and 8899 and the configured OpenRouter credential. The runner creates fresh arm directories and refuses to reuse them.

```sh
umask 077
original=~/.local/share/silo-owner-pilot/lookup-bkoiNu
trial=$(mktemp -d)
cp -r "$original/base" "$original/groups.json" "$original/reviewed-projections.json" "$trial/"
suite=benchmarks/runs/2026-11-22-whatsapp-lookup
core/.venv/bin/python "$suite/run.py" "$trial"
core/.venv/bin/python "$suite/row_judge.py" "$trial"
core/.venv/bin/python "$suite/context_control.py" "$trial"
```
