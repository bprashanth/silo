# Direct calls vs a python-tool harness

Question: can the model answer data questions with the whole workbook pasted
into the prompt, or does it need to compute with a tool?

`tg-bridge/eval_direct.py` computes 11 answers from the workbook (totals,
filters, counts, rankings, a ratio) and asks one question per call. Pass means
within 1%, or an exact name. Evidence: `benchmarks/ngo-workbook-correctness/`.

Direct, workbook as text (38k chars), 3 trials:

- Muse Glimmer (OpenRouter): 32/33. Correct, but spends tens of thousands of
  reasoning tokens adding rows by hand.
- Qwen3.5 9B: 23/33. Wrong sums, and once ran out of tokens.
- DeepSeek V4.1 Flash: 33/33.

The harness (`tg-bridge/harness.py`): the model sees an 8-row preview of each sheet
and has one `python` tool that runs in a no-network Docker container with the
user's files mounted read-only at `/data`.

- Local Muse Q8: 11/11.
- Qwen 9B: 9/11. Both misses gave no answer; every number it did give was exact.
- Local Muse Q8 with drafter, 2 trials: 18/22. All 4 misses hit the 8-step tool limit while
  re-checking. Raised the limit to 12 and added a final no-tools call that forces
  an answer. Every later run is 22/22.

The harness is now what the bot uses for every message. Tool steps are not kept
in chat history.
