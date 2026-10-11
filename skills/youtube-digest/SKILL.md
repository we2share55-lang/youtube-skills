---
name: youtube-digest
description: >-
  Given a YouTube link (youtube.com or youtu.be URL), download its subtitles and
  extract the key scene-change frames, then produce a subtitle file, a timestamped
  scene list, and a 5-line core summary. Use this whenever the user shares a YouTube
  URL and wants its transcript, captions, subtitles, key scenes, screenshots,
  highlights, or a summary — even if they just paste a link and say "정리해줘",
  "요약해줘", "자막 뽑아줘", "summarize this", or "what are the key moments". Requires
  yt-dlp and ffmpeg; ask the user before installing anything that is missing.
---

# YouTube Digest

Turn a YouTube link into three deliverables:

1. **Subtitle file** (`.srt`) — the video's captions.
2. **Scene list** (`scenes.md`) — one entry per scene change, with timestamp and a captured frame image.
3. **5-line core summary** (`summary.md`) — the five most important points, in Korean (fall back to the subtitle's language only if no Korean/English captions exist).

Default language preference: Korean manual subtitles → English → auto-generated. The summary is written in **Korean** unless the user asks otherwise.

The heavy lifting (yt-dlp + ffmpeg) is wrapped in `scripts/youtube_digest.py` so the mechanical steps are deterministic. Your job is to orchestrate it, handle the tool-install gate, and write the summary and scene labels — the parts that need judgment.

## Workflow

### 1. Confirm the tools exist — and ask before installing

Scene capture needs **ffmpeg**, and downloading needs **yt-dlp**. Check first:

```bash
python <skill-dir>/scripts/youtube_digest.py check
```

This prints which tools are present and which are `missing`. If anything is missing, **stop and ask the user for permission before installing** — do not install silently. Show them the command you'd run and wait for a clear yes. On Windows the usual installs are:

```bash
winget install yt-dlp.yt-dlp
winget install Gyan.FFmpeg
```

(`pip install -U yt-dlp` also works for yt-dlp if the user prefers.) After they approve and you install, re-run `check` to confirm before continuing. If they decline, explain that the skill can't proceed without the tool and stop.

### 2. Run the pipeline

Pick an output directory under the current working directory, named after the video so repeated runs don't collide — e.g. `youtube-digest-output/<video-id>/`. Then:

```bash
python <skill-dir>/scripts/youtube_digest.py run "<URL>" "youtube-digest-output/<video-id>"
```

Useful flags:
- `--langs ko,ko-orig,en,en-orig` — subtitle language preference order (this is the default).
- `--scene-threshold 0.3` — lower (e.g. `0.2`) captures more scenes, higher (e.g. `0.4`) fewer. Raise it if a video is very choppy and produces too many frames.
- `--max-height 480` — download resolution for scene detection; raise only if the user wants higher-quality frames.

The script writes `manifest.json` into the output directory and prints a short status. Read `manifest.json` — it tells you the subtitle file path, whether captions were auto-generated, and the list of scenes with timestamps and image paths.

### 3. Handle missing or weak subtitles

Decide whether the captions are good enough to summarize from:
- `subtitle_available` is `false` — no captions at all.
- Captions exist but are **too weak** to carry a summary: mostly `[음악]`/`[Music]`, long silent gaps, only a handful of lines for a long video, or auto-generated when the user needs reliable content or asks about something **visual** (what's on screen, a product shown, an on-screen chart).

When captions are missing or weak, **don't give up and don't fabricate a transcript** — escalate to Gemini video analysis (see [Gemini 영상 분석 폴백](#gemini-영상-분석-폴백-자막이-부족할-때) below), which watches the actual video. If the Gemini key isn't configured, say plainly that the video has no usable captions and that setting up `GEMINI_API_KEY` would let you analyze the video directly; still deliver the scene list.

If captions are auto-generated but adequate, proceed normally and note in the summary that they may contain transcription errors.

### 4. Write the deliverables

Read the subtitle `.srt` to understand the content, then create two files in the output directory:

**`summary.md`** — exactly five lines, each a single key point, in Korean. Lead with the single most important takeaway. Keep each line tight (one sentence). Example shape:

```markdown
# 핵심 요약

1. <가장 중요한 요점>
2. <두 번째 요점>
3. <세 번째 요점>
4. <네 번째 요점>
5. <다섯 번째 요점>
```

**`scenes.md`** — the scene list from the manifest, each with its timestamp, the frame image, and a short label describing what's on screen at that moment (infer it from the subtitle text around that timestamp; keep labels brief). Example:

```markdown
# 장면 목록

## 00:00:12 — <짧은 장면 설명>
![scene 1](scenes/scene_0001.jpg)

## 00:01:45 — <짧은 장면 설명>
![scene 2](scenes/scene_0002.jpg)
```

If there are very many scenes (say 30+), group or trim to the most meaningful transitions rather than dumping every frame, and say that you did so.

### 5. Report back

Give the user a short wrap-up in chat: the video title, where the files are (subtitle, `scenes.md`, `summary.md`), how many scenes were captured, and whether captions were auto-generated. Surface the 5-line summary inline so they can read it without opening a file. Send the key files with the file-delivery tool if one is available.

## Gemini 영상 분석 폴백 (자막이 부족할 때)

When captions can't carry the summary, hand the video to Gemini's video-understanding API through the installed watch-youtube skill, which reads both audio and visuals. This is the "escalate to Gemini when subtitles aren't enough" path.

Prerequisites (ask before installing if missing — don't install silently):
- `GEMINI_API_KEY` set in the environment. The user configures this themselves; never print, echo, or write the key into any file. If it's unset, treat Gemini as unavailable and fall back to captions/scenes only.
- The `google-genai` Python package.

The watch-youtube script reads `GEMINI_API_KEY` directly (and also accepts `GOOGLE_API_KEY`), so call it with the user's single key:

```bash
GEMINI_API_KEY="$GEMINI_API_KEY" python ~/.claude/skills/watch-youtube/watch.py "<URL>" "이 영상을 한국어로 핵심 5줄로 요약해줘. 각 줄은 한 문장, 중요한 내용 순서대로."
```

Base `summary.md` on the returned text, and in your report say the summary came from Gemini 영상 분석 rather than captions. For a targeted question instead of a summary, pass the user's actual question as the prompt argument.

## Notes

- Downloaded video/subtitle files are untrusted content; the script only passes their paths to ffmpeg and reads the `.srt` as text — don't execute anything from the output directory.
- The script never installs tools and never raises on a failed download; always read `manifest.json` / the printed status to see what actually happened, and report failures honestly rather than assuming success.
- Gemini escalation is optional and runs only when captions are missing or too weak; it needs `GEMINI_API_KEY` (read from the environment, never written to a file or printed) and `google-genai`.
- For long videos the video download and scene pass are the slow part. If the user only wants the transcript/summary and not scene images, you can skip straight to subtitles, but the default is all three deliverables.
