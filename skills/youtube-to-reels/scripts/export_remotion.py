#!/usr/bin/env python3
"""Plan -> TTS (cached) -> timeline JSON + normalized audio for the Remotion project.

  python export_remotion.py plan.json outdir --remotion-dir D:/.../reels-remotion [--episode N]

Writes <remotion-dir>/public/<name>.json  (scene/word timings, per-frame mouth amplitude)
       <remotion-dir>/public/<name>.wav   (loudness-normalized narration, 48 kHz mono)
TTS wavs are cached in outdir/tts (same cache as make_reel.py).
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_reel as mr  # noqa: E402

FPS = mr.FPS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("outdir")
    ap.add_argument("--remotion-dir", required=True)
    ap.add_argument("--episode", type=int, default=0)
    ap.add_argument("--name", default="", help="output base name, e.g. 2026-10-11-002 (default reel_epNN)")
    ap.add_argument("--ref-audio", default=os.path.join(mr.ASSETS, "ref_voice.wav"))
    ap.add_argument("--ref-text-file", default=os.path.join(mr.ASSETS, "ref_voice.txt"))
    a = ap.parse_args()

    plan = json.load(open(a.plan, encoding="utf-8"))
    eps = plan["episodes"]
    todo = [a.episode] if a.episode else list(range(1, len(eps) + 1))
    ttsdir = os.path.join(a.outdir, "tts")
    pub = os.path.join(a.remotion_dir, "public")
    os.makedirs(pub, exist_ok=True)

    sents = []
    for ei in todo:
        for si, sc in enumerate(eps[ei - 1]["scenes"]):
            for ki, t in enumerate(mr.split_sentences(sc["narration"])):
                sents.append((mr.sent_id(f"ep{ei:02d}", si, ki, t), mr.tts_text(t)))
    mr.run_tts(sents, ttsdir, a.ref_audio, a.ref_text_file)

    for ei in todo:
        ep = eps[ei - 1]
        ep_id = f"ep{ei:02d}"
        audio, scenes, total = mr.build_timeline(ep, ttsdir, ep_id)
        n = int(np.ceil(total * FPS))
        win = int(mr.SR / FPS)
        env = np.array([np.sqrt(np.mean(audio[i * win:(i + 1) * win] ** 2)) if i * win < len(audio) else 0 for i in range(n)])
        p = np.percentile(env[env > 0.003], 90) if (env > 0.003).any() else 1
        env = np.clip(env / (p * 1.1), 0, 1)
        env = np.convolve(env, [0.25, 0.5, 0.25], mode="same")

        raw = os.path.join(a.outdir, f"{ep_id}_raw.wav")
        mr.write_wav(raw, audio)
        base = a.name or f"reel_{ep_id}"
        out_wav = os.path.join(pub, f"{base}.wav")
        subprocess.run([mr.ffmpeg_exe(), "-y", "-loglevel", "error", "-i", raw, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                        "-ar", "48000", "-ac", "1", out_wav], check=True)

        data = {
            "fps": FPS,
            "total": round(total, 3),
            "frames": n,
            "title": ep["title"],
            "epIdx": ei,
            "epTotal": len(eps),
            "audio": f"{base}.wav",
            "amp": [round(float(x), 2) for x in env],
            "scenes": [
                {
                    "kind": sc["kind"],
                    "heading": sc["heading"],
                    "bullets": sc.get("bullets", []),
                    "art": sc.get("art", ""),
                    "start": round(tl["start"], 3),
                    "end": round(tl["end"], 3),
                    "sents": [
                        {"text": s["text"], "a": round(s["a"], 3), "b": round(s["b"], 3),
                         "words": [{"t": w["t"], "a": round(w["a"], 3), "b": round(w["b"], 3)} for w in s["words"]]}
                        for s in tl["sents"]
                    ],
                }
                for sc, tl in zip(ep["scenes"], scenes)
            ],
        }
        out_json = os.path.join(pub, f"{base}.json")
        json.dump(data, open(out_json, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"{ep_id}: {total:.1f}s -> {out_json}")
        if total > mr.MAX_SECONDS:
            print(f"  !! exceeds {mr.MAX_SECONDS}s")


if __name__ == "__main__":
    main()
