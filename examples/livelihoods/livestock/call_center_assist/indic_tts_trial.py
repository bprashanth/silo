import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from transformers import AutoTokenizer


EN_AGENT_PROMPTS = [
    "Namaste, this is the livestock helpline. Please tell me, what happened to your animal?",
    "Which animal is sick?",
    "Is the buffalo able to stand up?",
    "Please say the phone number slowly, digit by digit.",
    "One second, writing it down.",
]

KN_AGENT_PROMPTS = [
    "ನಮಸ್ಕಾರ, ಇದು ಪಶು ಸಹಾಯವಾಣಿ. ದಯವಿಟ್ಟು ಹೇಳಿ, ನಿಮ್ಮ ಪ್ರಾಣಿಗೆ ಏನಾಯಿತು?",
    "ಯಾವ ಪ್ರಾಣಿ ಅಸ್ವಸ್ಥವಾಗಿದೆ?",
    "ಎಮ್ಮೆ ಎದ್ದು ನಿಲ್ಲಲು ಆಗುತ್ತಿದೆಯಾ?",
    "ದಯವಿಟ್ಟು ಫೋನ್ ನಂಬರನ್ನು ನಿಧಾನವಾಗಿ, ಅಂಕೆ ಅಂಕೆಯಾಗಿ ಹೇಳಿ.",
    "ಒಂದು ಕ್ಷಣ, ನಾನು ಬರೆಯುತ್ತಿದ್ದೇನೆ.",
]

KN_FARMER_REPLIES = [
    "ನನ್ನ ಎಮ್ಮೆ ಎರಡು ದಿನದಿಂದ ಮೇವು ತಿನ್ನುತ್ತಿಲ್ಲ",
    "ಹಸು ಎದ್ದೇಳುತ್ತಿಲ್ಲ",
    "ಒಂದೇ ಹಸು",
    "ನಿನ್ನೆಯಿಂದ",
    "ನನ್ನ ಹೆಸರು ಬಸವರಾಜು",
    "ಕುಣಿಗಲ್, ತುಮಕೂರು ಜಿಲ್ಲೆ",
]


def _device_arg(raw):
    if raw:
        return raw
    return "cuda" if torch.cuda.is_available() else "cpu"


def _load_desc_tokenizer(model, local_model_dir):
    src = model.config.text_encoder._name_or_path
    try:
        return AutoTokenizer.from_pretrained(src, local_files_only=True)
    except Exception:
        try:
            return AutoTokenizer.from_pretrained(src)
        except Exception:
            return AutoTokenizer.from_pretrained(str(local_model_dir), local_files_only=True)


