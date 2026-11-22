# Searching Jam Buns from the CLI

**Question.** Can the existing CLI recover a remembered link or reconstruct a meeting proposal from a group conversation? Silo core revision `50a8d84`. Two fresh, read-only Jam Buns captures on 22 November 2026 each returned 167 texts from the linked WhatsApp Web session. The second included available cached titles, descriptions and canonical URLs for link posts. Five messages had HTTP(S) links and three had preview text. The collector stayed offline during reads and never opened a destination. The inputs, private case wording and full shell transcripts are on the DGX under `~/.local/share/silo-owner-pilot/search-ZnuqbZKj`.

## What Drive already supplies

The ordinary WhatsApp sandbox is the same DuckDB record store used by the CLI. Its two named views support SQL, literal terms and quoted phrases. Drive additionally ranks phrases and words apart, embeds passages, scores them with cosine similarity, thresholds weak semantic matches and merges literal and semantic rankings. The implementation selects this path for files. Adding a WhatsApp view does not give it vectors or a default date column. The io search trial also distinguishes finding evidence, explaining it, and assigning reusable labels. [io search trial](https://github.com/bprashanth/io/blob/main/chronology/2026-11-21T0000-search-defaults-agent-trial.md) · [Core implementation](../../../core/lib/recstore.py)

We compared the ordinary CLI with two benchmark-only projections through the **actual Drive code path**. Each source ref became either a single passage or a passage with up to two neighboring messages on each side, within ten minutes on the same day. Both included available textual link previews. We used the existing embedder on DGX loopback, Drive thresholds and rank fusion, without generated document cards. The projections have separate private databases. Core production behavior and the original message records are unchanged.

## Findings

| Case | Evidence |
|---|---|
| Young birders month / young borders month | Neither spelling, nor the quoted birders phrase, yielded a supported candidate. None of the five link bodies or three cached previews contained young, bird, month or border. The two links without previews, older history and media remain unresolved. |
| Find a known shared link | We generated three private development questions, one from each actual preview with its source URL as the reference. Ordinary `ask` returned 0/3 exact URLs. For distinctive keyword searches the plain message view found 1/3 source refs and preview-enriched Drive retrieval ranked 3/3 first. For paraphrases the message view found 0/3 and enriched retrieval ranked 2/3 first. These are source-derived development cases, not an independent accuracy estimate. Enrichment and ranking both changed. |
| CC meeting, as asked on November 10 | We excluded messages after noon November 10 and fixed the CLI's date helper to that instant in IST. “Last week” resolved to November 2–8. On November 6 the same sender asked about a CC meeting and proposed two people in a separate message that minute. The shell used mail. A real direct sender-prefix and date lookup in the group found the proposal and independently matched the source capture. A second lookup returned the sender's actual URL that day. The source alone does not establish that URL's purpose. |
| Retrieve the discussion by meaning | For “who should be included in the CC meeting”, single-message fusion returned zero results. Windowed fusion returned three overlapping hits; together they included both source messages. “Who should attend the meeting” returned zero even with windows. A literal search for “CC meeting” found the scheduling message; a search for “include” found the proposal. |
| Decide who to invite | Given the retrieved window, the local 9B cited the proposal but listed five people, included just one of the two proposed names and called the list confirmed. With only the relevant message it quoted the text exactly and marked status unclear. Returning the speaker, timestamp and exact proposal is supported. Turning nearby names into a final roster needs separate evidence. |
| Resolve a person | Within this group and week, the supplied prefix matched one sender; the misspelling control matched zero. The ordinary CLI searched Calendar on the unknown-person case and did not clarify. Search for candidates within scope; ask which person when there is no unique match. |
| Register a dated message resource | A process-local registration made `--on 'last week'` work directly. The explicit group question then used WhatsApp, but still missed the pair. The less explicit question still went elsewhere. Exposing the resource helps filters; source selection and interpretation require their own tests. |

The private file `meeting-receipt.txt` contains the timestamp, speaker, message ref, verbatim suggestion and the separate November 6 link. It stays outside Git. Treat the question “what did Rinj propose?” as retrieval. “Who should we ultimately invite?” requires the later decision or a clarification. A view becomes useful for a recurring selection, and a judgement for a user-defined category applied repeatedly.

## Shell chips and remote privacy

We ran ten dated or current shell turns using the existing CLI entry point, with Qwen 3.5 9B for mapping and wording. The repeated meeting question displayed the struggled chip and suggested remote. The first attempt searched the wrong source without displaying a struggle. Chips are execution signals.

Clef received only the generic link-count question. It returned probabilities with a top score below the display threshold, so the shell withheld a kind chip. Repeating the question produced the struggled chip and remote offer. The stock classifier receives the raw question independently of mapper masking. Row judging with hosted Clef also sends the selected content; it was unnecessary here. The named questions used local models with hosted classification disabled.

Using the actual remote mapper input, a loopback privacy scanner, and intercepted remote dispatch, the known email and phone canaries were hidden and rehydrated correctly. In the unseeded conversation probe the nickname, group title, sender, shared URL and full proposal sentence remained visible. The ordinary masking path is insufficient for this private history.

We exercised two **fresh** live remote turns. Each outbound payload had to match an inspected schema-only reference constructed from an empty control store, and the check was repeated at the HTTP boundary. A changed follow-up could not leave. The generic control returned five link-bearing messages; the local shell had counted all 167. The ordinary named request failed preflight. In a separate diagnostic vault, two verified literals were seeded as reversible codes. The guarded first-turn request passed and rehydrated the aliases, but the remote plan still selected Gmail. This validates those two exact outbound requests. History, repair prompts and arbitrary future questions require independent protection. None of the inspected chat excerpts went to hosted Clef or the remote mapper.

## Reproduce

The [case bank](cases.json) contains the reusable shell questions. Raw results and the three source-derived preview questions require the owner's private run. From the repo root, set `run` to a new private directory and use the [group capture instructions](../2026-11-22-whatsapp-groups/README.md#replay) twice, in single-group mode: write `live.json`, then `previews.json` with `--link-metadata`. Keep the linked profile idle during capture. The following commands create fresh sandboxes and the historical cutoff. Set the umask before writing logs.

```sh
umask 077
d=benchmarks/runs/2026-11-22-whatsapp-search
py=core/.venv/bin/python
"$py" benchmarks/runs/2026-11-22-whatsapp-groups/import_snapshot.py "$run/live.json" "$run/sandbox"
"$py" "$d/shell_trials.py" "$run" > "$run/shell.log"
"$py" "$d/search_trials.py" "$run" > "$run/retrieval.log"
"$py" "$d/receipt.py" "$run" > "$run/receipt.log"
"$py" "$d/preview_trials.py" "$run" > "$run/preview.log"
"$py" "$d/resource_trial.py" "$run" > "$run/resource.log"
```

To replay the three private preview questions verbatim, pass the previously saved `private-preview-bank.json` as the second argument to `preview_trials.py`. The separate `remote_probe.py "$run"` performs the local masking audit and the allowlisted hosted calls only when the preceding shell output actually offered escalation. It requires the DGX loopback scanner at 8899, the local models and an authorized remote API key.

For an owner check on the frozen evidence, from the repo root:

```sh
export IDLI_SANDBOX="$HOME/.local/share/silo-owner-pilot/search-ZnuqbZKj/nov10"
core/idli list wa_messages --where "sender ILIKE '%rinj%' AND sent_at >= '2026-11-02' AND sent_at < '2026-11-09'" \
  --search include --fields sent_at,sender,body,ref
```

### Routing cues and native search

On a fresh copy of the November 10 store, we varied the prefix on the same meeting question, starting a new shell conversation each time with local mapping and judging. With no cue the mapper chose mail. “Search my chats”, “In my Jam Buns group”, and both cues together each selected wa_messages. None returned either proposed name. This is one controlled example of routing improving independently of retrieval accuracy.

We also tested the linked browser's local `msgFindSearch` through pinned WA-JS, using an explicit group ID and the same offline read path. All seven terms returned zero and end-of-results, including the known positives “meeting” and “include”. The negative birders result from this interface is inconclusive. To replay, pass `--native-search` and a fresh output path to the group snapshot script.
