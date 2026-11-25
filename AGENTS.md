# Working in Silo

Read the owner’s [CLI principles](docs/cli.md) and [design decisions](docs/decisions.md) before changing the command surface.

| When the change is about… | Put it here |
|---|---|
| A reusable operation on sandbox records | `core/`. Prefer an existing verb, resource and flags. Document the contract with an example in [cli.agent.md](docs/cli.agent.md) and keep `core/idli help` accurate. |
| A repeatable chain of operations | `proposals/workflows/`. Describe the inputs, existing commands, output and any trigger. A digest is one example. |
| An outcome to try with users | `proposals/pilots/`. Define the cases, reference data, expected outcomes and promotion decision. Implement the benchmark in `benchmarks/` first. Use its evidence to decide what graduates to product code. |
| Connecting a channel or operating a release | Transport code lives in `bridges/`. Rollout, access, verification and rollback belong under `deployment/{alpha,beta,ga}/` for the applicable stage. |
| Something awaiting the owner’s decision | Add one linked entry to [the review queue](todos/owner-review.md). Keep the detail in its home above. |

The owner maintains the human design notes from Dune. For any human-managed document, write agent updates in a tracked sibling named `<name>.agent.md`. Link to the original and describe implementation status or differences. Apply this convention throughout the repo. Update an existing agent-owned proposal, rollout guide or benchmark in place.

A core addition should solve a repeated operation across workflows, fit `idli VERB RESOURCE [REF] [flags]`, and have a testable contract. Use deterministic code for exact filters, dates and counts, and a confirmed definition and judge for uncertain meaning. Keep model-selected plans bounded. A schedule, chat shortcut or particular report is a workflow decision.

## Recording work

- Append a file in `chronology/` at a meaningful checkpoint in the conversation. Use `YYYY-MM-DDTHHMM-topic.md` in IST. Capture what the user wanted, what we tried, why we changed direction, what we observed and what remains open. A few exchanges can share one entry. Include searchable names such as the model or pilot and link to the run. Record later corrections in a new entry.
- Keep the actual experiment in `benchmarks/`. Reuse the bank, runner and rubric. For a run worth citing, keep a dated run note with the code revision, model/configuration, fixture or snapshot, command, result and limitations. Give a location and access instructions for private inputs and raw outputs. Keep customer records and credentials out of Git.
- Write a short piece in `narrative/` when several entries answer a question a human cares about. Explain what changed, what the evidence supports and what remains uncertain. Link to dated notes and benchmark evidence so the owner can use it to write the maintained docs. One piece can cover several runs.
- To answer “what did we learn about Muse three weeks ago?”, search the dated chronology for Muse around that date, follow its run reference for the exact setup and results, then check for later corrections. The [Muse field note](narrative/muse-harness.md) illustrates the route, including the archived v1 benchmark.
