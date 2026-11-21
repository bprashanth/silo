# What came from io, and where the evidence is

The core was built and measured in the io repo (`~/src/github.com/bprashanth/io`, branch `oss-desktop-eval`) on
2026-11-19 to 21, then copied here. io stays the lab: its benchmarks, chronology and the app (Paseo, Drivey, the
old Minis) stay there.

## Code

`core/lib/` is io's `benchmarks/runs/2026-11-06-oss-desktop-independent/cowork/lib/` cut down to what the core
loads: `idlicli`, `recstore`, `privacy` and `privacy_engine/`, `docmask`, `home`, `minisql`, `google_api`,
`stackwall`, `muse`, `filekit`, `minimap`. Some of these still carry app code the core never calls (`home`,
`stackwall`); trim them when they get in the way.

## Evidence (in io, `benchmarks/runs/`)

| Folder | What it showed |
|---|---|
| `2026-11-19-record-store/` | the first blind bench of the scaffold; the task banks and the grader |
| `2026-11-20-judge-models/` | what the judge sees matters most; Clef best value |
| `2026-11-21-agent-trial/` | an agent asking like the owner; 20+ fixes |
| `2026-11-21-heldout-rerun/` | frozen held-out: 9B 5 -> 10 correct, idli-remote 13 -> 13 |
| `2026-11-21-kind-classifier/` | Clef labels the kind of ask; 70% agree, workflow chips 10 of 13 |
| `2026-11-21-menu-regression/` | the smaller menu: not proven safe, so opt-in |

The turn-by-turn results hold real test-account rows and are kept on the DGX, not in git.

## History

io's `chronology/2026-11-20T1400-scaffold-hands-on.md` and `chronology/2026-11-21T0000-search-defaults-agent-trial.md`
record every step; io's `todos/idli-insights/p1/scaffold_core_round1.md` has the full bug list with evidence.
