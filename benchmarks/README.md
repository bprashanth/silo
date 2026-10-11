# Benchmarks

Each benchmark is a directory with a README (question, protocol, how to run),
`cases/` (inputs and how ground truth is computed), and `runs/<date>-<slug>/`
with the raw output of each run. A number reported in chronology or narrative
must point to a run here. Model weights and caches are never checked in.

| benchmark | question |
|---|---|
| [ngo-workbook-correctness](ngo-workbook-correctness/) | Does a model answer spreadsheet questions correctly, called directly or through a harness? |
| [decode-speed](decode-speed/) | How fast does local Muse decode under each quant and drafter setting? |
| [harness-compare](harness-compare/) | On messy NGO spreadsheets, is the bridge's harness or io's Codex more correct and auditable, and which receipt catches wrong answers? |
