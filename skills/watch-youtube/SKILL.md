---
name: watch-youtube
description: Watch and analyze YouTube videos using Gemini's video understanding API. Pass any YouTube URL to get summaries, timestamps, Q&A, or detailed analysis of video content — audio and visual.
---

# Watch YouTube

Use Google's Gemini API to actually *watch* YouTube videos and answer questions about them.

## How It Works

Gemini processes both audio and visual streams of YouTube videos at 1 FPS. You pass a URL + prompt, it returns analysis.

## When to Use

- User shares a YouTube URL and wants a summary, transcript, or analysis
- User asks "what did they say about X in this video?"
- User wants timestamps of key moments
- User wants to compare multiple videos (up to 10 per request with Gemini 2.5+)

## When NOT to Use

- Private or unlisted videos (only public videos work)
- User just wants the video link or metadata

## Setup

Requires `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) environment variable. Get one free at https://aistudio.google.com/apikey

## Usage

Run the script:
```bash
GEMINI_API_KEY="$GEMINI_API_KEY" python3 ~/.claude/skills/watch-youtube/watch.py "<youtube_url>" "<prompt>"
```

### Examples

**Summarize:**
```bash
watch.py "https://www.youtube.com/watch?v=VIDEO_ID" "Summarize this video in 5 bullet points"
```

**Timestamps:**
```bash
watch.py "https://www.youtube.com/watch?v=VIDEO_ID" "List the key moments with timestamps"
```

**Q&A:**
```bash
watch.py "https://www.youtube.com/watch?v=VIDEO_ID" "What tools or products did they mention?"
```

**Specific section:**
```bash
watch.py "https://www.youtube.com/watch?v=VIDEO_ID" "What happens at 05:30?" 
```

## Limits

- **Free tier:** 8 hours of YouTube video per day
- **Paid tier:** No limit
- **Max videos per request:** 10 (Gemini 2.5+)
- **Max video length:** ~1 hour (1M context), ~3 hours (low res)
- **~300 tokens per second** of video

## Models

- `gemini-3.5-flash` — default; fast, good for most use cases
- `gemini-3.1-pro-preview` — deeper analysis, longer videos
- Note: `gemini-2.5-flash` / `gemini-2.5-pro` are no longer available to new users (return 404) — use the 3.x models above.

## Fallback: Transcript Mode

If Gemini fails (quota exceeded, video too long, API key missing), the script automatically falls back to fetching the YouTube transcript via `youtube_transcript_api`.

**What the fallback does:**
1. Extracts the video ID from the URL
2. Fetches the auto-generated captions with timestamps
3. Returns the full transcript as text with your original prompt

**What you get back:** Raw timestamped transcript — the calling agent should read and answer the prompt from that text. Gemini-level visual/audio analysis is not available in fallback mode.

**Limitations of fallback:**
- No visual analysis (can't describe what's on screen)
- No answers about non-speech content
- Requires the video to have auto-generated or manual captions
- Private/unlisted videos without captions will fail entirely

**When fallback triggers:**
- Gemini quota exceeded (429 / RESOURCE_EXHAUSTED)
- Video exceeds context window (>1M tokens / ~1hr)
- `GOOGLE_API_KEY` not set
- Any other Gemini API error containing: quota, token, context, too long, exceeds

## Retries and fallback

- Temporary Gemini errors (503 overload, 429 rate limit, 500/502/504, timeouts) are **retried** with growing waits (default 5 retries, 20 s x attempt; env WATCH_RETRIES, WATCH_RETRY_WAIT) so the real video + audio gets analyzed.
- Only after the retries are used up (or for non-temporary errors such as quota/long video/unsupported) does the script fall back to the **transcript only** and prints a loud warning that the video was NOT analyzed. Treat transcript-only results as lower fidelity (auto captions, possibly translated).
