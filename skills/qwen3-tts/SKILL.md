---
name: qwen3-tts
description: Korean/multilingual text-to-speech with voice cloning from a short reference clip, using Qwen3-TTS (runs on CPU or GPU). Use when the user wants narration/TTS audio in a cloned voice, e.g. as the voice stage of youtube-to-reels.
---

# Qwen3-TTS (voice clone)

Model: `Qwen/Qwen3-TTS-12Hz-1.7B-Base` (cached in `~/.cache/huggingface`, downloaded on first use).
The skill's own venv (`.venv`, not committed) holds `qwen-tts`, `torch`, `soundfile`.
On CPU expect roughly 10 s of compute per 1 s of speech.

## Reference voice
3–15 s of clean single-speaker audio + its exact transcript. Only clone a voice the user owns or has permission to use.

## Usage
```powershell
$py = "$HOME\.claude\skills\qwen3-tts\.venv\Scripts\python.exe"
& $py "$HOME\.claude\skills\qwen3-tts\scripts\tts.py" --ref-audio ref.wav --ref-text-file ref.txt --text "안녕하세요" --out out.wav
# batch (cached by file existence):
& $py "$HOME\.claude\skills\qwen3-tts\scripts\tts.py" --ref-audio ref.wav --ref-text-file ref.txt --items items.json --outdir out
```
`items.json`: `[{"id":"s01","text":"..."}]` -> `out/s01.wav` (16-bit PCM, 24 kHz).

## Setup on a new PC
```powershell
python -m venv "$HOME\.claude\skills\qwen3-tts\.venv"
& "$HOME\.claude\skills\qwen3-tts\.venv\Scripts\pip.exe" install qwen-tts soundfile
```
(Install a CUDA torch build instead of the CPU one if there is an NVIDIA GPU.)
