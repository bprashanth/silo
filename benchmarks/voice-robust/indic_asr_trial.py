import argparse
import json
import re
import time
from pathlib import Path

import jiwer
import librosa
import numpy as np
import soundfile as sf

import asr_engines
import degrade


FARMER_REPLIES = [
    ("kn_farmer_01", "ನನ್ನ ಎಮ್ಮೆ ಎರಡು ದಿನದಿಂದ ಮೇವು ತಿನ್ನುತ್ತಿಲ್ಲ"),
    ("kn_farmer_02", "ಹಸು ಎದ್ದೇಳುತ್ತಿಲ್ಲ"),
    ("kn_farmer_03", "ಒಂದೇ ಹಸು"),
    ("kn_farmer_04", "ನಿನ್ನೆಯಿಂದ"),
    ("kn_farmer_05", "ನನ್ನ ಹೆಸರು ಬಸವರಾಜು"),
    ("kn_farmer_06", "ಕುಣಿಗಲ್, ತುಮಕೂರು ಜಿಲ್ಲೆ"),
]


def load_audio_16k(path):
    x, sr = sf.read(path, dtype="float32", always_2d=True)
    x = x.mean(1)
    if sr != 16000:
        x = librosa.resample(x, orig_sr=sr, target_sr=16000)
    return np.asarray(x, dtype=np.float32)


def norm_kan(s):
    s = (s or "").strip()
    s = re.sub(r"[^\w\u0C80-\u0CFF\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def summarize(rows):
    groups = {}
    for r in rows:
        if r.get("error"):
            continue
        groups.setdefault((r["engine"], r["condition"]), []).append(r)
    out = []
    for (engine, cond), rs in sorted(groups.items()):
        out.append(
            {
                "engine": engine,
                "condition": cond,
                "n": len(rs),
                "wer": round(float(np.mean([x["wer"] for x in rs])), 4),
                "cer": round(float(np.mean([x["cer"] for x in rs])), 4),
                "p50_ms": round(float(np.percentile([x["ms"] for x in rs], 50)), 1),
                "p95_ms": round(float(np.percentile([x["ms"] for x in rs], 95)), 1),
            }
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tts-dir", default="/mnt/seagate/silo/voice-robust/tts/indic-parler")
    ap.add_argument("--out-json", default="/mnt/seagate/silo/voice-robust/runs/asr/indic-conformer-trial.json")
    args = ap.parse_args()

    tts_dir = Path(args.tts_dir)
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_txt = out_json.with_suffix(".txt")

    engines_to_try = [
        "indic-conformer-kn",
        "indic-conformer-kn-rnnt",
        "parakeet-v3",
    ]

    engines = {}
    load_errors = {}
    for name in engines_to_try:
        try:
            engines[name] = asr_engines.make(name)
        except Exception as e:
            load_errors[name] = str(e)

    rows = []
    conditions = {
        "clean": lambda x, uid: x,
        "farm_phone": lambda x, uid: degrade.CONDITIONS["farm_phone"](x, uid),
    }

    for uid, ref in FARMER_REPLIES:
        wav_path = tts_dir / f"{uid}.wav"
        if not wav_path.exists():
            rows.append(
                {
                    "id": uid,
                    "error": f"missing input wav: {wav_path}",
                }
            )
            continue
        clean = load_audio_16k(wav_path)
        for cond, fn in conditions.items():
            x = fn(clean, f"{uid}.{cond}")
            for engine_name in engines_to_try:
                if engine_name in load_errors:
                    rows.append(
                        {
                            "id": uid,
                            "condition": cond,
                            "engine": engine_name,
                            "error": f"load_error: {load_errors[engine_name]}",
                            "ref": ref,
                            "hyp": "",
                        }
                    )
                    continue
                eng = engines[engine_name]
                try:
                    t0 = time.perf_counter()
                    hyp = eng.transcribe([x])[0]
                    ms = (time.perf_counter() - t0) * 1000.0
                    nref = norm_kan(ref)
                    nhyp = norm_kan(hyp)
                    rows.append(
                        {
                            "id": uid,
                            "condition": cond,
                            "engine": engine_name,
                            "ref": ref,
                            "hyp": hyp,
                            "wer": float(jiwer.wer([nref], [nhyp or "-"])),
                            "cer": float(jiwer.cer([nref], [nhyp or "-"])),
                            "ms": round(ms, 3),
                        }
                    )
                except Exception as e:
                    rows.append(
                        {
                            "id": uid,
                            "condition": cond,
                            "engine": engine_name,
                            "error": str(e),
                            "ref": ref,
                            "hyp": "",
                        }
                    )

    summary = summarize(rows)
    payload = {"rows": rows, "summary": summary, "load_errors": load_errors}
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["IndicConformer Kannada Trial"]
    if load_errors:
        lines.append("Load errors:")
        for k, v in load_errors.items():
            lines.append(f"- {k}: {v}")
    for s in summary:
        lines.append(
            f"{s['engine']:24s} {s['condition']:10s} n={s['n']} "
            f"WER={s['wer']*100:5.1f}% CER={s['cer']*100:5.1f}% p50={s['p50_ms']:7.1f}ms p95={s['p95_ms']:7.1f}ms"
        )
    out_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
