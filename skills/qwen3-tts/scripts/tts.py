#!/usr/bin/env python3
"""Qwen3-TTS voice-clone CLI (CPU ok). Run with the skill's own venv:

  .venv\\Scripts\\python.exe scripts\\tts.py --ref-audio ref.wav --ref-text-file ref.txt \\
      --items items.json --outdir out

items.json = [{"id": "s01", "text": "..."}, ...]  ->  out/<id>.wav  (16-bit PCM, 24 kHz)
Existing outputs are skipped, so reruns are cheap. Single text: --text "..." --out a.wav
"""
import argparse
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref-audio", required=True)
    ap.add_argument("--ref-text", default=None)
    ap.add_argument("--ref-text-file", default=None)
    ap.add_argument("--items", default=None)
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--text", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--language", default="Korean")
    ap.add_argument("--model", default="Qwen/Qwen3-TTS-12Hz-1.7B-Base")
    a = ap.parse_args()

    ref_text = a.ref_text
    if a.ref_text_file:
        ref_text = open(a.ref_text_file, encoding="utf-8").read().strip()
    if not ref_text:
        sys.exit("ref text required (--ref-text or --ref-text-file)")

    if a.items:
        items = json.load(open(a.items, encoding="utf-8"))
        os.makedirs(a.outdir, exist_ok=True)
        jobs = [(i["text"], os.path.join(a.outdir, i["id"] + ".wav")) for i in items]
    elif a.text and a.out:
        jobs = [(a.text, a.out)]
    else:
        sys.exit("give --items/--outdir or --text/--out")

    jobs = [(t, o) for t, o in jobs if not os.path.exists(o)]
    if not jobs:
        print("nothing to do (all cached)")
        return

    import numpy as np
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    t0 = time.time()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.bfloat16 if dev == "cuda" else torch.float32
    model = Qwen3TTSModel.from_pretrained(a.model, device_map=dev, dtype=dtype)
    prompt = model.create_voice_clone_prompt(ref_audio=a.ref_audio, ref_text=ref_text)
    print(f"model ready on {dev} in {time.time() - t0:.0f}s; {len(jobs)} item(s)", flush=True)

    for n, (text, out) in enumerate(jobs, 1):
        t1 = time.time()
        wavs, sr = model.generate_voice_clone(
            text=text, language=a.language, voice_clone_prompt=prompt
        )
        w = np.asarray(wavs[0], dtype=np.float32)
        sf.write(out, w, sr, subtype="PCM_16")
        print(f"[{n}/{len(jobs)}] {len(w) / sr:.1f}s audio in {time.time() - t1:.0f}s -> {out}", flush=True)


if __name__ == "__main__":
    main()
