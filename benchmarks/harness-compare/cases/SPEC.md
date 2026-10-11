# Case spec: messy NGO workbooks

Build a set of benchmark cases that look like real NGO spreadsheets, not tidy
exports. Each case tests whether an agent with a Python tool gets the right
numbers out of a messy file.

## Layout (one directory per case)

```
cases/<case_id>/
  gen.py        deterministic generator (fixed random seed). Writes files/ and case.json.
  files/        the workbook(s) the agent will receive (xlsx, csv)
  case.json     {"id", "description", "files": [names], "questions": [...]}
  verify.py     recomputes every answer by parsing files/ independently of gen.py
```

Each question in `case.json` looks like this:

```json
{"id": "q1", "question": "plain-English question as a programme manager would ask it",
 "answer": 123456 or "Exact Name", "kind": "number" | "name", "tol_pct": 1.0,
 "trap": "one line: the mistake a naive reader makes (e.g. sums the subtotal rows too)"}
```

Rules:

- Compute the truth in `gen.py` from the clean underlying records **before** making them
  messy. Never compute it by reading the messy file back.
- `verify.py` must parse the messy files carefully and reproduce every answer.
  It exits non-zero on any mismatch. Two independent derivations must agree.
- Questions must have exactly one defensible answer. If there is a convention
  (dedupe by Visit ID, treat village names case-insensitively, ignore spaces), say it
  in the question.
- Each case has 5 or 6 questions: at least one total, one filter plus sum, one count,
  one ranking that returns a name, and one ratio or percentage.
- Use realistic Indian NGO content: programmes, districts and states, donors (CSR
  trusts, government schemes, foreign grants), INR amounts with lakhs and crores.
- Use only Python 3 with openpyxl, pandas and numpy. Run with
  `/home/beeps/src/github.com/bprashanth/musings/tg-bridge/.venv/bin/python`.
- Keep each file under 2 MB.

## Cases

1. `subtotals`: a monthly expense ledger with a "Total – Apr 2025" style subtotal row
   after each month, blank separator rows, and a grand total row at the bottom.
   The trap is double counting.
2. `offset_headers`: 3 title or notes rows (organisation name, "Prepared by", date),
   then a two-level merged header (quarter cells merged over their month columns),
   with data starting around row 6. The layout is wide: programmes × months.
3. `two_tables`: one sheet with a budget table at the top, 3 blank rows, a small
   heading, then a donor-receipts table with different columns. A second sheet holds notes.
4. `formulas_no_cache`: written by openpyxl with live formulas (=C2*D2 line totals,
   =SUM subtotals) and no cached values. Reading with data_only=True returns None for
   those cells, so the agent must compute from the inputs.
5. `mixed_units`: an amount column holding numbers, strings like "₹1,20,000", "1.2 L",
   "2.5 lakh", "1 Cr", "45k", and blanks, "-" or "NA" (which count as zero). Dates mix
   2025-04-03, 03/04/2025 (DD/MM) and "3 Apr 2025". State these conventions in a note
   row or the question.
6. `big_ledger`: about 20,000 transaction rows across 2 sheets (field expenses and a
   salary register), plus a lookup sheet that maps cost-centre codes to programmes.
   Questions need a join.
7. `field_log`: a beneficiary visit log entered by field staff. Village names have
   inconsistent case and spacing, and the same Visit ID is entered twice in places.
   Questions state the normalisation and dedupe rule.
8. `multi_file`: `beneficiaries.csv` plus `payments.xlsx`, joined on beneficiary ID.
   Some payments have IDs not in the CSV; the question says to exclude them.

When done, run every `gen.py` and then every `verify.py`, and print one summary line
per case. Write `cases/README.md` listing each case and its questions.
