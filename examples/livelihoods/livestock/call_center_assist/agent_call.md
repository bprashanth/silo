> The agent takes the call: the measurement record. The main entry point here is the operator assist, see [README.md](README.md).

# Robust voice intake for tired farmers on bad lines

**Question.** The first livestock voice POC (`benchmarks/livestock-voice`, Codex) kept mis-hearing callers. What does it take for a voice
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
examples/livelihoods/livestock/call_center_assist/start.sh          # :8775, isolated from the bot and from :8765; models load in ~40 s
open http://127.0.0.1:8775                # or http://100.82.28.38:8775 over the tailnet (needs the insecure-origin flag, see README.md)
examples/livelihoods/livestock/call_center_assist/start.sh stop
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

Ten simulated callers (`sim.py`) go through the full engine in real time: VAD, smart-turn, Parakeet, the interpreter,
Kokoro, plus barge-in and silence handling. The interpreter changes per run. Speech crosses a 2G (GSM) line; `noisy_gruff`
uses the worst condition (`farm_phone`) with noise bursts. The scenarios are:

- straightforward
- minimal ("My cow is sick.")
- everything at once
- a correction ("not three days, two days")
- talking over the agent
- urgent (can't stand, breathing fast)
- doesn't know when it started
- "one minute madam" then silence, then "what medicine should I give?"
- hesitant, with mid-sentence pauses, and silent once
- noisy and gruff with noise bursts

The simulated farmer corrects wrong read-backs and checks the phone number. Each call has 13 checks:
- fields: animal, count, symptoms, since, treatment, name, village, district, phone;
- urgency flag;
- confirmation;
- no question three times in a row;
- no reply slower than 6 s.

Per-scenario tables are in [runs/2026-10-16-sim](runs/2026-10-16-sim/README.md).

| interpreter | private | calls completed + confirmed | checks | first sound p50 / p90 | reply p50 / p95 | interpretation p50 |
|---|---|---|---|---|---|---|
| **local Muse 30B** | yes | 10/10 | 119/130 | 0.35 / 0.96 s | 1.95 / 4.14 s | 1.10 s |
| DeepSeek V4 Flash (text) | no | 10/10 | 120/130 | 0.35 / 0.93 s | 1.93 / 4.15 s | 1.07 s |
| Gemini 3.5 Flash-Lite **hearing the audio** | no | 10/10 | **127/130** | 0.35 / 0.97 s | 3.45 / 4.83 s | 1.83 s |
| rules only (the fallback, from a run where the API refused every call) | yes | 5/5 | 50/65 | 0.34 s | 1.71 s | 0.14 s |

What these show:

- **No call hung or looped, under any interpreter.** Every call reached a confirmed record. When interpretation slows
  down, fillers take up the slack; when it fails outright, the rule fallback still finishes the call.
- **The first sound comes 0.35 s after the farmer stops, every time.** It is the instant acknowledgement. The p90 of
  about 0.95 s is phone-number turns, where the agent deliberately waits 0.9 s for the next group of digits.
- **Village is nearly all of the local misses** (10 of 11). Kokoro can't pronounce Kannada names ("Hosahalli" becomes
  "Ha Sahali"), so Parakeet hears "Hassan…". The agent reads the value back, and when a correction comes back the same,
  it marks the field *unclear* and keeps the audio clip. The call doesn't loop.
- **Direct speech fixes place names.** Gemini hears the audio and knows Karnataka places, so it got the village right
  in 9 of 10 calls. It costs 1.5 s more per reply, which needed 5–8 fillers per call, and the audio leaves the box.
- **DeepSeek gains nothing over local Muse.** Same accuracy, same speed.

Real browser calls (`tests/browser_call.py`): Chromium, then WebRTC/Opus, then the server, with farmer audio injected as
the microphone. These are on the final code, in [runs/2026-10-16-browser](runs/2026-10-16-browser/):

| call | fields | first sound p50 (server / browser) | reply p50 | interruptions | result |
|---|---|---|---|---|---|
| plain | 8/8 | 0.37 / 0.43 s | 1.76 s | 0 | completed |
| simulated 2G line | 7/8 (village) | 0.38 / 0.36 s | 2.05 s | 0 | completed |
| farmer talks over the agent | 8/8 | 0.37 / 0.51 s | 1.90 s | 1 | completed |

## Bugs found by testing and fixed

The dialogue tests found real failure modes. Each now has a unit test or a scenario. `tests/test_intake.py` has 19
tests, including a fuzz test of 2,000 random callers per seed (run with 6 seeds): every call ends, and no question is
asked three times in a row.

