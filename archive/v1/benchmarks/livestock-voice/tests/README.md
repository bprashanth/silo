# Browser audio tests

Generate local, fictional farmer fixtures (audio stays on Seagate):

```sh
tg-bridge/.venv/bin/python benchmarks/livestock-voice/tests/generate_fixtures.py
```

With the server running, exercise the actual browser audio/WebRTC/STT/agent/TTS path:

```sh
python3 benchmarks/livestock-voice/tests/browser_audio.py \
  --backend pipecat \
  --output /mnt/seagate/silo/livestock-voice/runs/my-local-call
# Hosted test explicitly sends these fictional voices to OpenRouter:
python3 benchmarks/livestock-voice/tests/browser_audio.py \
  --backend openrouter \
  --output /mnt/seagate/silo/livestock-voice/runs/my-hosted-call
```

The browser checks **Use synthetic audio instead of microphone**, clicks Call, and selects
and speaks fixtures using visible controls. Each fixture is decoded to audio and connected
to the same continuous WebRTC sender as a real microphone. No transcript text is injected.
A continuous silent audio source keeps the sender alive between utterances so VAD receives
end-of-turn silence. Playwright saves per-turn screenshots, the exported call record,
received agent audio (WebM), observations, console errors and checks. FFmpeg verifies that
the agent recording contains non-silent PCM audio.

The default five-turn call covers missing information, details supplied out of order,
urgent warning signs, unavailable contact/no previous treatment, and confirmation. If ASR drops the volunteered name and the agent asks for it, the driver
speaks a separate real name-only fixture before confirming, and records that extra turn.
`checks.json` reports quality separately from audio transport success. A successful script
exit means the spoken turns completed and real agent audio arrived; it does **not** imply
all questionnaire quality checks passed. Inspect `confirmed`, `urgent_flag`, `animal_cow`
and `missing_fields` in that file, plus the actual transcript.

Additional tests:

```sh
# Short, interrupted greeting. Barge-in measurement is approximate.
python3 benchmarks/livestock-voice/tests/browser_audio.py --backend pipecat \
  --barge --fixtures missing --output /mnt/seagate/silo/livestock-voice/runs/my-barge
# Deliberately incomplete call: evaluate unknown/correction handling, not completeness.
python3 benchmarks/livestock-voice/tests/browser_audio.py --backend pipecat \
  --fixtures difficult,unknown,correction \
  --output /mnt/seagate/silo/livestock-voice/runs/my-difficult-call
```

Browser latency uses one monotonic browser clock: scheduled last non-silent fixture sample
versus first non-silent received agent PCM frame. These samples are saved both in
`browser_metrics` in the exported record and the backend's `events`. This includes WebRTC
and browser buffering, but excludes physical speaker/device latency. Human mic mode uses
an approximate RMS speech-end detector instead of the known fixture schedule.

Synthetic Kokoro-to-Whisper tests are favorable to recognition and do not demonstrate
human accent robustness. The noisy fixture adds deterministic low-level noise to local
synthetic English; it is not a human recording or an Indian-accent evaluation. No human
microphone test should be claimed from these scripts. For a human test, leave synthetic
mode unchecked and grant the browser microphone permission on localhost.

The Browser skill was loaded first; its runtime reported no available browsers. These
standalone Playwright tests are the fallback for this environment, rather than automation
of an available in-app browser surface.

Native Dograh runs its own browser transport and conversation engine:

```sh
python3 benchmarks/livestock-voice/tests/dograh_browser.py \
  --output /mnt/seagate/silo/livestock-voice/runs/my-native-call
```

Its saved native transcript and recorded WebRTC audio are separate evidence. The shared
page imports the transcript into local structured extraction after the native call; this
does not replace Dograh's voice engine. See `../CANDIDATES.md` for verified and incomplete
native conditions.
