# Daily digest

**Proposal.** Give a tester one short morning message with upcoming meetings, a scheduling request worth answering and relevant proposals. The earlier Signal experiment was retired. Its implementation and tests are preserved in commit `b58614b`.

## Compose from existing operations

1. Refresh the permitted Google sources. Read the next week of `calendar` with `list`, applying the current time, timezone and RSVP filters. Keep all-day and overlapping events when calculating availability.
2. Use a query or view over mail to select the latest message per thread. Look for an incoming request for times. Show the source words and Gmail link. Use a confirmed definition and judge if the tester wants a broader meaning of “needs a reply.”
3. Search mail and Drive for proposal titles and show links. For a scheduling request, a deterministic step can calculate two free half hours. The tester can review a draft before contacting anyone.
4. A future Mini runner would own the trigger, source freshness, deduplication and delivery. The earlier experiment used a weekday 08:30 IST push. Its interface included `my plan`, `draft times`, `pause briefs` and `resume briefs`. These are examples for evaluating the workflow.

## Benchmark before promotion

Replay an unanswered request, a later outgoing reply, declined and overlapping meetings, a stale calendar and a restart at delivery time. Check thread and file IDs, local times, absence of false availability, and one delivery per intended recipient and day. Compare the same one-off request via `idli ask`. A recurring digest needs an explicit schedule and a tested runner before rollout.
