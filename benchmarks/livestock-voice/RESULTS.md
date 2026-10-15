# Livestock voice POC results — 15 October 2026

This is a synthetic English browser benchmark on a shared DGX Spark. The test uses locally generated farmer speech through a browser MediaStream/WebRTC connection and records actual incoming agent audio. It does not validate human microphone accents, noisy field conditions, Hindi or Kannada. Earlier failed runs remain available alongside later fixes.

The useful default is the isolated Pipecat page at http://127.0.0.1:8765. The hosted option is explicitly non-private. Dograh opens its independent native interface; its transcript can be imported afterward into the shared schema.

## Measurement scope

Browser response timing uses a single monotonic clock: last non-silent sample of the farmer fixture to detected non-silent incoming agent audio. It includes transport/buffering, but not physical speaker or sound-card delay. Server first-audio enqueue is a separate measurement. OpenRouter API TTFB is a third, different scope. Native Dograh processor TTFB must not be compared directly with browser end-to-end timing.

The final local batch comprises three confirmed calls (runs08–10), 15 received-audio samples, and 10/10 expected fields per call. Local p50 **1671 ms**, p90 **2203.6 ms**, p95 **2239.8 ms** (linear interpolation). Two of each five turns are the controlled summary/completion; these are complete voice-stack timings, not pure Muse generation measurements. [Local summaries](runs/local-final-summary.json). Hosted final runs01–03 also completed, with 15 samples: p50 **2541 ms**, p90 **3601.6 ms**, p95 **3675.8 ms**. Observed costs were **$0.0037866 / $0.003396 / $0.003336**, averaging **$0.0035062 per call**. [Hosted summaries](runs/hosted-final-summary.json). Small samples are descriptive, not production SLAs. GPU and CPU measurements include existing unrelated services. There is no exclusive idle-machine baseline. Connection setup/buffering subcomponents, per-turn full audible-response duration, isolated per-candidate CPU/GPU consumption, and corpus word-error rate were not separately measured. Recordings and raw timestamps permit further analysis; these missing measurements are not treated as zero.

## Final comparison

| Metric | Native Dograh | Local Pipecat | OpenRouter audio |
|---|---|---|---|
| Browser spoken exchange | Yes, native UI | Yes, shared page | Yes, shared page |
| Confirmed full intake | Not achieved in automated attempt | 3/3 final calls | 3/3 final calls |
| Browser response p50 | Unmeasured | 1.671s | 2.541s |
| Browser response p90 | Unmeasured | 2.204s | 3.602s |
| Browser response p95 | Unmeasured | 2.240s | 3.676s |
| Correct fields | 6/10 in partial run6; name misheard, 3 missing | 10/10 each final call | 10/10 each final call, reviewed first record |
| Transcript quality | Native partial-interruption omissions; Ramesh→Ramish | Clear final fixtures; noisy sample imperfect | Provider output transcript; local ASR for caller display |
| Interruption | Native partial speech observed; stop latency unmeasured | Greeting stop about167ms | Shared local greeting stop about150ms |
| GPU | Shared existing Muse,27090MiB allocation | Same shared Muse allocation | Cloud inference unmeasured; local Muse used for record extraction |
| Observed API cost/call | $0 local inference | $0 local inference | Mean$0.0035062 |
| Setup/operation | High: native containers plus adapter | Moderate: one benchmark server, existing models | Low additional adapter complexity; shared local infrastructure remains |
| Inference/audio privacy | Local, after telemetry/tunnel/STUN changes | Local | Explicitly non-private |

Interruption timings are approximate single browser RMS measurements, not percentile estimates. Both tests interrupted the shared Kokoro greeting; they do **not** establish interruption latency during hosted model output. Full interrupted-word alignment and echo-heavy human duplex behavior remain unverified. The next spoken response after interruption was 1906 ms locally and 2407 ms hosted in those short tests. The final post-restart local retest again stopped audio in 167 ms, responded in 1624 ms, and correctly marked the greeting as interrupted/possibly partially played.

## Before/after and retained failures

- Large-v3-turbo CPU local baseline: first browser response **6641 ms**, ASR **4632 ms**. Isolated base.en reduced the comparable first browser response to **1640 ms**, ASR **317 ms**. This single-turn comparison is about a 75% reduction in perceived delay, not a claim about the whole-call distribution.
- Local04: audio worked, but urgency classification and confirmation failed. It repeated a question already answered.
- Local05–07: urgency and field extraction improved; repeated questions and missing-name recognition still prevented confirmation. These calls are not counted as successful completed intakes.
- Root edge test: noisy hesitation audio was recognized imperfectly. The exact correction was initially recognized but lost in extraction. The rerun correctly records **two days ago** and retains the caller quote; three browser latency samples were **1796, 2065, 2026 ms**. This deliberately incomplete call remains `ended_unconfirmed`.
- Hosted01: actual five-turn speech-to-speech completed, all ten required topics addressed, urgent review flagged and summary confirmed. Browser samples **3638, 3764, 3057, 2977, 2738 ms**; observed billed usage **$0.0037866**. This is a complete-call observation, unlike the shorter catalog smoke test.
- Native Dograh: genuine native browser audio/transcription and relevant follow-ups verified. Long utterances split at pauses; the two-utterance test became five farmer and six assistant transcript entries. Native full-intake automation did not reach confirmation. Its processor timings are not an end-to-end percentile result. A native transcript also omitted some interrupted partial phrases that were audible in the recording.

