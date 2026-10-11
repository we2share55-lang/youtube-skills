#!/usr/bin/env python3
"""Render reels (1080x1920 mp4) from a plan.json made by plan.py.

  python make_reel.py plan.json outdir [--episode N] [--ref-audio A --ref-text-file T]
                      [--character C.jpg] [--preview]

Pipeline per episode: split narration into sentences -> Qwen3-TTS voice clone (qwen3-tts skill, cached)
-> word timing + mouth envelope -> PIL frames piped to ffmpeg (h264 + aac) -> outdir/reel_XX.mp4
"""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
ASSETS = os.path.join(SKILL, "assets")
TTS_SKILL = os.path.join(os.path.expanduser("~"), ".claude", "skills", "qwen3-tts")

W, H, FPS = 1080, 1920, 30
SR = 24000
MAX_SECONDS = 59.0
LEAD, TAIL, GAP = 0.35, 0.8, 0.22

INK, MUTED = (27, 27, 31), (130, 136, 148)
BLUE, ORANGE, LIGHT, LINE = (47, 107, 255), (255, 138, 61), (243, 245, 249), (226, 230, 238)
FONT_BOLD = ["malgunbd.ttf", "NanumGothicBold.ttf", "AppleGothic.ttf", "NotoSansKR-Bold.otf"]
FONT_REG = ["malgun.ttf", "NanumGothic.ttf", "AppleGothic.ttf", "NotoSansKR-Regular.otf"]


# ---------- helpers ----------
def font(names, size):
    for n in names:
        for d in ("C:/Windows/Fonts", "/usr/share/fonts", "/Library/Fonts", "/System/Library/Fonts"):
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    return ImageFont.load_default()


def ffmpeg_exe():
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg not found (pip install imageio-ffmpeg)")


def read_wav(path):
    with wave.open(path, "rb") as w:
        assert w.getsampwidth() == 2 and w.getnchannels() == 1
        sr = w.getframerate()
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return a, sr


def write_wav(path, a, sr=SR):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())


def split_sentences(text):
    parts = re.findall(r"[^.!?]+[.!?]?", text.replace("\n", " "))
    return [p.strip() for p in parts if p.strip()]


# spoken form for TTS only (subtitles keep the original text). Extend as needed.
PRON = {"ETF": "이티에프", "KODEX": "코덱스", "TIGER": "타이거", "IPO": "아이피오", "KOSPI": "코스피", "KOSDAQ": "코스닥",
        "NASDAQ": "나스닥", "FOMC": "에프오엠씨", "GDP": "지디피", "PER": "피이알", "PBR": "피비알", "ROE": "알오이", "CPI": "씨피아이"}


def tts_text(text):
    for k, v in PRON.items():
        text = text.replace(k, v)
    return text


def sent_id(ep_id, si, ki, text):
    h = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    return f"{ep_id}_s{si}_{ki}_{h}"


def trim_silence(a, thr=0.012):
    idx = np.where(np.abs(a) > thr)[0]
    if len(idx) == 0:
        return a, 0, len(a)
    s, e = max(0, idx[0] - int(0.03 * SR)), min(len(a), idx[-1] + int(0.06 * SR))
    return a[s:e], s, e


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def wrap_words(words, max_chars):
    """greedy wrap list of (word, idx) into lines"""
    lines, cur, n = [], [], 0
    for w in words:
        add = len(w["t"]) + (1 if cur else 0)
        if cur and n + add > max_chars:
            lines.append(cur)
            cur, n = [], 0
            add = len(w["t"])
        cur.append(w)
        n += add
    if cur:
        lines.append(cur)
    return lines


