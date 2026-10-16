# Call center automation: a livestock workflow with a conversational gap

The frozen example is [full_call_center](../examples/livelihoods/livestock/full_call_center/). It demonstrates a livestock assistance workflow through Telegram, a local case desk and an optional Fizzy board. It does not yet provide a real-time telephone call or a reliably conversational intake agent.

## What the POC establishes

A farmer sends text or a voice note. Whisper transcribes audio locally; Muse extracts structured information; the application asks for missing information and requires confirmation before submission. Kokoro produces spoken replies. The active trial is English with `af_heart`; the preceding Hindi trial used `hf_alpha`. Both use the existing local Muse service.

Submitted cases appear in the case desk. An operator assigns a registered vet, who accepts through Telegram and later reports a visit, observations, assistance and follow-up needs. The bot asks the farmer for feedback, and an operator closes resolved cases. Disagreement or continuing need routes to review. Photos, voice notes and location can support a report; they do not independently establish that a visit occurred.

Fizzy is a self-hosted, one-way display of submitted live cases. It mirrors status and structured fields; the case desk remains authoritative for assignment and closure. Drafts and synthetic historical seed cases are excluded. Telegram identifiers, original transcripts and media are not copied to Fizzy. No case data was uploaded to fizzy.do. Fizzy can be stopped without changing either bot or the case database.

Buffalo Soldiers has its own token, owner-only allowlist, inbox and process. The original io/Silo bot remains in `tg-bridge/`, without livestock routing. The code lives in the example directory, and Python imports and service commands use that location directly. The temporary root compatibility symlink was removed; historical chronology retains the commands used at the time. Private configuration and runtime databases remain outside the checkout; large model, audio and screenshot artifacts stay on Seagate or the existing host model store.

## What the evidence actually covers

There are two completed live Telegram roleplays: the earlier English workflow through the original integration, and the independent Buffalo Hindi workflow. Both used one account for farmer and vet, synthetic media and fictional visits. Feedback is explicitly labeled single-account roleplay rather than independent verification. The separate 150-case seed dataset is fictional history, not 150 tested conversations.

The Hindi run exercised intake, confirmation, assignment, acceptance, report clarification, report confirmation, feedback and closure. Actual returned Telegram audio was decoded and transcribed back to Hindi. Browser checks opened the corresponding native Fizzy card, followed its case-desk link and verified the closed case under Done. The later English switch verified Kokoro output and Whisper recognition; it was not a new completed English Buffalo workflow.

Twenty-nine deterministic tests pass at freeze. Tests cover state transitions, grounding, isolation, selected language handling, transport behavior and mirror recovery. These tests do not establish robustness to arbitrary conversation, accents, noise, multiple independent users or production traffic. Some voice-note turns took tens of seconds. Earlier Pipecat/Dograh calling work remains recorded under benchmarks and chronology; this example uses asynchronous messages.

## Where the real conversation broke

The current intake is a prescribed checklist, not a conversational agent. Muse extracts fields and the application asks the first missing question. A scripted straight-through demonstration hid several failures:

- “My cow is looking sick” yielded no fields, even though the animal type was explicit.
- “Which animal—do you want its name?” was treated as ambiguity and triggered the same question again. Romanized Hindi recognition also missed that clarification.
- “What do you mean by struggling to breathe?” received a request to clarify instead of an explanation.
- “It is standing” answered only part of a combined standing/breathing/consciousness question. The application did not track those parts separately and repeated the whole question.
- An animal report sent while the account remained in vet mode failed because no case was assigned. A generic error concealed the actionable cause.

The last issue now produces explicit role-switch/assignment guidance. A narrow fallback retains unambiguous animal mentions and explicitly stated weakness when Muse extracts nothing. Questions and negations are excluded from that fallback. These repairs do not solve general clarification or partial-answer handling.

Other fixes discovered during testing included readable Unicode for Hindi model prompts, preservation of Devanagari marks for speech, and enumeration of closed Fizzy cards to prevent duplicate creation after mirror-state loss.

## Agreed direction, not implemented in this freeze

Separate the required information from the wording and order of the conversation. The questionnaire should specify fields, completion criteria, independent subquestions, accepted unknowns, conditional follow-ups and approved explanations. Documentation should ground explanations and relevant exploration; it should not silently replace the checklist or authorize invented treatment advice.

On each turn, the agent should distinguish answers, corrections, clarification requests and related questions. It should propose supported field updates and a natural reply, then ask one unresolved question. The application should retain partial answers, validate updates and control submission. A brief relevant detour is permitted, followed by a return to outstanding intake items. Completion still requires an explicit summary confirmation.

For the next iteration, supply a small approved guidance document directly with the checklist before building document search. Evaluate conversations with clarification, partial answers, corrections, unknowns and tangents, including whether the agent returns to intake. A completed checklist alone is insufficient evidence of a usable conversation.

The user asked to freeze before implementing this design. The example preserves the existing behavior and its limitations for review.

## Evidence trail

- [Voice benchmark closeout](../chronology/2026-10-15T2323-livestock-voice-benchmark-closed.md)
- [Initial live Telegram workflow](../chronology/2026-10-15T2343-livestock-v2-telegram-complete.md)
- [Independent Hindi bot and Fizzy](../chronology/2026-10-16T0830-buffalo-hindi-fizzy.md)
- [English trial switch](../chronology/2026-10-16T2220-buffalo-english-trial.md)
- [Role error and explicit-observation recovery](../chronology/2026-10-16T2236-buffalo-role-error-recovery.md)
- [Freeze and relocation](../chronology/2026-10-16T2256-freeze-livestock-call-center.md)