## Changes made after testing

Local inference stays separate from production Telegram. Models are preloaded. Whisper base.en is isolated on Seagate. Muse's existing final-channel template avoids hidden reasoning. First response sentences go into Kokoro while later text is generated; structured extraction runs after speech generation so it does not delay the first spoken response.

Turn handling preserves pending caller PCM when speech resumes during recognition, rather than discarding a clause at a pause. Incoming speech cancels queued agent audio. Transcript metadata distinguishes generated/queued text and potentially partially played interrupted text. Exact spoken word alignment is not claimed.

The intake controller applies explicit-evidence warning classification, preserves unknowns and latest corrections, tracks already answered topics, and uses a field-backed summary/confirmation step because Muse did not reliably obey that request. These guards are part of this experimental implementation. Human review remains necessary; no diagnosis, prescription or real dispatch occurs.

End call immediately stops the microphone and speaker while final extraction saves. Completed records are sent to a mock local completion endpoint. Fields, provenance, transcript, latency stages and observed hosted usage are exported together. Native Dograh retains its own conversation implementation and uses the shared extractor only after the call.

## Resources, cost and deployment

The host is aarch64 / NVIDIA GB10, driver580.159.03 / CUDA13.0. Existing shared Muse reported **27090 MiB per-process GPU allocation**. Device total-memory counters are unsupported on this unified-memory platform. Whisper/Kokoro run on CPU. [Resource observations](runs/resource-summary.json) include whole-host CPU and memory; attribution to individual candidates is unmeasured. Electricity and hardware amortization are unmeasured. Local inference has no per-call API charge.

First local audio test arrived about eight minutes after starting implementation; a complete hosted browser call was measured about sixteen minutes after start. These are wall-clock milestones during parallel development, not reproducible clean-install times. Native Dograh deployment/configuration took approximately ten minutes, with subsequent integration and audio testing additional. Pipecat has one application process plus existing Muse; native Dograh has API/UI/Postgres/Redis/MinIO plus the local speech compatibility service, making it operationally heavier.

Only the hosted candidate sends test speech to OpenRouter. Catalog discovery and exact rates are in [CANDIDATES.md](CANDIDATES.md). Observed usage is recorded, not inferred from audio length. Local candidate audio/inference stay on the machine. Native Dograh telemetry and public tunnels are disabled; default public STUN was discovered and patched out before its local-network tests. Package/image/model downloads during setup require the internet.

## Recommendation and limits

- **Immediate English demo:** use the shared page; prefer the local option for privacy and the hosted option when conversational consistency matters more than its approximately three-second response delay. The final local batch completed three synthetic calls with 10/10 fields each; that is a useful demo baseline, not proof of real-user robustness.
- **Self-hosted production direction:** Pipecat fits the existing services with fewer components. This POC still needs real-user testing, stronger recognition across accents/noise, measured duplex echo handling, and broader conversation validation before production.
- **Conversational experience:** hosted audio followed the intake more consistently in the tested calls. Dograh offers a native workflow editor, but its full completion and latency comparison are not established here.
- **Lowest marginal API cost:** local Pipecat or native local Dograh; local hardware/energy cost is not measured. Hosted cost was small in these synthetic calls, but it is not private.
- **Additional Indian languages:** no tested winner. A modular Pipecat speech pipeline is configurable, but changing language/model lists is not evidence of language quality. Test each language with human speakers before choosing a stack.

## Final verification

15 focused regression tests pass. Three final local calls and three hosted calls completed with the expected fields; actual non-silent remote audio was captured. Final server restart activated idempotent completion saves, followed by a successful real-audio interruption retest. The desktop Chromium window is open with a real microphone path (no fake microphone flags); live human testing remains for the user. No production Telegram service was restarted.

## Evidence

Small synthetic raw records: [runs/2026-10-15-browser](runs/2026-10-15-browser/). Large audio, screenshots, raw resources, dependency cache and downloaded sources: `/mnt/seagate/silo/livestock-voice/`. Final user call state is private on NVMe in `~/.local/share/silo-livestock-voice/`. Test scripts and protocol: [tests/README.md](tests/README.md).
