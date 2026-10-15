# Livestock browser voice benchmark started

Read `.prompts/INTEGRATIONS.md` and `.prompts/v1_livestock.md`; implementing an isolated experiment in `benchmarks/livestock-voice/` on branch `poc/livestock-voice`. Production Telegram services are unchanged.

Discovery: local Muse health responds at `127.0.0.1:8181`; architecture is aarch64, GPU is NVIDIA GB10, driver 580.159.03 / CUDA 13.0. Existing Whisper and Kokoro weights are reusable. Seagate has 3.2 TB available. Dependencies, downloaded sources, audio fixtures and large test artifacts go under `/mnt/seagate/silo/livestock-voice/`.

Raw discovery: [environment.json](../benchmarks/livestock-voice/runs/2026-10-15-discovery/environment.json). GPU has existing unrelated workloads, so these measurements are not an exclusive clean-machine baseline. `nvidia-smi` does not expose total device memory on this unified-memory hardware; per-process accounting is available.

Browser plugin discovery returned no available browsers; use standalone Playwright Chromium for synthetic audio tests, then open a local browser tab for user testing. Synthetic microphone fixtures cannot substitute for a human accent/noise assessment.