# ---------- TTS ----------
def run_tts(sentences, ttsdir, ref_audio, ref_text_file):
    os.makedirs(ttsdir, exist_ok=True)
    items = [{"id": sid, "text": t} for sid, t in sentences]
    jf = os.path.join(ttsdir, "items.json")
    json.dump(items, open(jf, "w", encoding="utf-8"), ensure_ascii=False)
    py = os.path.join(TTS_SKILL, ".venv", "Scripts", "python.exe")
    if not os.path.exists(py):
        py = os.path.join(TTS_SKILL, ".venv", "bin", "python")
    cmd = [py, os.path.join(TTS_SKILL, "scripts", "tts.py"), "--ref-audio", ref_audio,
           "--ref-text-file", ref_text_file, "--items", jf, "--outdir", ttsdir]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run(cmd, env=env)
    if r.returncode:
        sys.exit("TTS failed")


# ---------- timeline ----------
def build_timeline(ep, ttsdir, ep_id):
    """returns audio (np), scenes[{start,end,sents}], words timing"""
    audio = [np.zeros(int(LEAD * SR), dtype=np.float32)]
    t = LEAD
    scenes = []
    for si, sc in enumerate(ep["scenes"]):
        s_start = t if si == 0 else t
        sents = []
        for ki, text in enumerate(split_sentences(sc["narration"])):
            a = read_wav(os.path.join(ttsdir, sent_id(ep_id, si, ki, text) + ".wav"))[0]
            a, _, _ = trim_silence(a)
            dur = len(a) / SR
            toks = text.split()
            weights = np.array([max(1, len(re.sub(r"[^\w]", "", w))) for w in toks], dtype=float)
            cum = np.concatenate([[0], np.cumsum(weights)]) / weights.sum()
            words = [{"t": w, "a": t + cum[i] * dur, "b": t + cum[i + 1] * dur} for i, w in enumerate(toks)]
            sents.append({"text": text, "a": t, "b": t + dur, "words": words})
            audio.append(a)
            t += dur
            audio.append(np.zeros(int(GAP * SR), dtype=np.float32))
            t += GAP
        scenes.append({"start": s_start, "sents": sents})
    for i, s in enumerate(scenes):
        s["end"] = scenes[i + 1]["start"] if i + 1 < len(scenes) else t
    audio.append(np.zeros(int(TAIL * SR), dtype=np.float32))
    total = t + TAIL
    return np.concatenate(audio), scenes, total


# ---------- video clips (layout B: clip on top, chips below) ----------
CLIP_BOX = (40, 280, W - 40, 850)  # x0, y0, x1, y1 of the clip window
CLIP_W, CLIP_H = CLIP_BOX[2] - CLIP_BOX[0], CLIP_BOX[3] - CLIP_BOX[1]
CHIP_Y = 872


def find_clip(clipsdir, ei, si, sc):
    if not clipsdir:
        return None
    names = [sc["clip"]] if sc.get("clip") else []
    for ext in ("mp4", "mov", "webm", "m4v"):
        names += [f"ep{ei:02d}_scene_{si + 1:02d}.{ext}", f"scene_{si + 1:02d}.{ext}"]
    for n in names:
        p = n if os.path.isabs(n) else os.path.join(clipsdir, n)
        if os.path.exists(p):
            return p
    return None


def clip_duration(path):
    r = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


