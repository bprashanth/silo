# Call center assist: a human takes the call, the agent fills the care record

The example is [call_center_assist](../examples/livelihoods/livestock/call_center_assist/). A paravet at an
emergency response centre (ERC) takes a farmer's call. The assist listens to both sides, fills a care record
as facts are said, and marks each fact *confirmed* once the operator repeats it back. Codex's
[full_call_center](../examples/livelihoods/livestock/full_call_center/) automates the whole workflow over
Telegram. This example keeps a person on the phone and makes that person's job easier.

## How it got here

It started as a different question: can a voice agent take the call itself? A farmer with a gruff voice, a
cheap phone and a bad line made the first POC mis-hear almost everything.
- **Recognition was the main fix.** Whisper base.en on the CPU was replaced by Parakeet-TDT v3 on the GPU with
  domain phrase boosting. On real Indian-accented speech over a simulated 2G line, word errors fell from 51%
  to 25%. Recall of the key words (animal, numbers, symptoms, names, places) rose from 57% to 90%.
- **Structure keeps the conversation sound, not a bigger model.** Code decides what to ask, so the species
  is never forgotten. Each question gets two tries before it is marked unclear, and every turn has a
  deadline with a rule fallback, so nothing loops or hangs. The LLM only interprets replies.
- **The record** is in [`benchmarks/voice-robust`](../examples/livelihoods/livestock/call_center_assist/README.md#how-it-was-measured)
  (now moved with the code): an ASR bake-off on 104 clips, ten simulated callers, and real browser calls.

The agent-led call still works (:8775). The user's own calls showed what it cannot do well: it cannot take a
call that goes off-script the way a person can. So the second entry point turned it around. The human leads,
and the agent becomes the ears and the notebook.

## What the assist does

- **Two columns: call | care record.** A middle "next step" panel was dropped on the user's request. Staff are
  trained to look at the record and ask whatever still reads *to ask*. Field hints, such as the gazetteer
  spelling of a village or a phone number with too few digits, sit on the field itself.
- **Any order, late confirmation.** The operator can take the case in any order. A repeat confirms whenever it
  comes, so "I have noted down your goat issue" ten turns later confirms the animal.
- **Grounded facts.** Every fact needs words for it in what was said. An operator fact must be in the
  operator's own words, and an urgent sign needs words for that sign. The live farmer exposed each of these
  rules by breaking it: Muse turned "very dull" into *unconscious*, and credited the farmer's correction to the
  operator's next question.
- **Protocol cards** (a prototype, switched off with `ASSIST_PROTOCOL=0`). Real dispatch systems guide a
  non-clinical call-taker, but don't let them diagnose: MPDS cards and determinant levels, NHS Pathways, and
  the 1962 veterinary ERCs, where the call-taker collects and a vet gives medical direction. So the assist:
  - opens a card from the farmer's words (sudden death, poisoning, spreading, skin lumps, belly, birth, cough,
    loose motions, animal down);
  - adds the card's key questions to the record and sets a priority (E, D, C or A) from fixed rules;
  - shows a few pre-approved lines to read out, and the call-back-if-worse line;
  - after the call, checks that the paravet asked, read out the lines, escalated at E and named no disease, and
    gives the vet a handoff that points to DAHD's Standard Veterinary Treatment Guidelines (2024).

  The cards are illustrative. They need a vet's sign-off and the ERC's own severity mapping before real use.

## The practice caller

Lakshmamma, from Hosahalli in Kanakapura taluk, calls with one of seven problems. Each case sheet is built from
an Indian field report: goat diarrhoea, PPR-like spread after buying at the santhe, young jowar (cyanide),
enterotoxaemia-like sudden death, kid pneumonia, lumpy skin disease and a stuck kidding. She gives one thing at
a time and only what is asked. She corrects wrong read-backs and hangs up only after a goodbye.
`google/gemini-3.1-flash-lite` plays her, at about 1.1 s per reply. It was picked over Gemini 2.5 flash-lite
(spelled names out letter by letter), Haiku 5.5 (broke the JSON), gpt-oss-120b and Mistral small. OpenRouter
receives only the synthetic case sheet and the operator's recognised words. The voice is local Kokoro, through a
simulated GSM line.

## What the evidence covers, and what it doesn't

- **Covered.** 54 unit tests of the record, the confirmation rules and the cards. Scripted role-plays through
  a real Chromium WebRTC call:
  - Live young-jowar case: 10/11 fields, protocol checks 13/15. The two fails are real: the script skipped
    the animal-down card's question and one of its lines.
  - Live case 7: 11/11.
  - Recorded buffalo case: 11/11.
- **Not covered.**
  - The operator voice in tests is an American TTS voice, and it mis-hears Kannada names ("Hasahali").
  - The live farmer hears the ASR text, not the audio.
  - No real farmer recordings have gone through the assist.
  - IndicConformer on real Kannada was not tried in the assist.
  - The village list is a small gazetteer, not the real LGD list.
  - The animal-down lines are worded for cattle.

## Evidence trail

- [Robust farmer intake](../chronology/2026-10-16T0414-voice-robust-farmer-intake.md)
- [Live calls and the operator-assist entry point](../chronology/2026-10-16T0852-voice-live-calls-and-operator-assist.md)
- [Two columns and a live Lakshmamma](../chronology/2026-10-16T1437-operator-assist-live-lakshmamma.md)
- [Protocol cards](../chronology/2026-10-16T1530-operator-assist-protocol-cards.md)
- [Checkpoint](../chronology/2026-10-16T2330-call-center-assist-checkpoint.md)
