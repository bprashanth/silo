# Voice benchmark closed; move to asynchronous livestock workflow

The real-time voice experiment remains a benchmark in benchmarks/livestock-voice. Pipecat local used Whisper → Muse → Kokoro with a custom intake controller; Dograh managed its own browser call and two-node workflow through a local compatibility service using the same speech/model components. OpenRouter used hosted audio replies. Measurements and limitations are in RESULTS.md, including question-loop regression evidence and native Dograh tailnet audio checks. Native Dograh full confirmed intake was not established.

At the user's direction, stop extending live-call transcription and implement .prompts/v2_livestock.md: Telegram voice notes, deterministic case lifecycle, human assignment approval, field evidence, independent farmer feedback, and district analytics. No existing usable Idli Ops/Intelligence web app was found in sibling repositories; reuse Silo's Telegram transport, Whisper/Kokoro and local Muse. Databases/private state remain on NVMe; synthetic large test artifacts remain on Seagate.

The requested af_alpha voice is absent from installed Kokoro voices. hf_alpha is the installed Hindi female voice and already Silo's default; use it for the new workflow, including English speech. No model or Telegram service was restarted during discovery.
