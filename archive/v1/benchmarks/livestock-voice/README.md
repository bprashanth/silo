# Livestock voice benchmark

Question: can an isolated browser voice intake collect a fictional farmer's report with conversational response latency, using local Pipecat, self-hosted Dograh, or hosted speech-to-speech?

## Try the call

Open **http://127.0.0.1:8765** on the demonstration machine. Select a backend, click **Call**, allow microphone access, and say “My cow is sick.” Headphones help avoid acoustic feedback when testing interruptions. Click **End call** to save the transcript and intake record, then use the export buttons.

For the existing Tailscale connection, open **http://100.82.28.38:8765**. Dograh opens **http://100.82.28.38:13010/workflow/1** from the backend selector. For microphone testing over plain HTTP in Chrome, enable `chrome://flags/#unsafely-treat-insecure-origin-as-secure` with both origins, comma-separated: `http://100.82.28.38:8765,http://100.82.28.38:13010`, then relaunch Chrome. This is a development browser exception; no HTTPS or Tailscale Serve is configured. The servers bind to all interfaces.

OpenRouter is explicitly non-private: use fictional information only. Its API receives a complete audio utterance and streams its spoken reply; it is not a native realtime audio session. The local option uses continuous WebRTC microphone audio, Silero turn detection, Whisper, Muse and Kokoro. No telephone call or veterinarian dispatch occurs.

```sh
benchmarks/livestock-voice/setup.sh       # first install
benchmarks/livestock-voice/start.sh       # preloads speech models
benchmarks/livestock-voice/start.sh stop
```

Production Telegram services are untouched. Existing Muse must be running at `http://127.0.0.1:8181`. Edit `questionnaire.json` to change intake instructions and required fields.

## Storage and dependencies

- Experiment dependencies, source downloads, audio fixtures, recordings and resource logs: `/mnt/seagate/silo/livestock-voice/`.
- Small Python launcher, call state and server logs: `~/.local/share/silo-livestock-voice/`. exFAT cannot provide venv symlinks or private file permissions.
- Existing speech weights: `~/.local/share/idli-bridge/models/`, linked to Seagate.
- OpenRouter key remains server-side in `~/.config/idlisseus/openrouter.json`; override its location with `LIVESTOCK_OPENROUTER_CONFIG`. No key is sent to the browser.
- Pipecat 1.12.0, SmallWebRTC/aiortc, Silero ONNX VAD, faster-whisper CPU int8, Kokoro ONNX CPU, aiohttp and FastAPI. ARM64 / NVIDIA GB10 discovery is in `runs/2026-10-15-discovery/environment.json`.

## Test protocol

Use the same synthetic farmer WAVs across candidates. The browser test's fixture mode routes WAV audio into a MediaStream and through WebRTC, VAD and recognition; it does not inject transcript text. Record the remote spoken audio, inspect the transcript and fields, and capture screenshots. Synthetic TTS-to-ASR results must be distinguished from human microphone, accent and noise tests.

Compare missing information, out-of-order facts, correction, unknown answers, urgency, interruption and confirmed completion. Do not mark completion merely because the browser connected or displayed text.

Latency should distinguish server first-audio generation from browser received-audio onset. The latter includes transport and buffering but is still an analyser-based playback estimate, not a physical speaker measurement. Raw events retain monotonic timestamps; percentile summaries should only combine comparable non-interrupted turns. Background services share the GPU, so this environment is not an exclusive clean baseline.

```sh
python3 benchmarks/livestock-voice/record_resources.py --seconds 300 \
  --output /mnt/seagate/silo/livestock-voice/runs/manual/resources.jsonl
```

`nvidia-smi` reports utilization and per-process GPU allocations, but total device memory is unsupported on this unified-memory hardware. Unavailable measurements must remain marked unavailable.

## Candidate behavior and testing

Dograh opens its native workflow in another tab from the common selector. Click **Run Test** there. After ending that call, return here and click **Import latest Dograh call** for the shared structured schema and export. Dograh retains its own voice engine; the shared record is explicitly a post-call local extraction adapter. Its UI and API are on ports 13010 and 18000. See [CANDIDATES.md](CANDIDATES.md) for the isolated deployment and data flow.

```sh
benchmarks/livestock-voice/dograh.sh start
# Configure the isolated native workflow on a fresh installation:
PYTHONPATH=/mnt/seagate/silo/livestock-voice/packages \
  ~/.local/share/silo-livestock-voice/venv/bin/python benchmarks/livestock-voice/configure_dograh.py
benchmarks/livestock-voice/dograh.sh stop
```

See [tests/README.md](tests/README.md) for the real-audio browser tests and human testing instructions. [test_intake.py](test_intake.py) covers negation, corrections, unknown answers, confirmation and interrupted recognition without model calls.

The local experiment adds evidence-based urgency checks, preserves a caller fragment when speech resumes during transcription, and uses a deterministic field-backed summary/confirmation step because Muse repeatedly ignored the requested summary. Missing-field follow-ups and extraction still use Muse. These controller changes are part of this candidate, not native Pipecat features. Interrupted transcript entries are labelled audio-queued/possibly partially played; they cannot guarantee word-perfect speaker alignment.

## Results

See [RESULTS.md](RESULTS.md) for measured comparisons, failures retained from earlier revisions, and recommendations. Large raw audio and screenshots remain on Seagate; selected small synthetic records are copied under `runs/` for review.
