# Livestock browser POC ready for user testing

Working page is http://127.0.0.1:8765, opened in a visible Chromium window on the demo desktop. Pipecat is selected by default; Call requests the real microphone. OpenRouter uses synthetic-only externally hosted speech. Dograh opens its native tab and supports post-call transcript/schema import.

Three final local calls completed with 10/10 expected fields each. Fifteen browser received-audio samples: p50 **1671 ms**, p90 **2203.6 ms**, p95 **2239.8 ms**. Three hosted calls completed: p50 **2541 ms**, p90 **3601.6 ms**, p95 **3675.8 ms** across 15 samples. Observed hosted costs averaged **$0.0035062 per call**. Local summary/completion are controlled from collected facts, not free-form Muse; two of each five turns use this guard.

Native Dograh genuinely handled multi-turn speech and its audio was recorded, but the full intake automation did not achieve confirmation. Do not treat native deployment as full acceptance. Native transcript omissions on interrupted speech and name recognition errors remain documented.

Final local interruption retest: approximately **167 ms** to audio stop, **1624 ms** to subsequent reply; queued greeting is visibly labelled interrupted. These are synthetic waveform/browser RMS observations, not human microphone or physical speaker measurements. All 15 focused regression tests pass, including unknown/corrected facts, negations, pending speech retention, confirmation and idempotent completion persistence.

Final server restart activated persistence and transcript annotation fixes; actual-audio retest passed afterward. No production Telegram services changed. Model/dependency/audio/screenshot artifacts stay on Seagate except Docker's existing NVMe storage and private live state. Local branch is `poc/livestock-voice`; no push.

[Results and limitations](../benchmarks/livestock-voice/RESULTS.md), [setup](../benchmarks/livestock-voice/README.md), [small synthetic records](../benchmarks/livestock-voice/runs/2026-10-15-browser/). Large raw evidence is under `/mnt/seagate/silo/livestock-voice/runs/`.