def run_parler(model_dir, out_dir, device):
    from parler_tts import ParlerTTSForConditionalGeneration

    out_dir.mkdir(parents=True, exist_ok=True)
    model = ParlerTTSForConditionalGeneration.from_pretrained(
        str(model_dir),
        local_files_only=True,
        torch_dtype=torch.float16 if device.startswith("cuda") else torch.float32,
    ).to(device).eval()
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
    desc_tokenizer = _load_desc_tokenizer(model, model_dir)

    # Warm-up once so per-utterance measurements are warm timings.
    d = "Mary is a female speaker with a clear, warm voice, moderate pace, very clear audio."
    p = "Warm up."
    d_ids = desc_tokenizer(d, return_tensors="pt").to(device)
    p_ids = tokenizer(p, return_tensors="pt").to(device)
    with torch.inference_mode():
        _ = model.generate(
            input_ids=d_ids.input_ids,
            attention_mask=d_ids.attention_mask,
            prompt_input_ids=p_ids.input_ids,
            prompt_attention_mask=p_ids.attention_mask,
        )
    if device.startswith("cuda"):
        torch.cuda.synchronize()

    jobs = []
    for i, text in enumerate(EN_AGENT_PROMPTS, 1):
        jobs.append(
            (
                f"eng_agent_{i:02d}",
                text,
                "Mary is a female speaker with a clear, warm voice, moderate pace, very clear audio.",
                "english_agent",
                "Mary",
            )
        )
    for i, text in enumerate(KN_AGENT_PROMPTS, 1):
        jobs.append(
            (
                f"kn_agent_{i:02d}",
                text,
                "Anu is a female Kannada speaker with a clear, warm voice, moderate pace, very clear audio.",
                "kannada_agent",
                "Anu",
            )
        )
    for i, text in enumerate(KN_FARMER_REPLIES, 1):
        jobs.append(
            (
                f"kn_farmer_{i:02d}",
                text,
                "Suresh is a male Kannada speaker with a clear, natural voice, moderate pace, very clear audio.",
                "kannada_farmer",
                "Suresh",
            )
        )

    rows = []
    sr = int(model.config.sampling_rate)
    for uid, text, desc, group, speaker in jobs:
        d_ids = desc_tokenizer(desc, return_tensors="pt").to(device)
        p_ids = tokenizer(text, return_tensors="pt").to(device)
        if device.startswith("cuda"):
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        with torch.inference_mode():
            wav = model.generate(
                input_ids=d_ids.input_ids,
                attention_mask=d_ids.attention_mask,
                prompt_input_ids=p_ids.input_ids,
                prompt_attention_mask=p_ids.attention_mask,
            )
        if device.startswith("cuda"):
            torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        audio = wav.detach().float().cpu().numpy().squeeze()
        audio = np.asarray(audio, dtype=np.float32)
        path = out_dir / f"{uid}.wav"
        sf.write(path, audio, sr)
        sec = len(audio) / float(sr)
        rows.append(
            {
                "engine": "indic-parler-tts",
                "id": uid,
                "group": group,
                "speaker": speaker,
                "text": text,
                "description": desc,
                "wav": str(path),
                "sample_rate": sr,
                "audio_seconds": round(sec, 3),
                "synth_seconds": round(dt, 3),
                "rtf": round(dt / max(sec, 1e-6), 3),
                "peak_mem_mb": round(
                    (torch.cuda.max_memory_allocated() / (1024 * 1024)) if device.startswith("cuda") else 0.0,
                    1,
                ),
            }
        )
    return rows


def run_kokoro(kokoro_python, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "prompts": EN_AGENT_PROMPTS,
        "out_dir": str(out_dir),
    }
    code = r"""
import json, time
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
from kokoro import KPipeline

payload = json.loads(input())
prompts = payload["prompts"]
out_dir = Path(payload["out_dir"])
out_dir.mkdir(parents=True, exist_ok=True)

device = "cuda" if torch.cuda.is_available() else "cpu"
tts = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device=device)
_ = list(tts("Warm up.", voice="hf_alpha", speed=0.95))
if device == "cuda":
    torch.cuda.synchronize()

rows = []
for i, text in enumerate(prompts, 1):
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
    t0 = time.perf_counter()
    parts = [r.audio for r in tts(text, voice="hf_alpha", speed=0.95)]
    wav = torch.cat(parts).detach().cpu().numpy() if parts else np.zeros(2400, dtype=np.float32)
    if device == "cuda":
        torch.cuda.synchronize()
    dt = time.perf_counter() - t0
    uid = f"eng_agent_{i:02d}"
    path = out_dir / f"{uid}.wav"
    sf.write(path, wav.astype(np.float32), 24000)
    sec = len(wav) / 24000.0
    rows.append({
        "engine": "kokoro-hf_alpha",
        "id": uid,
        "group": "english_agent",
        "speaker": "hf_alpha",
        "text": text,
        "wav": str(path),
        "sample_rate": 24000,
        "audio_seconds": round(sec, 3),
        "synth_seconds": round(dt, 3),
        "rtf": round(dt / max(sec, 1e-6), 3),
        "peak_mem_mb": round((torch.cuda.max_memory_allocated() / (1024 * 1024)) if device == "cuda" else 0.0, 1),
    })
print(json.dumps(rows))
"""
    p = subprocess.run(
        [str(kokoro_python), "-c", code],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env=os.environ.copy(),
    )
    if p.returncode != 0:
        raise RuntimeError(f"Kokoro benchmark failed (code {p.returncode}):\n{p.stderr}")
    return json.loads(p.stdout)