def load_clip(path, need, focus=0.5):
    """decode a clip to cover CLIP_W x CLIP_H, 30 fps, silent; slowed (<=2x) to fill `need` s, else trimmed. -> uint8 array [n,h,w,3]"""
    dur = clip_duration(path) or need
    f = min(max(need / dur, 1.0), 2.0)
    vf = (f"scale={CLIP_W}:{CLIP_H}:force_original_aspect_ratio=increase,"
          f"crop={CLIP_W}:{CLIP_H}:(iw-{CLIP_W})/2:(ih-{CLIP_H})*{focus:.3f},setpts={f:.4f}*PTS,fps={FPS}")
    cmd = [ffmpeg_exe(), "-loglevel", "error", "-i", path, "-an", "-vf", vf, "-t", f"{need:.3f}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    fs = CLIP_W * CLIP_H * 3
    n = len(raw) // fs
    if n == 0:
        sys.exit(f"could not decode clip: {path}")
    return np.frombuffer(raw[: n * fs], dtype=np.uint8).reshape(n, CLIP_H, CLIP_W, 3)


# ---------- rendering ----------
class Renderer:
    def __init__(self, char_path, ep, ep_idx, ep_total, credit):
        self.ep, self.credit = ep, credit
        self.ep_idx, self.ep_total = ep_idx, ep_total
        self.f_title = font(FONT_BOLD, 54)
        self.f_head = font(FONT_BOLD, 84)
        self.f_hook = font(FONT_BOLD, 96)
        self.f_bul = font(FONT_BOLD, 54)
        self.f_sub = font(FONT_BOLD, 66)
        self.f_small = font(FONT_REG, 30)
        self.f_chk = font(FONT_BOLD, 38)
        ch = Image.open(char_path).convert("RGB")
        self.ch_h = 720
        self.ch = ch.resize((int(ch.width * self.ch_h / ch.height), self.ch_h), Image.LANCZOS)
        self.ch_x, self.ch_y = 24, H - self.ch_h + 30
        self.sx = self.ch.width / ch.width
        self.coin = "coin" in os.path.basename(char_path).lower()
        # mouth anchor in source-image px (photo/caricature face vs. coin face), scaled to the render size
        self.mouth = (int(412 * self.sx), int(648 * self.sx)) if self.coin else (int(400 * self.sx), int(627 * self.sx))
        self.base = self._base()

    def _base(self):
        im = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(im)
        # top pill with episode title
        title = self.ep["title"]
        tw = d.textlength(title, font=self.f_title)
        pw = min(W - 80, tw + 90)
        d.rounded_rectangle((40, 150, 40 + pw, 150 + 96), 48, fill=BLUE)
        d.text((40 + pw / 2, 198), title, font=self.f_title, fill="white", anchor="mm")
        if self.ep_total > 1:
            d.text((W - 48, 198), f"PART {self.ep_idx}/{self.ep_total}", font=self.f_chk, fill=MUTED, anchor="rm")
        # credit
        d.text((W - 40, H - 60), self.credit, font=self.f_small, fill=MUTED, anchor="rm")
        return im

    # card layers per scene (RGBA, in card coordinates)
    CARD = (40, 290, W - 40, 1010)

    def scene_layers(self, sc):
        x0, y0, x1, y1 = self.CARD
        cw, chh = x1 - x0, y1 - y0
        bg = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
        d = ImageDraw.Draw(bg)
        accent = {"hook": ORANGE, "outro": ORANGE}.get(sc["kind"], BLUE)
        d.rounded_rectangle((0, 0, cw, chh), 44, fill=LIGHT, outline=LINE, width=3)
        d.rounded_rectangle((0, 0, 22, chh), 11, fill=accent)
        layers = []
        big = sc["kind"] in ("hook", "outro") or not sc.get("bullets")
        f = self.f_hook if big else self.f_head
        head_lines = self._wrap_px(sc["heading"], f, cw - 120)
        lh = f.size + 14
        if big:
            ty = chh // 2 - lh * len(head_lines) // 2
            for i, ln in enumerate(head_lines):
                d.text((cw // 2, ty + i * lh + lh // 2), ln, font=f, fill=INK, anchor="mm")
            if sc["kind"] == "hook":
                d.text((cw // 2, 70), "?", font=font(FONT_BOLD, 90), fill=accent, anchor="mm")
        else:
            ty = 70
            for i, ln in enumerate(head_lines):
                d.text((70, ty + i * lh), ln, font=f, fill=INK)
            d.rounded_rectangle((70, ty + len(head_lines) * lh + 10, 70 + 160, ty + len(head_lines) * lh + 20), 5, fill=accent)
            by = ty + len(head_lines) * lh + 70
            for b in sc["bullets"]:
                lay = Image.new("RGBA", (cw, 150), (0, 0, 0, 0))
                ld = ImageDraw.Draw(lay)
                ld.ellipse((70, 40, 106, 76), fill=accent)
                lines = self._wrap_px(b, self.f_bul, cw - 230)
                for k, ln in enumerate(lines):
                    ld.text((135, 18 + k * 66), ln, font=self.f_bul, fill=INK)
                layers.append((lay, by))
                by += 66 * len(lines) + 56
        return bg, layers

    def clip_layers(self, sc):
        """layout B overlays: (banner RGBA | None, big-heading chip RGBA | None, [(chip RGBA, x, y)])"""
        accent = {"hook": ORANGE, "outro": ORANGE}.get(sc["kind"], BLUE)
        bullets = sc.get("bullets") or []
        banner = big = None
        chips = []
        if bullets and sc["kind"] == "point":
            f = font(FONT_BOLD, 60)
            lines = self._wrap_px(sc["heading"], f, CLIP_W - 150)
            h = 40 + 70 * len(lines)
            banner = Image.new("RGBA", (CLIP_W - 40, h), (0, 0, 0, 0))
            d = ImageDraw.Draw(banner)
            d.rounded_rectangle((0, 0, banner.width, h), 30, fill=(255, 255, 255, 238), outline=LINE, width=3)
            d.rounded_rectangle((0, 0, 16, h), 8, fill=accent)
            for i, ln in enumerate(lines):
                d.text((44, 20 + i * 70), ln, font=f, fill=INK)
            n = len(bullets)
            cw = (CLIP_W - 20 * (n - 1)) // n
            fs = 42 if n <= 2 else 32
            fb = font(FONT_BOLD, fs)
            wrapped = [self._wrap_px(b, fb, cw - 90) for b in bullets]
            ch = min(150, max(100, 34 + max(len(w) for w in wrapped) * (fs + 12)))
            for i, ls in enumerate(wrapped):
                chip = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                cd = ImageDraw.Draw(chip)
                cd.rounded_rectangle((0, 0, cw, ch), 28, fill=LIGHT, outline=LINE, width=3)
                cd.ellipse((24, ch // 2 - 12, 48, ch // 2 + 12), fill=accent)
                ty = (ch - len(ls) * (fs + 12)) // 2
                for k, ln in enumerate(ls):
                    cd.text((64, ty + k * (fs + 12)), ln, font=fb, fill=INK)
                chips.append((chip, CLIP_BOX[0] + i * (cw + 20), CHIP_Y))
        else:
            f = font(FONT_BOLD, 62)
            lines = self._wrap_px(sc["heading"], f, CLIP_W - 100)[:2]
            big = Image.new("RGBA", (CLIP_W, 140), (0, 0, 0, 0))
            d = ImageDraw.Draw(big)
            d.rounded_rectangle((0, 0, CLIP_W, 140), 36, fill=accent)
            lh = 74
            ty = 70 - lh * len(lines) // 2
            for i, ln in enumerate(lines):
                d.text((CLIP_W // 2, ty + i * lh + lh // 2), ln, font=f, fill="white", anchor="mm")
        return banner, big, chips

    def _wrap_px(self, text, f, maxw):
        d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        lines, cur = [], ""
        for w in text.split():
            t = (cur + " " + w).strip()
            if d.textlength(t, font=f) > maxw and cur:
                lines.append(cur)
                cur = w
            else:
                cur = t
        if cur:
            lines.append(cur)
        return lines or [text]

    def checklist(self, scenes, cur):
        heads = [(i, s) for i, s in enumerate(self.ep["scenes"]) if s["kind"] == "point"]
        if not heads:
            return None
        lay = Image.new("RGBA", (470, 90 * len(heads) + 70), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        d.text((0, 0), "오늘의 핵심", font=self.f_chk, fill=MUTED)
        for k, (i, s) in enumerate(heads):
            y = 64 + k * 90
            on = i == cur
            done = i < cur
            col = BLUE if on else (INK if done else MUTED)
            d.ellipse((0, y + 6, 40, y + 46), fill=BLUE if (on or done) else LINE)
            d.text((20, y + 26), str(k + 1), font=self.f_small, fill="white", anchor="mm")
            d.text((60, y + 26), s["heading"], font=self.f_chk, fill=col, anchor="lm")
        return lay

    def char_frame(self, amp, tsec):
        ch = self.ch.copy()
        d = ImageDraw.Draw(ch)
        mx, my = self.mouth
        if self.coin:
            s = self.sx
            dark = (28, 28, 34)
            if amp > 0.08:
                w, h = int((84 + 60 * amp) * s), int((22 + 84 * amp) * s)
                d.ellipse((mx - w // 2, my - int(6 * s), mx + w // 2, my - int(6 * s) + h), fill=(52, 20, 30), outline=dark, width=max(2, int(5 * s)))
                d.ellipse((mx - w // 4, my - int(6 * s) + h - int(26 * s), mx + w // 4, my - int(6 * s) + h - int(4 * s)), fill=(214, 110, 120))
            else:
                d.arc((mx - int(73 * s), my - int(43 * s), mx + int(73 * s), my + int(43 * s)), 20, 160, fill=dark, width=max(3, int(10 * s)))
        elif amp > 0.08:
            h = int(6 + 34 * amp)
            w = int(46 + 16 * amp)
            d.ellipse((mx - w // 2, my - 6, mx + w // 2, my - 6 + h), fill=(92, 24, 36))
            d.ellipse((mx - w // 4, my - 6 + h - 12, mx + w // 4, my - 6 + h - 2), fill=(214, 110, 120))
        # idle sway + talk bounce (rotate around feet)
        ang = 1.6 * math.sin(tsec * 2.2) + 1.2 * amp * math.sin(tsec * 9)
        sq = 1 + 0.018 * amp
        ch = ch.resize((int(ch.width / sq), int(ch.height * sq)), Image.BILINEAR)
        ch = ch.rotate(ang, resample=Image.BICUBIC, fillcolor=(255, 255, 255), center=(ch.width / 2, ch.height))
        return ch

    def subtitle_img(self, lines, active):
        f = self.f_sub
        d0 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        lh = f.size + 16
        widths = [sum(d0.textlength(w["t"] + " ", font=f) for w in ln) for ln in lines]
        cw = int(max(widths)) + 90
        chh = lh * len(lines) + 50
        im = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((0, 0, cw, chh), 36, fill=(255, 255, 255, 235), outline=LINE, width=3)
        for li, ln in enumerate(lines):
            x = (cw - widths[li]) / 2
            for w in ln:
                col = BLUE if w is active else INK
                d.text((x, 25 + li * lh), w["t"], font=f, fill=col)
                x += d0.textlength(w["t"] + " ", font=f)
        return im


def render_episode(rd, scenes, audio, total, out_mp4, tmp_wav, preview=False, clips=None):
    clips = clips or {}
    clip_cache = {}  # scene index -> frames (only the current scene is kept)
    clip_mask = Image.new("L", (CLIP_W, CLIP_H), 0)
    ImageDraw.Draw(clip_mask).rounded_rectangle((0, 0, CLIP_W, CLIP_H), 40, fill=255)
    clip_ring = Image.new("RGBA", (CLIP_W, CLIP_H), (0, 0, 0, 0))
    ImageDraw.Draw(clip_ring).rounded_rectangle((0, 0, CLIP_W - 1, CLIP_H - 1), 40, outline=LINE, width=4)
    clip_over = {si: rd.clip_layers(rd.ep["scenes"][si]) for si in clips}
    n = int(math.ceil(total * FPS))
    # mouth envelope per frame
    win = int(SR / FPS)
    env = np.array([np.sqrt(np.mean(audio[i * win:(i + 1) * win] ** 2)) if i * win < len(audio) else 0 for i in range(n)])
    p = np.percentile(env[env > 0.003], 90) if (env > 0.003).any() else 1
    env = np.clip(env / (p * 1.1), 0, 1)
    env = np.convolve(env, [0.25, 0.5, 0.25], mode="same")

    # precompute layers
    layers = [rd.scene_layers(sc) for sc in rd.ep["scenes"]]
    checks = [rd.checklist(scenes, i) for i in range(len(scenes))]
    # subtitle chunks
    chunks = []  # (a, b, lines)
    for si, sc in enumerate(scenes):
        for st in sc["sents"]:
            ws = st["words"]
            lines = wrap_words(ws, 13)
            for k in range(0, len(lines), 2):
                grp = lines[k:k + 2]
                flat = [w for ln in grp for w in ln]
                chunks.append({"a": flat[0]["a"], "b": flat[-1]["b"], "lines": grp, "words": flat, "scene": si})
    for i, c in enumerate(chunks):
        nxt = chunks[i + 1]["a"] if i + 1 < len(chunks) else total
        c["b"] = max(c["b"], min(nxt, c["b"] + 0.5))

    write_wav(tmp_wav, audio)
    ff = ffmpeg_exe()
    frames_to_do = range(n)
    if preview:
        frames_to_do = [int(total * FPS * x) for x in (0.05, 0.25, 0.5, 0.8)]
    cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", tmp_wav, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-ar", "48000", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out_mp4]
    proc = None if preview else subprocess.Popen(cmd, stdin=subprocess.PIPE)
    x0, y0, x1, y1 = Renderer.CARD
    for fi in frames_to_do:
        t = fi / FPS
        si = max(i for i, s in enumerate(scenes) if s["start"] <= t) if t >= scenes[0]["start"] else 0
        sc = scenes[si]
        im = rd.base.copy()
        prog = ease_out((t - sc["start"]) / 0.4)
        if si in clips:
            # layout B: video window on top, heading banner on it, keyword chips below
            if si not in clip_cache:
                clip_cache.clear()
                need = sc["end"] - sc["start"] + 0.6
                clip_cache[si] = load_clip(clips[si], need, rd.ep["scenes"][si].get("focus_y", 0.5))
            frames = clip_cache[si]
            fr = Image.fromarray(frames[min(max(0, int((t - sc["start"]) * FPS)), len(frames) - 1)])
            fade = ease_out((t - sc["start"]) / 0.3)
            if fade < 1:
                fr = Image.blend(Image.new("RGB", fr.size, "white"), fr, fade)
            im.paste(fr, (CLIP_BOX[0], CLIP_BOX[1]), clip_mask)
            im.paste(clip_ring, (CLIP_BOX[0], CLIP_BOX[1]), clip_ring)
            banner, big, chips = clip_over[si]
            if banner is not None:
                b = banner.copy()
                b.putalpha(b.getchannel("A").point(lambda v: int(v * prog)))
                im.paste(b, (CLIP_BOX[0] + 20, CLIP_BOX[3] - banner.height - 20 + int(30 * (1 - prog))), b)
            if big is not None:
                g = big.copy()
                g.putalpha(g.getchannel("A").point(lambda v: int(v * prog)))
                im.paste(g, (CLIP_BOX[0], CHIP_Y + int(30 * (1 - prog))), g)
            for bi, (chip, cx, cy) in enumerate(chips):
                ta = sc["start"] + 0.6 + (sc["end"] - sc["start"] - 1.2) * (bi / max(1, len(chips))) * 0.85
                pb = ease_out((t - ta) / 0.35)
                if pb > 0:
                    c2 = chip.copy()
                    c2.putalpha(c2.getchannel("A").point(lambda v: int(v * pb)))
                    im.paste(c2, (cx, cy + int(30 * (1 - pb))), c2)
        else:
            # layout A (default): text card
            bg, bl = layers[si]
            card = bg.copy()
            nb = len(bl)
            for bi, (lay, by) in enumerate(bl):
                ta = sc["start"] + 0.6 + (sc["end"] - sc["start"] - 1.2) * (bi / max(1, nb)) * 0.85
                pb = ease_out((t - ta) / 0.35)
                if pb > 0:
                    tmp = lay.copy()
                    tmp.putalpha(tmp.getchannel("A").point(lambda v: int(v * pb)))
                    card.alpha_composite(tmp, (0, int(by + 30 * (1 - pb))))
            card.putalpha(card.getchannel("A").point(lambda v: int(v * prog)))
            im.paste(card, (x0, y0 + int(40 * (1 - prog))), card)
        # checklist
        ck = checks[si]
        if ck is not None:
            im.paste(ck, (590, 1330), ck)
        # character
        a_idx = min(fi, n - 1)
        cf = rd.char_frame(float(env[a_idx]), t)
        im.paste(cf, (rd.ch_x, rd.ch_y + (rd.ch_h - cf.height)))
        # subtitles
        for c in chunks:
            if c["a"] - 0.05 <= t < c["b"]:
                act = next((w for w in c["words"] if w["a"] <= t < w["b"]), c["words"][-1] if t >= c["words"][-1]["b"] else c["words"][0])
                sub = rd.subtitle_img(c["lines"], act)
                im.paste(sub, ((W - sub.width) // 2, 1040), sub)
                break
        if preview:
            im.save(os.path.join(os.path.dirname(out_mp4), f"preview_{fi}.png"))
        else:
            proc.stdin.write(im.tobytes())
    if proc:
        proc.stdin.close()
        proc.wait()
        if proc.returncode:
            sys.exit("ffmpeg failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("outdir")
    ap.add_argument("--episode", type=int, default=0, help="1-based; 0 = all")
    ap.add_argument("--ref-audio", default=os.path.join(ASSETS, "ref_voice.wav"))
    ap.add_argument("--ref-text-file", default=os.path.join(ASSETS, "ref_voice.txt"))
    ap.add_argument("--character", default=os.path.join(ASSETS, "character_coin.png"))
    ap.add_argument("--clips", default=None, help="folder with scene_01.mp4 ... (layout B: clip on top, chips below)")
    ap.add_argument("--preview", action="store_true", help="only dump a few PNG frames")
    a = ap.parse_args()

    plan = json.load(open(a.plan, encoding="utf-8"))
    os.makedirs(a.outdir, exist_ok=True)
    ttsdir = os.path.join(a.outdir, "tts")
    eps = plan["episodes"]
    credit = f"출처: {plan.get('source_channel', '')}".strip()
    todo = [a.episode] if a.episode else list(range(1, len(eps) + 1))

    # 1) TTS for all needed sentences (one model load)
    sents = []
    for ei in todo:
        for si, sc in enumerate(eps[ei - 1]["scenes"]):
            for ki, t in enumerate(split_sentences(sc["narration"])):
                sents.append((sent_id(f"ep{ei:02d}", si, ki, t), tts_text(t)))
    run_tts(sents, ttsdir, a.ref_audio, a.ref_text_file)

    # 2) render
    for ei in todo:
        ep = eps[ei - 1]
        ep_id = f"ep{ei:02d}"
        audio, scenes, total = build_timeline(ep, ttsdir, ep_id)
        print(f"{ep_id}: {total:.1f}s", flush=True)
        if total > MAX_SECONDS:
            print(f"  !! {total:.1f}s exceeds {MAX_SECONDS}s — shorten narration in plan.json", flush=True)
        rd = Renderer(a.character, ep, ei, len(eps), credit)
        out = os.path.join(a.outdir, f"reel_{ei:02d}.mp4")
        clips = {}
        for si, sc in enumerate(ep["scenes"]):
            p = find_clip(a.clips, ei, si, sc)
            if p:
                clips[si] = p
        if a.clips:
            print(f"  clips: {len(clips)}/{len(ep['scenes'])} scenes use video (others use text cards)", flush=True)
        render_episode(rd, scenes, audio, total, out, os.path.join(a.outdir, f"{ep_id}.wav"), preview=a.preview, clips=clips)
        if not a.preview:
            print("saved", out, flush=True)
            with open(os.path.join(a.outdir, f"reel_{ei:02d}_caption.txt"), "w", encoding="utf-8") as f:
                f.write(ep.get("caption", "") + "\n\n" + " ".join(ep.get("hashtags", [])) + f"\n\n원본: {plan.get('source_url', '')}\n")


if __name__ == "__main__":
    main()
