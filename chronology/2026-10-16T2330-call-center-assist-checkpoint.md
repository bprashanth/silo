# Call center assist: checkpoint before the move

The operator assist (:8776) is checkpointed as it stands at `1a4c1fe`, with the protocol cards on. The longer
account is in [`narrative/call_center_assist.md`](../narrative/call_center_assist.md).

**State at the checkpoint.**
- The screen is call | care record. Protocol cards open inside the care record, with a priority banner. A
  vet handoff block appears after the call.
- The caller is Lakshmamma, with seven case sheets drawn from Indian field reports. She is played live by
  `google/gemini-3.1-flash-lite` on OpenRouter (synthetic role-play only), or from recorded clips for the
  loose-motions and buffalo cases.
- Recognition (Parakeet), understanding (local Muse) and the voice (Kokoro) are local.
- Tests: 54 unit tests pass. Live role-play: young-jowar 10/11 fields with protocol QA 13/15, case 7 at 11/11,
  and the recorded buffalo case at 11/11.

**How to try it** (as given to the user):
1. Open `http://127.0.0.1:8776`. Over the tailnet it is `http://100.82.28.38:8776` and needs Chrome's
   insecure-origin flag.
2. Pick "my goats are shaking, one has fallen" (young jowar) in AI mode, and take the call as the paravet.
3. Check the review and the vet handoff afterwards.
4. Restart with `ASSIST_PROTOCOL=0` to compare without the cards.

**Still open.**
- The animal-down lines are worded for cattle.
- The operator ASR mis-hears names with the American test voice.
- The live farmer hears the ASR text, not the operator's audio.
- No real farmer recordings yet.
- The cards need a vet's sign-off.

**Next** (asked in the same message): move the assist into `examples/livelihoods/livestock/call_center_assist/`
next to Codex's `full_call_center/`, with a `run.sh` landing page that has one card per entry point.
