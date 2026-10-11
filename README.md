# youtube-skills

Claude Code용 **유튜브 읽기 · 음성 · 릴스 제작** 스킬 모음. 어떤 주제의 프로젝트 폴더에서든 `~/.claude/skills/`에 설치해 두면 그대로 쓸 수 있습니다.
(경제 공부 릴스 프로젝트는 별도 저장소 `moneystudy`에 있습니다.)

## 스킬

| 스킬 | 설명 |
|------|------|
| [`skills/watch-youtube`](skills/watch-youtube) | Gemini 영상 이해 API로 유튜브 영상을 분석(요약·타임스탬프·Q&A). 일시적 오류는 재시도하고, 끝내 실패하면 자막만 읽는 폴백(경고 표시). |
| [`skills/youtube-digest`](skills/youtube-digest) | 유튜브 링크 → 자막·핵심 장면·5줄 요약. |
| [`skills/youtube-to-reels`](skills/youtube-to-reels) | 유튜브 링크 → 60초 이내 세로 릴스 + 썸네일 + 캡션 (Gemini 기획, 복제 음성, Remotion 렌더). |
| [`skills/qwen3-tts`](skills/qwen3-tts) | Qwen3-TTS 음성 복제(CPU 가능) CLI. |
| [`skills/value-investing-coach`](skills/value-investing-coach) | 버핏식 가치투자 관점의 교육용 비서. |
| `skills/notion-*` (4개) | Notion 연동 문서화·리서치·회의·스펙 스킬. |

## 요구사항

- Python: `google-genai`, `youtube-transcript-api` (릴스 제작은 `pillow`, `numpy`, `imageio-ffmpeg`, `faster-whisper` 추가)
- 환경변수: `GEMINI_API_KEY` (키 값은 저장소에 커밋하지 말 것)
- 릴스 제작: Node 20+, Remotion 프로젝트(`moneystudy/reels-remotion`), `npx skills add remotion-dev/skills -g -a claude-code -y`

## 설치 / 동기화

- 다른 PC: `git clone` → `.\install-skills.ps1` (남은 준비물 안내가 출력됩니다)
- 스킬을 고친 뒤: `.\sync-skills.ps1` (`~/.claude/skills` → 저장소 복사 → 커밋 → push)

## 저장소에 일부러 넣지 않은 것 (공개 저장소)

- **참조 음성**(`ref_voice.wav/txt`)과 **원본 캐릭터 사진**: 본인 자료는 각 PC에서 직접 `skills/youtube-to-reels/assets/`에 넣습니다.
- API 키, 인스타그램 토큰 등 비밀값.

## 환경 변수로 조절하는 값

- `WATCH_RETRIES`(기본 5), `WATCH_RETRY_WAIT`(기본 20초): 영상 분석 중 일시적 Gemini 오류 재시도.