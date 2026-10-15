# Robust voice intake for tired farmers on bad lines

**Question.** The first livestock voice POC (`../livestock-voice`, Codex) kept mis-hearing callers. What does it take for a voice
agent to hear a farmer reliably (gruff or tired voice, cheap mic, noisy yard, 2G call or weak data link) and still hold a
good conversation: one that never hangs, never forgets to ask the species, never loops, and handles interruptions? How far
can a fully local stack go, and what do hosted OpenRouter models add?

**Short answer.** Recognition was the main problem, and it was mostly the model choice. The POC used Whisper base.en on the
CPU, picked for latency. NVIDIA **Parakeet-TDT-0.6B v3 on the GPU, with domain phrase boosting**, cuts word errors on real
Indian-accented speech over a noisy 2G line from 51% to 25%, and lifts recall of the key farmer words (animal, numbers,
symptoms, names, places) from 57% to 90%. It takes about 50 ms per utterance (8× faster than the POC's base.en) and never
invented words on noise-only audio. No hosted model was better in a live loop. The best, Gemini 3.8 Flash, was as accurate
but took 4–10 s per utterance. The conversation is made robust by structure, not by a bigger model:

- Code decides what to ask, so the species can't be forgotten.
- Each question gets at most two tries, then it is marked *unclear* for a human, so nothing loops.
- The LLM only interprets each reply (local Muse, about 1.1 s).
- An instant prerecorded acknowledgement covers the thinking time ("Achha, okay." 0.35–0.45 s after the farmer stops),
  with a filler if needed ("One second, writing it down.").
- A deadline with a rule-based fallback means no turn can hang.

## Try it

```sh
benchmarks/voice-robust/start.sh          # :8775, isolated from the bot and from :8765; models load in ~40 s
open http://127.0.0.1:8775                # or http://100.82.28.38:8775 over the tailnet (needs the insecure-origin flag, see ../livestock-voice)
benchmarks/voice-robust/start.sh stop
```

Click **Call** and talk as a farmer. Tick **Simulate bad 2G line** to hear your own voice through a 300–3400 Hz, 8 kHz
μ-law link with bursty packet loss before the agent gets it. **Understanding** chooses who interprets replies: local
Muse (private), DeepSeek V4 Flash or Gemini 3.8 Flash on OpenRouter (text only), or Gemini Flash-Lite **hearing the
audio directly** (not private). Recognition (Parakeet) and the voice (Kokoro `hf_alpha`, Indian female) are always local.

## How it works

```
mic ─WebRTC/Opus─▶ [optional 2G line] ─▶ AGC ─▶ Silero VAD (0.25 s pause) ─▶ smart-turn v3 "finished?" (else ≤1.4 s)
   ─▶ Parakeet v3 + boosting (GPU, ~50 ms) ─▶ ack clip plays now ─▶ LLM interprets (JSON schema) ─▶ Intake policy
   ─▶ read-back + next question ─▶ Kokoro on GPU (~60 ms, cached) ─▶ WebRTC ─▶ speaker
```

| file | role |
|---|---|
| `intake.py` | The dialogue policy (pure, unit-tested). It defines the slot order (urgent calls jump to village and phone), two tries per question, read-back of names, places, numbers and phone, a correction heard the same way twice going to *unclear*, a single safety disclaimer for advice questions, hold/repeat handling, the summary, and a bounded confirmation. |
| `nlu.py` | One grammar-constrained LLM call per turn: intent plus only the facts stated. "Don't know" is believed only if the farmer said so. The answer to the question just asked gets a rule-based safety net. Names and places are snapped to the service-area gazetteer by sound (Double Metaphone plus spelling). On a 3.5 s deadline it falls back to rules. Backends: `muse`, `or:<model>`, and `audio:<model>` (direct speech). |
| `call.py` | Turn-taking: AGC, VAD, smart-turn, barge-in (0.35 s of speech over the agent stops it), merging a mid-sentence pause into one turn, echo rejection, acks/fillers, silence re-prompts (3, then a polite close), and per-turn audio evidence. |
| `speech.py` | Parakeet (ASR) and Kokoro on the GPU (TTS). Acks and fillers are synthesized at startup. A script guard handles v3 occasionally switching language. |
| `server.py`, `static/` | Pipecat 1.12 SmallWebRTC server and page: live transcript, fields with their state, and per-turn timings. |
| `sim.py` | Simulated callers in real time through the same `Call`. Ten scenarios: straightforward, minimal, all-at-once, correction, interruptions, urgent, unknown onset, hold + "what medicine?", hesitant + silent, and noisy/gruff + noise bursts. The farmer corrects wrong read-backs. |
| `asr_bench.py`, `asr_engines.py`, `build_corpus.py`, `degrade.py` | ASR bake-off on a degraded corpus. |
| `correct.py`, `correct_bench.py` | The rejected "LLM rewrites the transcript" approach, kept as evidence. |
| `tests/test_intake.py`, `tests/browser_call.py` | Policy guarantees, and a real Chromium → WebRTC call with injected audio. |

## The ASR bake-off

**Corpus** (`build_corpus.py`, audio on the Seagate, never committed):
- 60 real Indian-English conversational utterances from **EdACC** (Edinburgh International Accents of English, test
  split; Hindi-L1 and Indian English speakers).
- 30 synthetic farmer lines × Kokoro Indian voices, plus a pitched-down "gruff" variant (44 clips). Each line carries the
  key words an intake must get right.

**Conditions** (`degrade.py`), each applied to every clip:
- `clean`
- `gsm`: 2G call, 300–3400 Hz, GSM-FR 13 kbps
- `opus6k_loss`: 6 kbps narrowband Opus with 8% bursty frame loss
- `farm_phone`: −6 dB quiet mic, yard noise at 5 dB SNR, clipping, GSM, 5% loss, then −18 dB

Six noise-only clips check for hallucination.

Selected results. The full table of 20 configurations is in [runs/2026-10-16-asr](runs/2026-10-16-asr/README.md).

| engine | where | EdACC WER clean / **farm_phone** | farmer key words clean / **farm_phone** | p50 / utterance | words invented on noise |
|---|---|---|---|---|---|
| Whisper base.en (POC) | CPU | 19.6% / **50.7%** | 87% / **57%** | 376 ms | 1/6 |
| Whisper large-v3-turbo (Telegram bot) | CPU | 10.9% / 29.8% | 92% / 78% | **4.8 s** | **6/6** |
| Whisper large-v3 | GPU | 10.9% / 33.3% | 94% / 87% | 308 ms | 1/6 |
| Canary-1B-v2 | GPU | 9.8% / 30.1% | 91% / 76% | 170 ms | 0/6 |
| Canary-Qwen-2.5B | GPU | 7.7% / 32.2% | 92% / 80% | 407 ms | 4/6 |
| Voxtral-Mini-3B | GPU | 12.0% / 32.7% | 91% / 83% | 769 ms | 3/6 |
| Oriserve Whisper Hindi2Hinglish (India-tuned) | GPU | 17.5% / 61.1% | 71% / 40% | 134 ms | 6/6 |
| Parakeet-TDT v2 (English) + boosting | GPU | 7.9% / 28.5% | **97% / 95%** | 44 ms | 0/6 |
| **Parakeet-TDT v3 + boosting (chosen)** | GPU | **6.9% / 24.8%** | 95% / 90% | **52 ms** | **0/6** |
| Gemini 3.8 Flash | OpenRouter | 6.7% / 28.3% | 100% / 95% | 5.1 s (p95 33 s) | 4/6 |
| Qwen3.8-Omni-Flash | OpenRouter | 6.9% / 27.4% | 94% / 86% | 3.6 s | 6/6 ("Nothing intelligible") |
| Gemini 3.5 Flash-Lite | OpenRouter | 10.9% / 42.2% | 94% / 78% | 1.9 s | 6/6 ("Hello") |

What the results say:

- **The POC's errors came from the model choice.** Trading base.en for speed doubled word errors under bad-line
  conditions. Parakeet on the GPU is both 8× faster and twice as accurate.
- **Phrase boosting** (NeMo GPU boosting tree with `domain_terms.json`: animals, symptoms, treatments, districts,
  taluks, villages, names) lifts key-word recall on the worst condition from 75% to 90%, at no latency cost and with
  ≤0.3 points of WER on unrelated speech. One caution: a boosted place pulled an unknown village toward itself
  ("Hosahalli" → "Hassanli", next to the district Hassan).
- **v2 vs v3.** v2 is English-only and recalls key words best. v3 is better on real accented speech, but sometimes
  switches script on a Kannada name ("Channapatna" → Cyrillic), so `speech.py` drops non-Latin words. Svarah
  (gated, access requested) should decide between them.
- **Hosted transcription isn't worth it in the loop.** It is no more accurate than Parakeet on real accented
  speech, takes 2–10 s per turn, and invents text on silence. Gemini 3.8 Flash's knowledge of Indian names is the
  exception and would suit an after-call clean-up pass.
- **Rewriting the transcript with an LLM is harmful** (`correct.py`). It fixed some names, but also turned "she is
  **not getting up**" into "not eating", which drops an urgent sign, and "**blood** in the milk" into "bloat". It
  added 1.4 s and gained only 4 points of key-word recall. The design keeps the raw transcript as evidence. Only
  name and place *values* are snapped to the gazetteer, and the agent reads them back.

## Conversations

SIM_RESULTS

## Limits and what's not shown

- **The farmer speech in the dialogue tests is synthetic.** Kokoro mispronounces Kannada names ("Hosahalli" comes
  out as "Ha Sahali"), so place-name capture is *understated*. Real speakers are only in the ASR corpus (EdACC).
  There are no human calls from a real 2G phone yet, and no Hindi or Kannada.
- **Names and places are the weak spot.** The design accepts this:
  - read the value back;
  - let the farmer correct it;
  - after two failures mark it *unclear* and keep that turn's audio for a human.

  Constraining the village to the stated district's LGD list would help further.
- **Muse is shared.** When another job loaded the GPU (93%), interpretation slowed to 2.4–3.5 s and some turns used
  the rule fallback. Calls slowed but still completed. A dedicated small model would isolate this.
- **Browser latency is approximate** (RMS onsets in the page; the real phone path is not measured). Server-side timing
  is the primary measure.
