# Operator assist: a person takes the call, the agent listens and helps

The second entry point. In the first (`../`, port 8775) the agent takes the farmer's call. Here a helpline operator
takes it, and the agent listens to both sides and helps in real time. The operator is trained to **repeat key facts
back** ("Buffalo, not getting up since morning. Which village?"). Their headset audio is clean, so what they repeat is
far easier to recognise than the farmer's 2G audio, and it counts as confirmed. The agent never speaks to the farmer.
It never overrides the operator either.

```sh
benchmarks/voice-robust/assist/start.sh        # :8776; models load in ~40 s; doesn't touch :8775, the bot or :8765
open http://127.0.0.1:8776                     # tailnet: http://100.82.28.38:8776 (same insecure-origin flag as :8775)
benchmarks/voice-robust/assist/start.sh stop
```

Pick a farmer, click **Answer call** and play the operator (use headphones). The farmer is scripted: recorded clips
(`scenarios.json`, rendered by `make_scenarios.py` through the scenario's bad-line condition) that answer the
question you just asked. The farmer waits through statements, as a person does, and answers when you ask
something. A wrong read-back gets corrected ("No madam, Kunigal"). Asked twice, the farmer gives a slower
answer ("Hosa... halli"). Mumbling gets "Hello? I could not hear". One scripted farmer can be replayed to
many operators, which makes this a training tool too.

## What the screen shows

- **Call.** Your words as recognised, live while you speak. Below them, the farmer's words as the line delivered
  them, with ▶ to replay the clip. The farmer side is meant to look bad; it is why you repeat things.
- **Assist.**
  - One big **next step**: either the next question, in the protocol's order (urgent cases move the village and
    phone up), or "Repeat back to confirm: 'Kunigal, right?'" when only the line heard a value.
  - **Alerts:**
    - Urgent signs, and what to take next.
    - A farmer's question about medicine ("don't prescribe, the vet team will advise").
    - Gazetteer spellings for a name or place that isn't in the list ("Hosali: did they mean Hosahalli?").
    - The line and you disagreeing.
    - A phone number that isn't 10 digits, or a read-back that sounded wrong. A mis-heard read-back never
      replaces a good number.
  - The phone digits as you take them (`98456 72310 (10/10)`).
- **Case record.** Each field with where it came from:
  - *confirmed*: you repeated it and the line agrees.
  - *you said*: only you said it.
  - *heard only*: repeat it back.
  - *differs*: check it.
- **After the call** (on hang-up):
  - Protocol checks: asked the species, standing and breathing; repeated facts back; read the phone back; read
    the case back; didn't prescribe; urgent case took the village and phone first.
  - A **second read of the whole call** by local Muse, and where it disagrees with the live record.
  - In role-play, the record against the farmer's real answers.
  - Timings per turn.

## How it works

```text
operator mic -> SmallWebRTC -> Silero VAD + smart-turn v3 -> Parakeet (captions every 0.8 s while talking; the turn at the end)
   -> last sentence a question? (rules, instant) -> scripted farmer clip plays 0.8 s later, over the same call
   -> operator words -> Muse (operator prompt: facts repeated back + what is being asked; 3 s deadline, rule fallback)
   -> farmer clip  -> the agent's ASR (as the line delivered it) -> the agent's farmer interpreter (nlu.py)
   -> Assist: one record, two sources per field -> next step + alerts (polled by the page every 300 ms)
hang-up -> QA checks + Muse re-reads the whole transcript -> differences
```

Same ASR, gazetteer and interpreter as the agent call (`../speech.py`, `../nlu.py`, `../domain_terms.json`). The
protocol order and the question wording come from `../intake.py`.

## Results (automated role-play, `tests/browser_assist.py`)

A real Chromium WebRTC call. The operator's 15 lines (`operator_script.json`, Kokoro `af_heart`, clean) are fed in
as the mic. The farmer is *Basavaraju, buffalo down* on the `farm_phone` condition (noisy yard, cheap mic, 2G codec,
packet loss).

| | result |
|---|---|
| record vs the farmer's real answers | **11/11** fields |
| protocol checks | 8/8 |
| farmer answers after the operator stops | 0.80 s every time (the scripted gap); 15 answers, no double answers |
| second read by Muse | agrees with the live record (4.3 s) |
| operator ASR | 60–250 ms per turn |
| operator interpretation (Muse) | 1–3 s; at the 3 s deadline the rules took over. Nothing waits on it: the farmer's reply and the checklist use the rules at once |

What the farmer side looked like on that line, and why repeating matters:

- "Buffalo madam, emme" became *Buffalo Madame F.*
- "Breathing is very fast madam" became *Breeding is very fast mother.*
- "Kunigal" was recognised as nothing at all.
- "Basavaraju" became *Nessa é verdade*: Parakeet v3 switched to Portuguese.

The operator's repeats carried all four. The record took the village and name only from the operator; the screen
labels those fields *you said*.

Two problems from the first runs, now fixed:

- **Mid-sentence pauses split operator turns**, so the farmer answered each fragment. The farmer now answers only
  a question, a greeting, a read-back or a goodbye. After a statement, the farmer waits and says "Hello?" after
  6 s of silence.
- **A summary read-back recognised as 11 or 14 digits overwrote the correct number.** Now it's kept aside, with an
  alert to read it again.

## Limits

- The farmer is scripted, and the farmer's voice is synthetic Kokoro. Real farmers say things the script doesn't
  cover. For a real pilot, the same screen would sit on a real call: the farmer leg of a SIP or Exotel stream,
  with the operator on a headset.
- The protocol checks are simple patterns, not a judgement of the call.
- An operator who doesn't repeat things gets no better than the agent-call ASR on the farmer's side. The
  repeating habit is the whole idea.
- Hosted re-listening of an unclear clip (for example Gemini on the saved farmer audio of a name) isn't wired up
  here. It's a privacy decision; see `../README.md`.
