# Hosted audio and Dograh deployment evidence

## OpenRouter actual speech-to-speech

Catalog fetched from `https://openrouter.ai/api/v1/models` on 2026-10-15 and saved at
`/mnt/seagate/silo/livestock-voice/evidence/openrouter-models.json`.
Only `openai/gpt-audio` and `openai/gpt-audio-mini` in that snapshot list **both** audio input and output. Lyria is audio-output-only; Gemini, Voxtral and Qwen entries do not list audio output and cannot qualify as this candidate.

| Model | Text input / 1M tokens | Text output / 1M | Audio input / 1M | Audio output / 1M |
|---|---:|---:|---:|---:|
| openai/gpt-audio-mini | $0.60 | $2.40 | $0.60 | $2.40 |
| openai/gpt-audio | $2.50 | $10.00 | $32.00 | $64.00 |

These are the catalog's literal rates, not assumed upstream OpenAI rates. Mini is the cheapest suitable model in this snapshot. OpenRouter billing observed below is authoritative for the paid smoke test; prices may change.

[OpenRouter's audio API documentation](https://openrouter.ai/docs/guides/overview/multimodal/audio) describes complete base64 input audio and SSE output chunks. `candidates.py` implements this with `modalities=[text,audio]`, PCM16 output, actual `delta.audio.transcript` and usage events. This is **turn-based audio input with streamed speech output**, not a realtime speech API. Local VAD/WebRTC may surround it without changing that distinction. Audio output is 24 kHz mono signed PCM16.

Two short synthetic English spoken inputs were generated locally with Kokoro and sent as WAV audio. The second request included prior conversation text; the caller transcript is separately generated locally for display. Response audio and the corresponding provider transcript are retained.

| Turn | Actual response | Request → first audio | Full API response | Observed billed cost |
|---|---|---:|---:|---:|
| Sick cow, not eating since yesterday | “I'm sorry to hear that. Could you tell me your name and your village?” | 1571 ms | 1961 ms | $0.0002886 |
| Can stand; Ramesh, Demo village/district | “Thank you, Ramesh. How many cows are sick right now?” | 2200 ms | 2767 ms | $0.0003300 |

Total observed billing: **$0.0006186** for these two responses. This is not a complete-call price. ASR/LLM/TTS stage timings are not exposed by the provider; VAD, browser buffering and audible playback are excluded from these API smoke timings. The first response bundled two fields in one question, so questionnaire adherence is imperfect. No human microphone test or multilingual claim follows from this synthetic smoke test.

Artifacts under `/mnt/seagate/silo/livestock-voice/evidence/`: `hosted-input-{0,1}.wav`, `hosted-output-{0,1}.wav`, `openrouter-smoke.json`. Secret loaded only server-side from `~/.config/idlisseus/openrouter.json`; never copied into artifacts. The hosted path is explicitly non-private and limited to synthetic data.

## Native Dograh

[Dograh source](https://github.com/dograh-hq/dograh) cloned to `/mnt/seagate/silo/livestock-voice/dograh`; native latest Docker API/UI report version 1.49.0. `dograh-api-manifest.json` verifies an ARM64 image exists; this deployment is not x86 emulation. The checked-in Compose file pins the tested API/UI image digests recorded in `runs/2026-10-15-candidates/dograh-runtime.json`. Five native services deployed: API, UI, Postgres/pgvector, Redis, MinIO. No production services were restarted.

- Browser UI: http://127.0.0.1:13010
- API: http://127.0.0.1:18000
- Object storage: http://127.0.0.1:19000
- Speech/Muse shim: http://172.17.0.1:18282/v1, available to native Docker services via `host.docker.internal`.
- Native workflow: ID 1, synthetic livestock intake, local model configuration selected as organization default.

`dograh_speech.py` is a local OpenAI API compatibility shim: `/audio/transcriptions` runs existing CPU Whisper; `/audio/speech` runs existing CPU Kokoro; `/chat/completions` and `/models` proxy local Muse. Dograh's native provider adapters, conversation engine, WebRTC, workflow and UI remain intact. It does not silently use the other benchmark's custom conversation pipeline.

The default Dograh provider is a managed external service, so it was not tested: only OpenRouter is authorized for external speech. Our configuration supplies a local base URL for every inference role and dummy local API key. `ENABLE_TELEMETRY=false` for API/UI; campaign/ARI processes disabled; no Cloudflare profile or public tunnel; no TURN; no Langfuse keys. Postgres/Redis/MinIO remain local Docker volumes. Docker engine stores image layers on NVMe; source, downloadable Python packages and test artifacts are on Seagate. Local JWT/password/token files are protected on NVMe under `~/.local/share/silo-livestock/dograh`, not exFAT.

This setup is **deployed and configured**, not yet proof of a successful browser conversation. See shared benchmark results for the actual browser acceptance test and measured latency. No default-stack speed comparison is claimed.

Deployment logs: `/mnt/seagate/silo/livestock-voice/evidence/dograh-deploy.log`; isolated Compose config: `/mnt/seagate/silo/livestock-voice/dograh/compose-benchmark.yaml`.

Native lifecycle: `./dograh.sh start`, `python3 configure_dograh.py`, `./dograh.sh stop`. The configure script reads the shared questionnaire and creates local model connections, a named pipeline configuration, and the workflow. Browser login credentials are in the private `account.json` file; do not paste them into logs. An initial native UI test revealed a missing `edge.data.condition`; this was repaired, and native interruption was explicitly enabled on the intake node. The Muse proxy preserves native tool-call semantics, so it does not apply the custom direct-answer prompt shortcut used by the other candidate.

Native browser testing found that Dograh hardcodes public Google STUN in both its Python WebRTC configuration and its browser bundle. Initial synthetic tests therefore exposed connection metadata to STUN (not audio/transcripts). `dograh_local_network.py` now removes those public ICE servers in both native components; `dograh.sh start` reapplies the narrowly scoped patch after container creation and restarts the API. Host ICE remains available. This patch does not change Dograh's conversation or speech pipeline. Browser reload is required after applying it.

## Native browser acceptance evidence

The native workflow has now handled actual synthetic microphone audio through its own WebRTC engine, local STT, Muse and Kokoro. Browser screenshots were inspected. Incoming browser audio was recorded independently and retranscribed locally; the recording matches the native assistant transcript. The first test's long silence triggered Dograh's normal inactivity hangup, so the next fixture shortened silence between farmer turns.

`tests/dograh_browser.py` provisions a deterministic microphone WAV, logs native visible transcripts, records received WebRTC audio, and saves screenshots. Evidence is under `runs/dograh-browser-final` and `runs/dograh-browser-multiturn` on Seagate. Native recognition rendered the synthetic name “Ramesh” as “Ramish”; it also split a long caller utterance at pauses. These are observed limitations, not perfect transcript accuracy.

`dograh_bridge.py` explicitly normalizes **post-call** native transcripts and processor timings. The shared benchmark applies local Muse extraction afterward and offers the same export schema. This is an extraction adapter, not a replacement for Dograh voice. Native processor TTFB events are labeled as such and must not be compared directly with browser speech-end-to-audible latency. Shared `/api/dograh/import` selects the latest ended native call. An ended native run is not proof that the farmer confirmed a complete intake; the shared schema preserves that distinction.

The final native multi-turn run (native ID 6) produced 11 transcript entries, including five farmer segments and six assistant responses. The imported schema captured name, village, district, cow/count, symptoms and onset; treatment, warning-sign review and contact remained unanswered, so the call is correctly `ended_unconfirmed`. Received audio capture was 314,480 bytes. An independent local retranscription revealed interrupted partial assistant phrases (“What is…” and an animal/count question) that were absent from the native final transcript. Thus native transcript capture is useful but **not a word-perfect record of interrupted playback**. This is a measured limitation.

The native service logs WebSocket authentication tokens in access-log query strings. A local demo token appeared during early debugging; the isolated benchmark JWT signing secret was rotated, old-token access was verified to return HTTP 401, and fresh private local authentication was issued. Production credentials and services were untouched. Subsequent log inspection redacts token query strings; raw native logs are not committed.

Hosted billing caveat: cancelling/barge-in can stop receipt of the final usage event even if a provider has already generated billable audio. Recorded `observed_cost_usd` totals cover received usage events, not a reconciliation of all cancelled requests against the account ledger.

A subsequent attempt at a complete native intake using an adaptive virtual microphone did **not** complete: recognition lagged the injected utterances and the run did not reach a confirmed summary within the test deadlines. Its evidence is retained under `runs/dograh-browser-complete`; it must not be counted as a completed intake. The earlier native static-microphone multi-turn test remains the successful native voice demonstration.

Final operational check: the native local speech shim was detached into its own process session, with the PID managed by `dograh.sh`. Kokoro ONNX is capped at four CPU threads in this isolated shim. A local PCM speech response returned 91,136 bytes in 0.575 seconds after this change; this is a direct TTS check, not a new end-to-end latency benchmark. Production speech code remains unchanged. Whisper still uses the existing CPU turbo model and is loaded on first request. Fresh browser opens through `/api/dograh/open` were verified on both `localhost` and `127.0.0.1` without manual login; the server sets HTTP-only local demo session cookies.
