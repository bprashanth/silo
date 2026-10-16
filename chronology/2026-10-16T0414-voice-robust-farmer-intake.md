# Robust voice intake for farmers on bad lines

The livestock POC kept mis-hearing callers. The cause is the model it picked for speed: Whisper base.en on the CPU,
greedy decoding. I worked in an isolated worktree, `../silo-voice` on branch `poc/voice-robust`
(`benchmarks/voice-robust/`, server on :8775). Codex's checkout, :8765/:8766 and the Telegram bot were untouched.

**Recognition.** I built a degraded corpus: 60 real Indian-English utterances from EdACC, plus 44 synthetic farmer
lines. Each was run under 4 line conditions (clean, GSM 2G, 6 kbps Opus with loss, and noisy yard + quiet mic + 2G),
plus noise-only clips. On the worst condition:

| engine | WER | key farmer words | per utterance |
|---|---|---|---|
| base.en (POC) | 50.7% | 57% | 376 ms |
| **Parakeet-TDT v3 + NeMo phrase boosting, GPU** | **24.8%** | **90%** | **52 ms**, no words invented on noise |

Whisper large-v3/turbo, Canary-1B/Qwen, Voxtral, an India-tuned Whisper, and hosted Gemini 3.5/3.8 and Qwen-Omni were
all worse, slower, or invented words on noise. The production Telegram Whisper (large-v3-turbo on CPU) takes 4.8 s per
utterance and hallucinated on 6/6 noise clips.

**Correction.** Rewriting the transcript with an LLM was harmful: "not getting up" became "not eating", and "blood"
became "bloat". It is kept only as evidence. Names and places are snapped to a gazetteer by sound and read back.

**Conversation.** Code owns the slot order and caps each question at two tries, and a backstop stops any question
being asked a third time in a row. Muse returns grammar-constrained JSON with guards, a 3.5 s deadline and a rule
fallback. Cached acks and fillers cover the gaps, and there is barge-in, fragment merging and digit-group patience.
Across 10 simulated calls (real time, 2G line):

| interpreter | completed and confirmed | checks | first sound p50 | reply p50 |
|---|---|---|---|---|
| local Muse | 10/10 | 119/130 | 0.35 s | 1.95 s |
| DeepSeek (text) | 10/10 | 120/130 | 0.35 s | 1.93 s |
| Gemini Flash-Lite hearing the audio | 10/10 | 127/130 (place names) | 0.35 s | 3.45 s |

Real Chromium WebRTC calls: 8/8 fields plain, 7/8 on the simulated 2G line, 8/8 with interruptions. Testing found and
fixed lost speech on weak lines (AGC before the VAD), duplicated merged audio, 11-digit numbers, a phone-confirmation
loop, and LLM-invented urgency. Policy tests: 19, including a 2,000-caller fuzz test across 6 seeds.

**Limits.** The farmer speech in the dialogue tests is synthetic, and Kokoro mispronounces Kannada names. There are no
human 2G calls. The Svarah, Indic Parler-TTS and IndicConformer downloads are still gated on HuggingFace access.

Evidence: [README](../benchmarks/voice-robust/README.md), [ASR runs](../benchmarks/voice-robust/runs/2026-10-16-asr/),
[simulated calls](../benchmarks/voice-robust/runs/2026-10-16-sim/), [browser calls](../benchmarks/voice-robust/runs/2026-10-16-browser/).
Audio, corpus and screenshots are under `/mnt/seagate/silo/voice-robust/`.
