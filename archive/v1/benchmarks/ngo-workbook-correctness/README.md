# NGO workbook correctness

**Question:** given an NGO finance workbook, does the model return the right
numbers and names?

**Case:** `cases/asha_ngo_finances_FY25-26.xlsx` is a synthetic workbook (sha256
`4e58a724…a15741`) with sheets Transactions (314 rows), Budget vs Actual and Funding.
It is clean: one table per sheet, headers in row 1, and no total rows.

**Oracle:** `truth()` in `tg-bridge/eval_direct.py` computes 11 answers from the raw
cells: total spend, admin spend, program ratio, July spend, USAID-funded spend,
Bihar MCH spend, count of transactions over ₹1 lakh, the top Education expense type,
the most over-budget program, the largest funding gap, and beneficiaries reached.
Pass means within 1%, or an exact name match.

**Protocol:** one question per call, and the reply must end with `ANSWER: <value>`.
- *Direct:* the whole workbook as text in the prompt.
- *Harness* (`+h`): an 8-row preview, plus the `python` tool from `tg-bridge/harness.py`.

```sh
cd tg-bridge
PAR=2 .venv/bin/python eval_direct.py <xlsx> idli+h,qwen+h,deepseek 3
```

| run | setup | score |
|---|---|---|
| 2026-10-11-direct-openrouter | Muse (OpenRouter) / Qwen 9B / DeepSeek, direct | 32/33, 23/33, 33/33 |
| 2026-10-11-harness-qwen | Qwen 9B + harness | 9/11 |
| 2026-10-11-harness-local-q8 | local Muse Q8 + harness | 11/11 |
| 2026-10-11-harness-local-q8-drafter | local Q8 + drafter + harness, 8-step limit | 18/22 (4 hit the step limit) |
| 2026-10-11-quant-drafter-sweep | Q8+d, Q4, Q4+d, Q6+d, 12-step limit and forced answer | 22/22 each |
| 2026-10-11-codex-local-probe | stock `codex exec` + local Muse Q4+d, total spend only | 1/1, 16 shell commands, 111 s |

**Limits:** one workbook, which is synthetic and clean, and a small number of trials.
This shows the harness works on tidy data. It does not show the harness copes with
real spreadsheets.
