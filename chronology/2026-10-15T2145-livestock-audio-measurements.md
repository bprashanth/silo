# Spoken browser tests and latency optimization

The isolated livestock benchmark now runs genuine Pipecat SmallWebRTC microphone audio through Silero, Whisper, Muse and Kokoro. A standalone Playwright browser injects synthetic WAV speech through its microphone MediaStream and records the received spoken output. The in-app Browser runtime reported no available browser.

First local baseline: browser speech-end to received audio onset **6641 ms**, with **4632 ms ASR** using existing large-v3-turbo CPU inference. Switching only the experiment to isolated Whisper base.en reduced the comparable first turn to **1640 ms**, with **317 ms ASR**. This is a single-turn before/after, not a percentile claim. Dependencies and downloaded model are on Seagate; production Telegram speech is unchanged.

Evidence under `/mnt/seagate/silo/livestock-voice/runs/`: `browser-local-03/baseline.json`, `browser-local-04/record.json`, and screenshots/received audio beside them. Later local tests found material quality problems: missing urgency, repeated questions, lost correction and unavailable-contact handling. These are retained as failed quality checks, not hidden by the working audio transport. Added explicit evidence-based urgency classification, missing-question routing and regression tests. The short noisy synthetic sample had transcription errors; no human-accent or multilingual claim is warranted.

Hosted GPT Audio Mini completed a five-turn browser intake with actual received audio, all required fields addressed, urgent review flagged, caller confirmation and a locally saved mock completion. Browser onset samples were 3638, 3764, 3057, 2977 and 2738 ms (p50 3057 ms). Observed API usage cost was $0.0037866 for that call. [Small summary](../benchmarks/livestock-voice/runs/hosted-browser-summary.json); raw transcript/record/audio at `/mnt/seagate/silo/livestock-voice/runs/browser-hosted-01/`.

Dograh's native ARM64 stack is deployed and has produced a greeting, transcribed “My cow is sick”, and asked for the caller's name in its own browser UI. More extensive native verification is ongoing; deployment alone is not completion. Native public STUN configuration was discovered and removed for the local-only run.

All quoted browser times are received-audio RMS onset measurements, not physical speaker measurements. Tests use synthetic data and share host resources with other services.