| failure | fix |
|---|---|
| A phone number said in groups ("nine eight four five six, … seven two …") became two turns, and neither half was a number | Merge a fragment whenever the farmer resumes before the real reply starts. Wait 0.9 s between digit groups. Collect partial digits and say "… Go on." |
| On a weak line, Silero VAD fired late and **1.5–2 s of speech was lost** | AGC ahead of the VAD (noise-floor tracking), lower thresholds, 1 s pre-roll |
| Merging duplicated audio ("four four four four") because the pre-roll reached back into the previous turn | Clear the pre-roll at each end of turn |
| An 11-digit number was accepted | Require exactly 10 digits (after stripping +91/0). Read the number back and ask "is that right?" |
| **The "is that number right?" question looped forever** when the LLM re-stated the number instead of hearing "yes" | Check yes first; the same number counts as yes. **A generic backstop: no question a third time in a row** |
| A worried farmer repeating "what medicine should I give?" looped the agent | The full disclaimer once, then short. From the second side-question, it costs an attempt |
| The LLM marked a village "UNKNOWN", invented "cannot stand" from "No, no, it is a cow", and put a phone number in the name | "Don't know" only if said. Stand/breath facts only when asked about or mentioned. Names/places can't be digits. A later "she is standing" withdraws the urgent flag |
| The echo filter threw away a farmer repeating the agent's read-back | Off by default (browser/phone echo cancellation handles echo). Opt-in for speakerphones |
| Re-prompts stacked ("Hello, are you there? Hello, are you there? …") | Re-prompt from the question, not from the last thing said |

## Live calls by a person (2026-10-16, 07:05–07:16)

Six real browser calls on the user's own voice, some through the simulated 2G line. Most failed. What went wrong,
checked by re-transcribing the saved audio with five engines:

| what happened | cause | fix |
|---|---|---|
| "Bullock" heard as *Ballroo*, *Ball*, *The ball rolls*; the agent asked "What problem are you seeing in the ballroo?" and read back "Ten ballroos" | every engine mis-heard this speaker's "bullock"; the policy accepted any word as the animal | the animal must be a known word (English, Kannada, Hindi). Otherwise the nearest-sounding one is read back as a yes/no ("Did you say a bull?") and not stored until the farmer says yes. The re-ask now offers "bullock" |
| "Don't" became the village *Doddamaralavad*; "Bye" became *Ballari* (a district) | **phrase boosting of place names, on all the time**, makes Parakeet emit gazetteer words on short unclear clips | boost livestock words always (`parakeet-v3-boost-vocab`) and place and name words only for the turn after the agent asks for one (`ASR_PLACE_ENGINE`). The audio model's names and places are only taken when they were asked for |
| "One" heard as *Ten* | ASR | counts of 5 or more get "Ten animals, is that right?" |
| "It's not lying down" was not recorded as a problem, so the agent asked again, then took "Something else" as the problem and skipped "Can it stand?" | the interpreter didn't treat it as a symptom; "lying" let it infer *can stand = yes* | the farmer's own words are kept as the problem; "something else" is never a symptom; *can stand = yes* is recorded only as an answer to that question |
| "This phone number." went nowhere; "Eight nine seven six three" then "No, no. One eight nine seven six three five two" became 13 digits, so the phone was dropped silently | no "same number" path; "no, no" didn't restart the number | "this number / same number" uses caller ID. "No…" or a correction restarts the digits. The summary says when no phone was taken |
| In the Gemini-audio calls, replies took 6.7–8 s | hosted audio model latency | none; that option stays experimental |
| Two calls had **Test audio** on, so the mic wasn't sent and the agent said "Hello, are you there?" | UI | none (the checkbox is labelled) |

All of these have tests (`tests/test_live_calls.py`, 10 tests). The fuzz test now also has doubtful animals,
counts of 10, "this number" and "no, no" restarts. It ran clean over 8 seeds (16,000 callers), after it found one
more loop: unclear replies to "What should I correct?". The 10-scenario simulation re-run with the new defaults
(`runs/sim/v2-muse`): **120/130** checks (was 118). The noisy, gruff caller now completes without a loop (was
10/13). Reply p50 is 2.1 s (Muse was shared with other GPU jobs). First sound is 0.40 s p50.

A process with two boosted Parakeets and Kokoro crashed with *CUDA illegal memory access* in NeMo's CUDA-graph
decoder. `VR_NEMO_CUDA_GRAPHS=0` (set in both start scripts) fixes it at the same ~50 ms.

## Svarah, IndicConformer, Indic Parler-TTS (gated models)

**Svarah**: real Indian-accented English, 200 utterances, one per speaker, from 19 first languages and 17 states.
Run by the Cursor agent; report in `/mnt/seagate/silo/voice-robust/agents/indic-report.md`.

| engine | clean | gsm | opus loss | farm_phone | p50 |
|---|---|---|---|---|---|
| parakeet-v2 | 8.6% | 9.8% | 13.7% | **16.3%** | 26 ms |
| parakeet-v2 + livestock boost | 8.6% | | | 16.8% | 62 ms |
| parakeet-v3 | 9.8% | 11.3% | 14.0% | 17.7% | 50 ms |
| parakeet-v3 + livestock boost | 9.8% | | | 17.8% | 62 ms |
| parakeet-v3 + full boost | 10.6% | 12.0% | 15.0% | 18.5% | 51 ms |
| canary-1b-v2 | 9.6% | 11.0% | 15.4% | 17.7% | 192 ms |
| whisper-large-v3-turbo (GPU) | 7.4% | 9.8% | 14.1% | 19.2% (2/6 noise hallucinations) | 147 ms |