def write_index(root, parler_rows, kokoro_rows):
    by_id_parler = {r["id"]: r for r in parler_rows}
    by_id_kokoro = {r["id"]: r for r in kokoro_rows}

    lines = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'><title>Indic TTS Trial</title>",
        "<style>body{font-family:sans-serif;margin:24px} table{border-collapse:collapse;width:100%} td,th{border:1px solid #ccc;padding:8px;vertical-align:top} audio{width:280px}</style>",
        "</head><body>",
        "<h1>Indic Parler-TTS vs Kokoro</h1>",
        "<h2>English Agent Prompts (side-by-side)</h2>",
        "<table><tr><th>ID</th><th>Text</th><th>Indic Parler-TTS</th><th>Kokoro hf_alpha</th></tr>",
    ]
    for i, text in enumerate(EN_AGENT_PROMPTS, 1):
        uid = f"eng_agent_{i:02d}"
        p = by_id_parler[uid]["wav"]
        k = by_id_kokoro[uid]["wav"]
        pr = os.path.relpath(p, root)
        kr = os.path.relpath(k, root)
        lines.append(
            f"<tr><td>{uid}</td><td>{text}</td>"
            f"<td><audio controls src='{pr}'></audio></td>"
            f"<td><audio controls src='{kr}'></audio></td></tr>"
        )
    lines += ["</table>", "<h2>Kannada Agent Prompts (Indic Parler-TTS)</h2>", "<table><tr><th>ID</th><th>Text</th><th>Audio</th></tr>"]
    for i, text in enumerate(KN_AGENT_PROMPTS, 1):
        uid = f"kn_agent_{i:02d}"
        p = by_id_parler[uid]["wav"]
        pr = os.path.relpath(p, root)
        lines.append(f"<tr><td>{uid}</td><td>{text}</td><td><audio controls src='{pr}'></audio></td></tr>")
    lines += ["</table>", "<h2>Kannada Farmer Replies (Indic Parler-TTS)</h2>", "<table><tr><th>ID</th><th>Text</th><th>Audio</th></tr>"]
    for i, text in enumerate(KN_FARMER_REPLIES, 1):
        uid = f"kn_farmer_{i:02d}"
        p = by_id_parler[uid]["wav"]
        pr = os.path.relpath(p, root)
        lines.append(f"<tr><td>{uid}</td><td>{text}</td><td><audio controls src='{pr}'></audio></td></tr>")
    lines += ["</table>", "</body></html>"]
    (root / "index.html").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default="/mnt/seagate/silo/voice-robust/models/indic-parler-tts")
    ap.add_argument("--out-root", default="/mnt/seagate/silo/voice-robust/tts")
    ap.add_argument("--device", default="")
    ap.add_argument("--kokoro-python", default=str(Path.home() / ".local/share/silo-voice/venv/bin/python"))
    args = ap.parse_args()

    model_dir = Path(args.model_dir)
    out_root = Path(args.out_root)
    out_parler = out_root / "indic-parler"
    out_kokoro = out_root / "kokoro"
    out_root.mkdir(parents=True, exist_ok=True)

    device = _device_arg(args.device)
    parler_rows = run_parler(model_dir, out_parler, device)
    kokoro_rows = run_kokoro(Path(args.kokoro_python), out_kokoro)
    write_index(out_root, parler_rows, kokoro_rows)

    out = {
        "device": device,
        "parler_model_dir": str(model_dir),
        "parler": parler_rows,
        "kokoro": kokoro_rows,
    }
    (out_root / "trial_metrics.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({"parler_rows": len(parler_rows), "kokoro_rows": len(kokoro_rows), "out_root": str(out_root)}))


if __name__ == "__main__":
    main()
