# Call center assist: a person takes the call, the agent fills the care record

A paravet at a livestock helpline (an ERC, like the 1962 centres) takes the farmer's call. The assist listens to
both sides and fills a **care record** as facts are said. The operator is trained to **repeat key facts back**
("Buffalo, not getting up since morning. Which village?"). Their headset audio is clean, so what they repeat is far
easier to recognise than the farmer's 2G audio, and it counts as confirmed. The agent never speaks to the farmer.
It never overrides the operator either. For important complaints it adds **protocol cards**: the extra questions,
a priority, and approved lines to read out. Diagnosis and medicines stay with the vet.

Its sibling, [`../full_call_center/`](../full_call_center/) (Codex), automates the whole workflow over Telegram.
The longer story, with what the evidence does and doesn't cover, is in
[`narrative/call_center_assist.md`](../../../../narrative/call_center_assist.md).

## Run

From the repository root, the livestock hub starts both examples and a landing page with one card each:

```sh
examples/livelihoods/livestock/run.sh            # hub :8770, assist :8776, case desk :8766, restarts the Buffalo bot
examples/livelihoods/livestock/run.sh --dry-run  # say what it would do, start nothing
examples/livelihoods/livestock/run.sh stop       # stop the hub, the assist and the bot
```

Only the assist:

```sh
examples/livelihoods/livestock/call_center_assist/assist/start.sh       # :8776; models load in ~40 s
open http://127.0.0.1:8776                     # tailnet: http://100.82.28.38:8776 (needs the insecure-origin flag, below)
examples/livelihoods/livestock/call_center_assist/assist/start.sh stop
```

Chrome only allows the microphone on `http://` from another machine if you list the address in
`chrome://flags/#unsafely-treat-insecure-origin-as-secure` (for example `http://100.82.28.38:8776`), then relaunch.

**What it needs** (`run.sh` checks these and stops with a list of what is missing):

| | where |
|---|---|
| Python venv (torch, NeMo, pipecat 1.12) | `~/.local/share/silo-voice/venv` |
| Models: Parakeet, Kokoro, smart-turn, Silero | `/mnt/seagate/silo/voice-robust/hf` (`HF_HOME`, offline) |
| Recorded farmer and operator clips | `/mnt/seagate/silo/voice-robust/assist/` (`make_scenarios.py`) |
| Local Muse (interpretation, card filling) | `http://127.0.0.1:8181`, used, never started here |
| OpenRouter key (the live AI farmer only) | `~/.config/idlisseus/openrouter.json`, never in the repo |
| State and logs | `~/.local/share/silo-voice/` (`assist.log`, `assist.pid`) |

Call audio and sessions never enter the repo (`.gitignore`).

Pick a case, pick how Lakshmamma answers, click **Answer call** and play the operator (use headphones).

- **Live (AI)**, the default. An LLM on OpenRouter (`FARMER_LLM`, default `google/gemini-3.1-flash-lite`) plays
  Lakshmamma from a case sheet (`lakshmamma.json`), her voice is local Kokoro `hf_beta` put through the 2G `gsm`
  condition, and the line's ASR hears that. Take the case in any order. She answers what you ask, one sign at a
  time, and keeps the rest until you ask about it ("did you buy any new goats?"). She corrects a wrong read-back,
  asks whether she should give medicine, and hangs up after goodbye. What leaves the machine: the case sheet and
  your words as recognised. It's synthetic role-play, nothing from real calls.
- **Recorded clips** (case 1 only; `buffalo-down` too, with `?test=1`). Fixed clips (`scenarios.json`, rendered by
  `make_scenarios.py`) answer the question you just asked, in the checklist's terms. Same farmer every time.

The cases are labelled by her opening line, so the menu doesn't give the case away. Each one is built from an
Indian field report, named in the case sheet:

| # | she opens with | behind it |
|---|---|---|
| 1 | "my goats are having loose motions" | diarrhoea, the top cause of goat deaths in village studies (MP 2013, TN 2022) |
| 2 | "my goats are not well. One small one died" | PPR-like spread after buying goats at the santhe (Karnataka outbreaks traced to bought-in animals) |
| 3 | "my goats are shaking, one has fallen" | young jowar sprouts: cyanide, goats the most susceptible (urgent, minutes) |
| 4 | "one of my good goats died in the night" | enterotoxaemia after a feed change; a second goat kicking at its belly |
| 5 | "my small ones have a cold, I think" | kid pneumonia in winter, the top kid killer with diarrhoea; she wants a tablet name |
| 6 | "my cow is giving very less milk" | lumpy skin disease (2022): she talks about the milk first, the lumps only when asked |
| 7 | "my goat is trying to give birth" | dystocia, a standing 1962 call type; she keeps asking "should I pull?" |

