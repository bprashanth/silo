# Operator assist: two columns, a live AI Lakshmamma, and how protocols could feed the assist

Work stayed in the `../silo-voice` worktree (branch `poc/voice-robust`). Codex's checkout, :8765/:8766 and the
Telegram bot were untouched.

**The screen is now call | care record.** The middle "next step / alerts" panel is gone. The staff work from the
record: an empty field reads *to ask*, and a hint (a gazetteer spelling, a short phone number) sits on its field.
The operator can take the case in any order. A repeat confirms whenever it comes, so "okay, I have noted the goat
problem" ten turns later confirms the animal; a test now pins that.

**One caller, Lakshmamma, with seven cases, played live by an LLM.** Each case sheet (`assist/lakshmamma.json`)
holds her story, details she gives only when asked, her manner, and the field answers, and names the Indian report
it is built from:

1. Loose motions (diarrhoea, the top goat killer in village studies).
2. PPR-like spread after buying goats at the santhe.
3. Young jowar sprouts (cyanide).
4. Enterotoxaemia-like sudden death.
5. Kid pneumonia in the cold.
6. Lumpy skin disease, where she talks about the milk first.
7. A stuck kidding.

The menu shows only her opening line, so it doesn't give the case away. Case 1 also keeps the recorded clips.

**Picking the model.** On the same 12-turn script, `google/gemini-3.1-flash-lite` gave one sign at a time,
corrected wrong read-backs, and stayed under 20 words, at ~1.1 s. The others fell short:

- Gemini 2.5 flash-lite: faster (0.8 s), but it spelled names out letter by letter and leaked symptoms.
- Haiku 5.5: broke the JSON twice.
- gpt-oss-120b: failed with reasoning off.
- Mistral small: slower.

Her reply starts ~1.9 s after the operator stops.

**What the live farmer exposed** (the recorded farmer never could):

- Muse invented urgent signs ("very dull" → *unconscious*; a fever → *difficult delivery*, *convulsions*). Signs now
  need words for them. A death always counts.
- Muse credited the farmer's correction ("since yesterday") to the operator's next question. Operator facts must
  now be in the operator's own words.
- The farmer's answer was read before the operator's question had been classified. The rule-detected question now
  goes with the turn.
- Symptoms put in other words showed as *differs*. They now merge.

Automated role-play, live case 2, with an off-checklist route: 11/11 fields and 8/8 protocol checks, in four of
five runs. Recorded buffalo case: 11/11 and 8/8 still. 43 unit tests pass.

## Brainstorm: how a real protocol could feed the assist (not built)

What exists publicly for 1962 / mobile veterinary units is the call flow, not the scripts:

1. The ERC call-taker records the caller, place and emergency type.
2. A vet at the centre triages, then either gives advice by phone or dispatches the nearest MVU.
3. A ticket is logged and SMSed to the owner and the van.

The MPDS (human emergency dispatch) is the mature model of a protocol that can be fed to software:

- **Entry questions**, asked on every call.
- **Chief-complaint cards**, each with key questions, a determinant level (Ω/A–E) set by the answers, and
  pre-arrival instructions to read out.

A livestock version for the assist could be data, not prompts:

- **Entry block.** The current 11 fields.
- **Complaint cards.** Each card has a few things:
  - Triggers, the words that open the card ("died", "shaking", "lumps", "giving birth").
  - Key questions, each one a field with a type.
  - Determinant rules. For example: deaths plus spread gives *E, dispatch now, notify*; one animal standing and
    eating gives *A, advice*.
  - Do and don't lines to read out. For example: "don't pull, keep her calm"; "move the goats off the jowar
    field"; "isolate the new goats".
  - Notifiability, which flags PPR, LSD, FMD and HS to the district officer.
- **The assist opens cards** from the farmer's words and adds their fields to the record. A jowar case grows
  *what did they eat / when*, and a new-goats case grows *bought from where / when / vaccinated?*. It ranks the
  determinant live, and checks after the call that each opened card's key questions were asked.
- **Sources.** The state AH department's SOP or 1962 ERC scripts, ICAR/state disease advisories and seasonal
  calendars, and the vets' own triage rules. Each card should be versioned and signed off by a vet. The LLM fills
  fields and spots triggers. It never sets the determinant or writes advice.
