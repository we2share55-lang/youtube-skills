#!/usr/bin/env python3
"""YouTube URL -> reels plan JSON (key points split into <=60 s episodes) via Gemini.

  python plan.py "<youtube_url>" plan.json [--model gemini-3.5-flash] [--episodes N]
"""
import argparse
import json
import math
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

# Korean TTS ~8 chars/s incl. spaces -> keep narration well under 60 s
MAX_CHARS_PER_EPISODE = 380

ENRICH = """- 학습용이므로 영상 내용을 더 쉽게 이해시키는 '쉬운 비유·일상 예시'를 추가해도 좋다(예: 숫자가 작은 가상의 생활 예시).
  단, 예시는 반드시 '예를 들어', '쉽게 말해'처럼 예시임을 밝히고, 영상에 없는 통계·역사적 사실·실제 수치는 지어내지 마라.
  핵심 정의와 개념은 영상 내용에 충실하고, 각 포인트는 '정의 → 쉬운 예시' 순서로 설명하라.
"""

PROMPT = """너는 유튜브 영상을 인스타그램 릴스(세로, 60초 이내)로 재구성하는 기획자다.
첨부된 영상(길이 약 {minutes:.1f}분)에서 '중요하다고 판단되는 핵심 내용' 위주로 릴스 {n_hint}를 기획해라.

규칙:
- 영상이 길면 주제 단위로 나눠 여러 편(episodes)으로 만든다. 한 편은 하나의 완결된 주제/교훈이어야 한다.
  권장 편 수: {n_rule}. 인사·광고·잡담·반복은 버리고 정보 밀도가 높은 부분만 쓴다.
- 편마다 narration 전체 글자 수(공백 포함)는 {max_chars}자 이하. (TTS로 읽으면 약 45~50초)
- 편 구성: scene 1개는 후킹(kind="hook", 시청자가 멈추게 하는 질문/반전 한 문장, 50자 이내),
  핵심 포인트 scene 3~4개(kind="point"), 마지막 정리 scene 1개(kind="outro", 한 줄 요약 + 행동 유도).
{enrich}- 말투는 친근한 존댓말(~해요/~예요). 원 영상 진행자인 척하지 말고 '이 영상에서는', '영상에 따르면'처럼 요약자 시점.
  원 영상에 없는 수치·사실을 지어내지 마라.
- narration은 TTS가 그대로 읽는다: 숫자는 한글 발음이 자연스럽게(예: '10만 원'), 영어 약어는 한글 발음 병기 가능, 이모지·괄호·특수문자 금지.
  문장은 짧게(한 문장 40자 이내), 마침표로 끝낸다.
- heading: 화면 카드 제목(14자 이내). bullets: 화면에 뜰 핵심 키워드 문구 2~3개(각 18자 이내, 마침표 없음).
  hook/outro는 bullets를 비워도 된다.
- title: 편 제목(20자 이내). caption: 인스타 캡션 본문(2~3문장) + hashtags 5~8개.

JSON만 출력:
{{"source_url": "...", "episodes": [
  {{"title": "...", "caption": "...", "hashtags": ["#..."],
    "scenes": [{{"kind": "hook|point|outro", "heading": "...", "bullets": ["..."], "narration": "..."}}]}}
]}}
"""


RETRIES = int(os.environ.get("WATCH_RETRIES", "6"))
RETRY_WAIT = float(os.environ.get("WATCH_RETRY_WAIT", "20"))


def is_transient(err):
    s = str(err).lower()
    if any(k in s for k in ("high demand", "overloaded", "try again later", "deadline_exceeded", "timed out", "timeout")):
        return True
    return any(code in s for code in ("503", "502", "504", "500 internal", "429", "resource_exhausted"))


def generate_with_retry(client, **kwargs):
    """Wait out temporary Gemini errors instead of failing (the plan must come from the real video)."""
    for attempt in range(RETRIES + 1):
        try:
            return client.models.generate_content(**kwargs)
        except Exception as e:  # noqa: BLE001
            if attempt >= RETRIES or not is_transient(e):
                raise
            wait = RETRY_WAIT * (attempt + 1)
            print(f"temporary Gemini error ({type(e).__name__}); retry {attempt + 1}/{RETRIES} in {wait:.0f}s", flush=True)
            time.sleep(wait)


def video_info(url):
    try:
        out = subprocess.run(
            ["yt-dlp", "--skip-download", "--no-warnings", "--print",
             "%(duration)s\t%(channel)s\t%(title)s", url],
            capture_output=True, text=True, encoding="utf-8", timeout=90,
        ).stdout.strip().splitlines()[-1].split("\t")
        return float(out[0]), out[1], out[2]
    except Exception:
        return 0.0, "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--model", default="gemini-3.5-flash")
    ap.add_argument("--episodes", type=int, default=0, help="force episode count")
    ap.add_argument("--no-enrich", action="store_true", help="use only the video's own content (no extra examples)")
    ap.add_argument("--focus", default="", help="optional topic hint, e.g. '금리와 환율'")
    a = ap.parse_args()

    dur, channel, title = video_info(a.url)
    minutes = dur / 60 if dur else 8.0
    if a.episodes:
        n_hint, n_rule = f"정확히 {a.episodes}편", f"정확히 {a.episodes}편"
    else:
        lo = max(1, math.ceil(minutes / 6))
        hi = min(10, max(lo, math.ceil(minutes / 3)))
        n_hint = "여러 편" if hi > 1 else "1편"
        n_rule = f"{lo}~{hi}편 (영상 약 4~6분당 1편, 짧은 영상은 1편)"

    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY not set")
    client = genai.Client(api_key=key)
    prompt = PROMPT.format(minutes=minutes, n_hint=n_hint, n_rule=n_rule, max_chars=MAX_CHARS_PER_EPISODE,
                           enrich="" if a.no_enrich else ENRICH)
    if a.focus:
        prompt += f"\n주제 힌트: {a.focus} 중심으로 고를 것.\n"
    if a.episodes == 1 and minutes > 8:
        prompt += "\n영상이 길지만 이번에는 1편만 만든다: 전체에서 가장 중요하고 기초가 되는 한 주제를 골라라.\n"
    resp = generate_with_retry(
        client,
        model=a.model,
        contents=types.Content(parts=[
            types.Part(file_data=types.FileData(file_uri=a.url)),
            types.Part(text=prompt),
        ]),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    plan = json.loads(resp.text)
    if isinstance(plan, list):  # model sometimes returns the bare episode list
        plan = {"episodes": plan[0]["episodes"] if plan and "episodes" in plan[0] else plan}
    plan["source_url"] = a.url
    plan["source_channel"] = channel
    plan["source_title"] = title

    for i, ep in enumerate(plan["episodes"], 1):
        total = sum(len(s["narration"]) for s in ep["scenes"])
        flag = "" if total <= MAX_CHARS_PER_EPISODE else "  !! OVER BUDGET"
        print(f"episode {i}: {ep['title']} ({len(ep['scenes'])} scenes, {total} chars){flag}")
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print("saved", a.out)


if __name__ == "__main__":
    main()
