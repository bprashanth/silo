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
