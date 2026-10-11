# Local Muse, a model menu, and charts

Downloaded to `/mnt/seagate/models/Muse-Glimmer-30B-GGUF/`: the Unsloth
`UD-Q8_K_XL` quant (32 GB, the highest available) and the BF16 vision
projector. Served by llama.cpp (`ghcr.io/ggml-org/llama.cpp:server-cuda13`,
container `idli-muse`) on `127.0.0.1:8181` with
`--jinja --reasoning-format deepseek -fa on -np 2 -c 131072`. Port 8080 is taken by searxng.

`/model` switches per chat between:

| key | model | label |
|---|---|---|
| qwen | qwen/qwen3.5-9b on OpenRouter | external |
| idli (default) | local Muse Glimmer 30B | idli internal |
| deepseek | deepseek/deepseek-v4.1-flash on OpenRouter | external |

Charts: the model writes a ```` ```chart ```` JSON block (kpi, bar, barh, line,
stacked_bar, pie, donut panels) and `charts.py` renders it with matplotlib. No
model-written code runs for charts. Test workbook: a synthetic NGO ledger,
`asha_ngo_finances_FY25-26.xlsx` (Transactions 314 rows, Budget vs Actual,
Funding). A dashboard request through Telegram rendered correctly; one budget
label ("Organisation-wide") did not match its row and is still open.
