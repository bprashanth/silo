# Signal pilot direction: discover unfinished work

The question for the pilot is whether Idli can catch work a person would otherwise forget. The current organizer surfaces one scheduling request and recent proposal titles. It does not maintain commitment history. A newer email can change what the brief shows without proving the earlier request was resolved.

## Three experiences to test with five to ten users for two weeks

| Experience | First useful slice with Google sources | Evidence a tester can check |
|---|---|---|
| My open loops | Separately surface requests addressed to me and promises others made to me. Show who owes what, the original words, when they were written and any explicit due date. | Pair “I’ll send the revised budget” with a later delivery only when the parties and document agree. Delivery and acceptance are separate events. Ask when the evidence is ambiguous. |
| Find anything | Find the document that was actually sent. Return its link or the Gmail conversation that carried it. | Compare the sent version with newer drafts in Drive. Ask for an organizer or date when several event PDFs fit. |
| Keep an eye on this | Start with “Tell me if nobody replies to this thread by Thursday.” Preview the exact thread, what counts as a reply, the local check time and where the alert goes. | On a fresh sync, an incoming reply cancels the alert. An overdue unanswered thread produces one alert. A failed sync reports uncertainty. Repeated checks and restarts must preserve the outcome. |

Start with one sandbox per person. Keep a source reference, timestamp and reason for each inferred state change. Let the person confirm, correct, mark done or snooze an item. An email asking for a budget is evidence of a request; a similarly named Drive upload alone cannot establish that the budget reached its recipient. Keep the evidence history when later delivery or acceptance changes the state.

## Fit with the core

Use existing lookup commands and SQL views for retrieval, dates and exact joins. A confirmed definition and judge can label uncertain meanings such as a promise or a request. Persist the supporting records and any correction. A Mini can combine views, a script step and judged labels. Keep timing, retries, notification deduplication and access checks in deterministic code. Preview outgoing actions and require explicit approval. Treat FIND, CATCHUP, TRACK, WATCH, PREPARE, ACT and REMEMBER as jobs to design around; approving new CLI verbs is a separate design decision. [CLI decisions](decisions.md) · [Mini design](minis.md)

Meeting preparation, handover, reporting gaps and compliance reminders can build on the same evidence. Examples include a Keystone call with unresolved questions, or missing field reports checked against an explicit roster and reporting period. Institutional recall needs a dated decision or verified correction. Voice-note ingestion, WhatsApp groups and external systems remain future source work. For any WhatsApp pilot, use opt-in, selected work groups with read-only ingestion and assess the unofficial connector before linking an account.

Measure how many surfaced items users confirm as genuine, how many they say they would have missed, and how often they return unprompted. Also record false closures, duplicate alerts and misses. Keep those measures separate from retrieval accuracy on the question banks. [Owner review queue](../todos/owner-review.md)