## What the screen shows

Two columns, on purpose: the operator works from the record, not from a script.

- **Call.** Your words as recognised, live while you speak, and Lakshmamma's words as the line delivered them,
  with ▶ to replay. After the call each of her lines also shows what she really said.
- **Care record.** Each field with where it came from: *confirmed* (you repeated it and the line agrees), *you said*,
  *heard only* (not repeated yet), *differs* (check it), or *to ask*. A repeat confirms whenever it comes: "okay, I
  have noted the goat problem" ten turns later confirms the animal. Hints sit on the field they're about (a
  gazetteer spelling for a village, a phone number that isn't 10 digits). The urgent signs are at the top.
- **After the call:** protocol checks, a second read of the whole call by local Muse and where it disagrees,
  the record against Lakshmamma's real answers, the case sheet (what she knew, and what she'd only say if
  asked), and timings.

## Protocol cards (prototype; `ASSIST_PROTOCOL=0` turns them off)

Real dispatch systems give a non-clinical call-taker more than a checklist, but not diagnosis or treatment. In
MPDS (ambulance dispatch) and NHS Pathways (NHS 111), what the caller says selects a protocol; its key questions
set a priority level and a response time, and the call-taker reads out pre-approved instructions ("pre-arrival
instructions", "care advice", "call back if it gets worse"). Clinicians take over anything outside the script. The
1962 veterinary ERCs work the same way: the call-taker collects the case, and a vet at the centre triages and
gives the medical direction ("online medical direction") or dispatches the mobile unit.

So the assist now does the same, inside the care record column:

- **Cards open from what was said**: the farmer's words, or the operator's statements (not their questions).
  Nine cards in `protocol_cards.json`: sudden death, possible poisoning, spreading disease, skin lumps, belly pain
  or bloat, difficult birth, cough, loose motions, animal down.
- **Each card adds its key questions as record fields** (*ask: what did they eat, and where?*), with the same
  confirmed / heard-only states.
- **A priority from fixed rules** on the answers: E (dispatch now, bring the ERC vet on), D, C or A. It shows
  whether the operator has brought the vet in.
- **Lines to read out**, ticked when the operator says them: "move the animals away from that field", "don't pour
  anything into their mouths", "don't pull", "keep the sick ones apart", and before closing, "call again if it gets
  worse".
- **Never to the farmer:** disease names or medicines. The after-call checks flag a disease named on the call.
  Disease names and the DAHD Standard Veterinary Treatment Guidelines appear only in the vet's handoff.
- **Rules, not the LLM, open cards and set the level.** Local Muse only fills a card's fields, and only the
  fields the operator just asked about. An operator line can only confirm what the farmer said. A value must be
  in the words: Muse had filled "Ate what" with the operator's goodbye, and "Age" with "two of them are coughing".

The cards, levels and lines are **illustrative**, written for the prototype from public sources and common
first-aid practice. A vet has to own them before any real use. The real thing would be the state's ERC
disease-severity mapping and SOPs.

## How it works

```text
operator mic -> SmallWebRTC -> Silero VAD + smart-turn v3 -> Parakeet (captions every 0.8 s while talking; the turn at the end)
   -> recorded: last sentence a question? (rules, instant) -> the clip for it plays 0.8 s later, over the same call
   -> live: every turn -> OpenRouter LLM as Lakshmamma (may stay quiet) -> Kokoro -> 2G line -> plays over the call
   -> operator words -> Muse (operator prompt: facts repeated back + what is being asked; 3 s deadline, rule fallback)
   -> farmer clip  -> the agent's ASR (as the line delivered it) -> the agent's farmer interpreter (nlu.py)
   -> Assist: one record, two sources per field, hints on the fields (polled by the page every 300 ms)
hang-up -> QA checks + Muse re-reads the whole transcript -> differences
```

Same ASR, gazetteer and interpreter as the agent call (`speech.py`, `nlu.py`, `domain_terms.json`). The protocol
order and the question wording come from `intake.py`.

## Results (automated role-play, `tests/browser_assist.py`)

**Live Lakshmamma** (`--script operator_script_lk.json`, case 2). The operator takes an off-checklist route (the
dead kid's age, the mouth, new animals) and never says "goat" until turn 11 ("I have noted the goat problem").

| | result |
|---|---|
| record vs her real answers | **11/11** fields in 4 of 5 runs (`lk-ai-1`…`-5`; run 3 was 10/11, below) |
| protocol checks | 8/8 |
| her reply starts after you stop | ~1.9 s p50 (LLM ~1.05 s p50, worst 4.7 s once; Kokoro + 2G ~0.2 s) |
| the late "goat problem" | confirmed the animal |

What the live farmer found that the recorded one couldn't:

- **Urgent signs nobody said.** Muse tagged "very dull" and a fever as *unconscious*, *difficult delivery* and
  *convulsions*. Now each urgent sign needs words for it in what was said (`nlu.urgent_with_evidence`), and a
  death ("one small one died") always counts.
- **The farmer's words credited to the operator.** She corrected a read-back ("the loose motions started only
  since yesterday") and Muse put "since yesterday" on the operator's next line, "Which village?". Operator facts
  are now kept only when the operator's own words carry them (`assist.said_by_operator`).
- **The answer read for the wrong question.** Her reply came before Muse had read the operator's question, so
  "two of them are breathing very fast" didn't fill *Breathing*. The farmer turn now uses the question the rules
  saw at once.
- **Symptoms in other words** ("fever" for "hot ears and body") showed as *differs*. They now merge.

**Recorded farmer**, *Basavaraju, buffalo down*, on `farm_phone`:

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

- The live farmer hears your words as our ASR recognised them, not your audio, so a mis-recognised read-back gets
  corrected even when you said it right ("No madam, Lakshmamma" after ASR heard "Lakshmema"). Real farmers mishear
  differently.
- The farmer's voice is synthetic Kokoro, and the scripted farmer only covers its clips. Real farmers say things the script doesn't
  cover. For a real pilot, the same screen would sit on a real call: the farmer leg of a SIP or Exotel stream,
  with the operator on a headset.
- The protocol checks are simple patterns, not a judgement of the call.
- An operator who doesn't repeat things gets no better than the agent-call ASR on the farmer's side. The
  repeating habit is the whole idea.
- Hosted re-listening of an unclear clip (for example Gemini on the saved farmer audio of a name) isn't wired up
  here. It's a privacy decision; see [`agent_call.md`](agent_call.md).

## Layout

| path | what |
|---|---|
| `assist/` | **This entry point**: `server.py` (:8776), `assist.py` (the record), `protocol.py` + `protocol_cards.json`, `farmer_ai.py` + `lakshmamma.json` (the live caller), `farmer.py` + `scenarios.json` (recorded clips), `static/`, `tests/` |
| `speech.py`, `nlu.py`, `intake.py`, `degrade.py`, `domain_terms.json` | Shared with the agent call: Parakeet and Kokoro on the GPU, the Muse interpreter and gazetteer, the checklist, the 2G line simulator |
| `server.py`, `call.py`, `static/`, `start.sh` | The other entry point, kept: **the agent takes the call** (:8775) |
| `sim.py`, `asr_bench.py`, `asr_engines.py`, `build_corpus.py`, `correct*.py`, `indic_*_trial.py`, `runs/` | The measurement record (below) |

## How it was measured

The agent-call work this grew out of, with the ASR bake-off (Whisper base.en vs Parakeet v3 and hosted models on
real Indian-accented speech over a simulated 2G line), ten simulated callers, browser calls and the Indic trials,
is in [`agent_call.md`](agent_call.md), with raw results in `runs/`. It was `benchmarks/voice-robust/` until
16 October 2026; the chronology entries before then use that path.

Tests (54, no models needed):

```sh
cd examples/livelihoods/livestock/call_center_assist
~/.local/share/silo-voice/venv/bin/python -m pytest -q -p no:cacheprovider tests/test_intake.py tests/test_live_calls.py assist/tests/test_assist.py assist/tests/test_protocol.py
# live, needs the servers: a real Chromium WebRTC call with a scripted operator
python3 assist/tests/browser_assist.py --script operator_script_lk_jowar.json
```
