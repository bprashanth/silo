# Voice: what broke in the first live calls, Svarah, and an operator-assist entry point

Work stayed in the `../silo-voice` worktree (branch `poc/voice-robust`). Codex's checkout, :8765/:8766 and the
Telegram bot were untouched.

**The user's own calls (6, 07:05–07:16 IST) failed for reasons the synthetic tests had missed.** I re-transcribed
the saved audio with five engines to separate recognition from policy:

- **"Bullock" was mis-heard by every engine** ("Ballroo", "The ball rolls"), and the agent accepted it as the
  animal. Animals are now checked against a list of English, Kannada and Hindi words. Anything else is read back
  as a yes/no ("Did you say a bull?") before it is stored.
- **Place-name boosting, on all the time, invented places**: "Don't" became the village "Doddamaralavad", and
  "Bye" became the district "Ballari". Livestock words are now always boosted. Place and name words are boosted
  only for the turn after the agent asks for one.
- **"One" was heard as "Ten"**, so counts of 5 or more are now confirmed.
- **"It's not lying down" was dropped, then counted as *can stand*.** The farmer's own words are kept, and "can
  stand" is recorded only as an answer to that question.
- **The phone number failed two ways.** "This phone number" now uses caller ID, and "No, no, …" restarts the
  digits.

Results: 10 regression tests, and a fuzz test of 16,000 callers, which found and fixed one more loop. The
10-scenario simulation scored 120/130 (was 118/130). Two boosted Parakeets plus Kokoro in one process crashed in
NeMo's CUDA-graph decoder; `VR_NEMO_CUDA_GRAPHS=0` fixes it.

**Gated models** (the user accepted the terms; the Cursor agent ran the benchmarks):

- **Svarah** (200 Indian-English speakers): Parakeet v2 is 1.4 points better than v3 on a bad line (16.3% vs
  17.7%). But on the user's real voice and on farmer key words, v3 with livestock boosting was better, so it
  stays the default.
- **IndicConformer** (VoicERA's recognizer): 0% WER on clean synthetic Kannada, 31% on a bad line.
- **Indic Parler-TTS**: 3.1 s per sentence, about 23× slower than Kokoro. Use it to pre-render fixed prompts,
  not for live replies.

**Operator assist** (`benchmarks/voice-robust/assist/`, :8776) is a second entry point: a person takes the call,
the agent listens to both sides and keeps the checklist. What the operator repeats back counts as confirmed. The
screen shows the next question, urgent alerts, gazetteer spellings, the phone digit count, and line/operator
disagreements. After the call come protocol checks and a second read of the whole call by local Muse. A scripted
farmer (recorded clips through a bad-line condition) answers the questions the operator asks, so the user can
role-play the operator. Automated browser role-play: 11/11 fields and 8/8 checks, with the farmer answering
0.8 s after each question. The farmer side of the line got "Kunigal" as nothing and "Basavaraju" as Portuguese;
the operator's repeats carried both.

**Graduation pattern**: `docs/GRADUATION.md` records how a tested benchmark moves into
`examples/stacks/livelihoods/livestock/`: one `run.py` that starts only its own servers, a hub page with one card
per entry point, and the benchmark left as the measurement record. Nothing is moved yet.

Verify:

```sh
cd benchmarks/voice-robust
python -m pytest tests/ assist/tests/test_assist.py -q   # 37 tests
./start.sh && assist/start.sh                           # :8775 agent call, :8776 operator assist
python3 assist/tests/browser_assist.py                  # operator role-play in Chromium
```