On general Indian English, v2 is about 1.4 points better than v3, and boosting costs 0.5–2 points. For Karnataka
speakers on farm_phone, v2 scored 25.1% and v3 29.8% (n=18). But on the cases that matter here, v3 with livestock
boosting won:

| | v3 + livestock boost | v2 + livestock boost |
|---|---|---|
| the user's own call audio | heard "It's a bullock", "The bullock", "So it's not eating", "Raichu" | heard "Kings of Balrow", "The ball bomb", "So it's not taking fe", "Right sure" |
| farmer key words | 83% | 88% |
| EdACC | 24.6% | 28.3% |

**Default: `parakeet-v3-boost-vocab`, with place boosting per turn.** Use v2 if the script-switching on names
(Cyrillic or Portuguese for "Basavaraju") becomes the bigger problem. It's English-only and can't switch.

**IndicConformer 600M** (VoicERA's recognizer; ONNX on the CPU here) on 6 synthetic Kannada farmer replies made by
Indic Parler-TTS:

| decoder | clean WER | farm_phone WER | p50 |
|---|---|---|---|
| RNNT | 0% | 31% | ~190–240 ms |
| CTC | 11% | 33% | ~190 ms |

Parakeet can't do Kannada at all. This is the path when the call moves to Kannada; test it on real Kannada speech
before trusting it.

**Indic Parler-TTS**:

| | Indic Parler-TTS | Kokoro |
|---|---|---|
| time per sentence | 3.1 s (about real time) | 0.13 s (23× faster) |
| GPU memory | 2.2 GB | 0.7 GB |

That's too slow for live replies, but fine for **pre-rendering the fixed prompts and fillers**, which are most
of what the agent says, in an Indian-English or Kannada voice. Listen side by side at
`/mnt/seagate/silo/voice-robust/tts/index.html`; nobody has judged the quality by ear yet.

## Operator assist (second entry point)

`assist/` (port 8776): a person takes the call and the agent listens and helps. It uses the same ASR, interpreter
and protocol, and the operator's repeats count as confirmation. In the automated role-play the farmer was on the
`farm_phone` line: "Kunigal" was recognised as nothing and "Basavaraju" as Portuguese. The call still got 11/11
fields right and passed 8/8 protocol checks, and the farmer answered 0.8 s after each question. See
`assist/README.md`.

## Recommendation

1. **Local is enough, and better, for recognition and the conversation.** Use Parakeet v3 (livestock words boosted, places only when asked), Muse, Kokoro
   `hf_alpha`, and this policy. It is private, and the farmer hears a response 0.35 s after they stop. Hosted models
   gained nothing in the loop except on place names.
2. **For names and places, use the hybrid.** Keep the call local. Send *only the saved audio clip* of an *unclear* name
   or village, plus the question, to an audio model (Gemini Flash-Lite, about 2 s, a fraction of a cent), after the call
   or in the background. Then put the result to the human reviewer as a suggestion. This keeps the conversation fast
   and private and fixes the weakest field, though a name or village clip is still personal data leaving the box, so
   it needs an explicit decision.
3. **Before trusting any number above,** test with real farmers on real 2G phones, starting with ~20 recorded calls.
   (Svarah is done: see above.) Load the program's real LGD village list per district.
4. To isolate from other GPU users, a dedicated small interpreter model would help. When Muse was shared with a busy
   GPU, interpretation went from 1.1 s to 2.4–3.5 s; calls still finished, with more fillers.


## Limits and what's not shown

- **The farmer speech in the dialogue tests is synthetic.** Kokoro mispronounces Kannada names ("Hosahalli" comes
  out as "Ha Sahali"), so place-name capture is *understated*. Real speakers are only in the ASR corpus (EdACC).
  There are no human calls from a real 2G phone yet, and no Hindi or Kannada.
- **Names and places are the weak spot.** The design accepts this:
  - read the value back;
  - let the farmer correct it;
  - after two failures mark it *unclear* and keep that turn's audio for a human.

  Constraining the village to the stated district's LGD list would help further.
- **Muse is shared** with the Telegram bot and other jobs on the box.
- **No real phone network.** The 2G line is simulated (codec, band-limiting, loss), and so is the browser's Opus at
  normal bitrates. Jitter and long dropouts on real networks aren't modelled.
- **TTS is Kokoro `hf_alpha` with English G2P.** It has an Indian timbre, but the pronunciation is American-English
  phonemes. Indic Parler-TTS (gated; access requested) could give an Indian English accent and is untested.
- **Browser latency is approximate** (RMS onsets in the page; the real phone path is not measured). Server-side timing
  is the primary measure.
