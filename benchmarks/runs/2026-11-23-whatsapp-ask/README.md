# Can the normal ask mapper deliver the WhatsApp source?

Every turn launched `core/idli ask --new --mapper nine_compressed --judge nine_compressed QUESTION` in a subprocess. Both models and the embedder ran locally. Hosted chips were disabled. The question was the only task-specific input to the CLI. No command, group, author, date, evidence ID or expected answer was supplied to the mapper by the grader.

## Fixture and comparison

The [linked WhatsApp capture](../2026-11-23-whatsapp-windows/README.md) holds 2,783 actual posts across 26 active groups. Twenty positive questions cover eight prior cases and twelve new questions drawn from other observed messages, including group sign-off, vendor setup, registration, partner introductions and a seed discussion. Four controls test an exact count, unknown group, ambiguous sender and missing history. New cases are source-derived development cases, chosen before the run; the benchmark was not independently blinded. The Google sources in this fixture are empty.

- **Stock** uses the ordinary snapshot views and mapper menu.
- **Hybrid** uses the same unmodified CLI. Before each ask the harness prepares a saved view of matches for the actual question in the private benchmark store. It detects group-name overlap without case annotations, and merges inverse-frequency token overlap, message vectors and burst vectors by reciprocal rank. The top twelve anchors are followed by their captured parents and nearby messages. The mapper sees an ordinary named view with columns and a description. It can query it, modify its filters, or use another source.
- **Guided** exposes the same rows and adds measured source counts, the actual group binding when unique, and an example command to the view description. This arm was introduced after inspecting the first hybrid traces. It measures menu presentation on this development bank.

- **Preview** adds the eight highest-ranked source references with local, 100-character message excerpts to the guided menu. The mapper still chooses its own commands. A preview shown only to the mapper earns zero retrieval credit. This diagnostic was added after early traces showed the mapper repeatedly applying counterproductive filters.

The store is prepared serially per arm and is dedicated to one tester. The candidate view is a benchmark fixture, unsuitable as shared persistent per-question state in a concurrent service. The runner reuses embeddings of the exact frozen snapshot. Every message keeps its source ref. Screenshots from the prior run are available as private receipts. No screenshot selection or summary quality is graded.

## Scoring and replay

The primary measure is **all required source records returned in the tool evidence recorded by ask** (`steps_shown`). A source is detected by its stable ref or a verbatim body prefix of up to 70 characters (minimum body length 28). A command returning only a derived value or a different excerpt can therefore fail this metric. Candidate recall is reported separately, before mapper selection, additional filters, row limits and display truncation. A packet match on its own earns zero end-to-end credit. Controls are inspected separately. The repeat runs the twelve new cases again in reverse order, each as a fresh ask.

The private bank, frozen receipts, per-case command traces and stores reside under `~/.local/share/silo-owner-pilot/ask-LMunvw` on the owner’s DGX. They were never added to Git. Local benchmark copies can also go under the ignored `benchmarks/private/`. The source snapshot and vectors are in the owner’s `windows-xTcFis` directory. For a replay on this machine:

```sh
umask 077
fixture=~/.local/share/silo-owner-pilot/windows-xTcFis
suite=benchmarks/runs/2026-11-23-whatsapp-ask
trial=$(mktemp -d)
cp ~/.local/share/silo-owner-pilot/ask-LMunvw/bank.json "$trial/"
for arm in base hybrid guided preview; do
  cp -r "$fixture/sandbox" "$trial/$arm"
  OPENBLAS_NUM_THREADS=1 core/.venv/bin/python "$suite/run.py" "$fixture" "$trial" "$arm"
done
core/.venv/bin/python "$suite/score.py" "$trial"
```
