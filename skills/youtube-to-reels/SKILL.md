---
name: youtube-to-reels
description: Turn a YouTube URL into one or more vertical (1080x1920, <=60 s) Instagram Reels mp4 files plus a cover image and caption — key points picked by Gemini, narrated in a cloned voice (qwen3-tts), rendered with Remotion (cartoon illustrations, coin character, word-highlight subtitles). Use when the user gives a YouTube link and wants reels/shorts made from it. Long videos become several reels.
---

# YouTube → Reels (Remotion)

Output per video (in the Remotion project's `out/`): `YYYY-MM-DD-NNN.mp4`, `..._thumbnail.png`, `..._caption.txt`. Instagram upload is NOT automated yet (see "Not included").

## Requirements
- `GEMINI_API_KEY`; `pip install google-genai pillow numpy imageio-ffmpeg faster-whisper`; `yt-dlp`; Node 20+
- `qwen3-tts` skill with its `.venv` (CPU ok, ~10 s compute per 1 s of speech)
- Remotion project `reels-remotion/` (`npm i`) + the official Remotion agent skills: `npx skills add remotion-dev/skills -g -a claude-code -y`
- **Reference voice (not in the repo, user's own voice only):** put `ref_voice.wav` (3–15 s, clean) and `ref_voice.txt` (exact transcript) into `assets/`. Never publish a voice sample.
- Optional character images in `assets/` (`character_coin.png` is included).

## Steps
1. **Plan** — Gemini picks the key points and splits long videos into episodes:
   `python scripts/plan.py "<url>" work/plan.json [--episodes N] [--no-enrich] [--focus "topic"]`
   The planner may add easy analogies (marked as examples) but must not invent facts or numbers. Review/edit `plan.json` (narration ≤ ~380 chars per episode; each scene has `heading`, `bullets`, `narration`, `art`).
2. **Voice + timing** (TTS cached by sentence text):
   `python scripts/export_remotion.py work/plan.json work/out --remotion-dir <reels-remotion> --name YYYY-MM-DD-NNN`
3. **Art** — each `art` id maps to a hand-coded SVG scene in `reels-remotion/src/Illustrations.tsx` (+ `ART_BG` color in `theme.ts`). New topic → add a component and register it in `ART`.
4. **Register** a `<Composition id="Reel-YYYY-MM-DD-NNN" ... defaultProps={{ file: "YYYY-MM-DD-NNN.json", timeline: null }}>` and a `Thumb-...` composition in `src/Composition.tsx`.
5. **Preview/render** (close any media player that has the old mp4 open — Windows locks it):
   `npx remotion studio` or `npx remotion render src/index.ts Reel-<name> out/<name>.mp4`
   Cover: `npx remotion still src/index.ts Thumb-<name> out/<name>_thumbnail.png --frame=110`
6. Write `<name>_caption.txt` (body + hashtags + "AI voice / not investment advice" notice).

## Notes
- Earlier PIL renderer (`scripts/make_reel.py`) still works as a fallback and holds the shared timeline code used by `export_remotion.py`.
- Keep content educational; don't claim a buyback/dividend guarantees price moves.
- Only clone a voice the user owns or has permission for; label uploads as AI voice.

## Not included
Instagram auto-upload. An older project (`myparang_marketing_instagram`) uses the Instagram API (Instagram Login): `graph.instagram.com/v21.0/<IG_USER_ID>/media` with `media_type=REELS` + public `video_url`, then `media_publish`. A new account needs its own token and user id (kept in a local `.env`, never committed).
