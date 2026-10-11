#!/usr/bin/env python3
"""YouTube digest helper: download subtitles and extract scene-change frames.

This script does only the *deterministic* media work with yt-dlp and ffmpeg.
Claude handles the parts that need judgment (the 5-line summary, scene labels).

Subcommands
-----------
  check                 Report whether yt-dlp and ffmpeg are available.
  run <url> <outdir>    Download subtitles + video, extract scene frames,
                        and write <outdir>/manifest.json describing everything.

The script never installs anything. If a tool is missing, `check` reports it
so the caller can ask the user for permission before installing.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys


def have(tool):
    """Return the resolved path to a tool on PATH, or None."""
    return shutil.which(tool)


def cmd_check(_args):
    status = {
        "yt_dlp": have("yt-dlp"),
        "ffmpeg": have("ffmpeg"),
        "ffprobe": have("ffprobe"),
    }
    missing = [k for k, v in status.items() if not v]
    print(json.dumps({"status": status, "missing": missing}, indent=2))
    # Exit non-zero if anything required is missing so callers can branch on it.
    return 1 if ("yt-dlp" in [m.replace("_", "-") for m in missing]
                 or not status["ffmpeg"]) else 0


def run(cmd, **kwargs):
    """Run a command, returning CompletedProcess. Never raises on non-zero."""
    return subprocess.run(cmd, text=True, capture_output=True, **kwargs)


def download_subtitles(url, outdir, langs):
    """Try to fetch the best available subtitle track.

    Preference order is: manual subs in the requested languages, then
    auto-generated subs in those languages. Returns a dict describing what
    was found, or None if no subtitles exist at all.
    """
    sub_template = os.path.join(outdir, "subtitle.%(ext)s")
    lang_arg = ",".join(langs)

    # First pass: manual (human) subtitles only.
    manual = run([
        "yt-dlp", "--skip-download", "--write-subs",
        "--sub-langs", lang_arg, "--convert-subs", "srt",
        "-o", sub_template, url,
    ])
    found = find_subtitle_file(outdir)
    if found:
        return {"file": found, "auto_generated": False, "log": manual.stderr[-2000:]}

    # Second pass: fall back to auto-generated captions.
    auto = run([
        "yt-dlp", "--skip-download", "--write-auto-subs",
        "--sub-langs", lang_arg, "--convert-subs", "srt",
        "-o", sub_template, url,
    ])
    found = find_subtitle_file(outdir)
    if found:
        return {"file": found, "auto_generated": True, "log": auto.stderr[-2000:]}

    return {"file": None, "auto_generated": None,
            "log": (manual.stderr + "\n" + auto.stderr)[-2000:]}


def find_subtitle_file(outdir):
    """Return the first .srt (preferred) or .vtt file in outdir, else None."""
    srts = [f for f in os.listdir(outdir) if f.endswith(".srt")]
    if srts:
        return os.path.join(outdir, sorted(srts)[0])
    vtts = [f for f in os.listdir(outdir) if f.endswith(".vtt")]
    if vtts:
        return os.path.join(outdir, sorted(vtts)[0])
    return None


def fetch_metadata(url):
    """Return (title, duration_seconds, video_id) from yt-dlp, best effort."""
    res = run(["yt-dlp", "--skip-download", "--print",
               "%(title)s\n%(duration)s\n%(id)s", url])
    lines = [l for l in res.stdout.splitlines() if l.strip()]
    title = lines[0] if len(lines) > 0 else "unknown"
    try:
        duration = float(lines[1]) if len(lines) > 1 else None
    except ValueError:
        duration = None
    vid = lines[2] if len(lines) > 2 else "video"
    return title, duration, vid


def download_video(url, outdir, max_height):
    """Download a modest-resolution copy for scene detection. Returns path."""
    out_template = os.path.join(outdir, "video.%(ext)s")
    run([
        "yt-dlp",
        "-S", f"res:{max_height}",
        "--merge-output-format", "mp4",
        "-o", out_template, url,
    ])
    vids = [f for f in os.listdir(outdir)
            if f.startswith("video.") and not f.endswith(".json")]
    return os.path.join(outdir, sorted(vids)[0]) if vids else None


def hms(seconds):
    s = int(round(seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def extract_scenes(video, outdir, threshold):
    """Capture a frame at each scene change. Returns a list of scene dicts.

    Uses ffmpeg's scene-detection score: a frame passes when the visual
    difference from the previous one exceeds `threshold` (0-1; ~0.3 is a
    good default). `showinfo` prints the timestamp of every frame that
    passes, in the same order the images are written, so we zip them.
    """
    scenes_dir = os.path.join(outdir, "scenes")
    os.makedirs(scenes_dir, exist_ok=True)
    pattern = os.path.join(scenes_dir, "scene_%04d.jpg")

    res = run([
        "ffmpeg", "-hide_banner", "-i", video,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-vsync", "vfr", "-q:v", "3", pattern,
    ])

    # showinfo lines look like: "... pts_time:12.345 ..."
    times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", res.stderr)]
    images = sorted(f for f in os.listdir(scenes_dir) if f.endswith(".jpg"))

    scenes = []
    for i, img in enumerate(images):
        t = times[i] if i < len(times) else None
        scenes.append({
            "index": i + 1,
            "timestamp_seconds": t,
            "timestamp": hms(t) if t is not None else None,
            "image": os.path.join("scenes", img),
        })
    return scenes


def cmd_run(args):
    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)

    missing = [t for t in ("yt-dlp", "ffmpeg") if not have(t)]
    if missing:
        print(json.dumps({"error": "missing_tools", "missing": missing}))
        return 2

    langs = [l.strip() for l in args.langs.split(",") if l.strip()]

    title, duration, vid = fetch_metadata(args.url)
    subs = download_subtitles(args.url, outdir, langs)
    video = download_video(args.url, outdir, args.max_height)

    scenes = []
    scene_error = None
    if video:
        scenes = extract_scenes(video, outdir, args.scene_threshold)
    else:
        scene_error = "video_download_failed"

    manifest = {
        "url": args.url,
        "video_id": vid,
        "title": title,
        "duration_seconds": duration,
        "duration": hms(duration) if duration else None,
        "subtitle_file": subs["file"],
        "subtitle_auto_generated": subs["auto_generated"],
        "subtitle_available": subs["file"] is not None,
        "video_file": video,
        "scene_threshold": args.scene_threshold,
        "scene_count": len(scenes),
        "scenes": scenes,
        "scene_error": scene_error,
        "output_dir": outdir,
    }
    manifest_path = os.path.join(outdir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "manifest": manifest_path,
        "subtitle_available": manifest["subtitle_available"],
        "subtitle_auto_generated": manifest["subtitle_auto_generated"],
        "scene_count": manifest["scene_count"],
        "scene_error": scene_error,
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="Report tool availability.")

    r = sub.add_parser("run", help="Download subs + extract scenes.")
    r.add_argument("url")
    r.add_argument("outdir")
    r.add_argument("--langs", default="ko,ko-orig,en,en-orig",
                   help="Comma-separated subtitle language preference order.")
    r.add_argument("--scene-threshold", type=float, default=0.3,
                   help="ffmpeg scene-change score threshold, 0-1 (default 0.3).")
    r.add_argument("--max-height", type=int, default=480,
                   help="Preferred max video height for scene detection.")

    args = parser.parse_args()
    if args.command == "check":
        sys.exit(cmd_check(args))
    elif args.command == "run":
        sys.exit(cmd_run(args))


if __name__ == "__main__":
    main()
