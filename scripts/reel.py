#!/usr/bin/env python3
"""Original reels for the pages.

WHY
---
The Arabic page was posting videos downloaded from X and Telegram - other
people's footage. For a page that wants to be a portfolio and to be
 monetised, redistributed footage is the wrong material: it is not
original, it is not what the brand is, and the platform's own originality
policy treats a channel built on it as a strike risk.

So: the reel is GENERATED. Three designed scenes on a slow Ken Burns
pan, a spoken voiceover from Gemini TTS in the page's own language, and
burned-in subtitles timed to the audio. No footage, no licensing, no
stock, and it matches the card design exactly.

Requires: Pillow, requests, and an ffmpeg with libx264 + aac.
imageio-ffmpeg provides a full static build (the one bundled with
Playwright is a stripped screen-recording build and cannot encode).
"""
from __future__ import annotations

import base64
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    import card_design as cd
except Exception as e:  # noqa: BLE001
    cd = None
    print(f"WARNING: card_design not importable: {e}", file=sys.stderr)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VW, VH = 1080, 1920
FPS = 30

# Gemini TTS voices that read Arabic and English well
VOICE = {"en": "Kore", "ar": "Fenrir"}
TTS_MODEL = "gemini-3.8-flash-tts"
TTS_FALLBACK = "gemini-2.5-flash-preview-tts"


# ---------------------------------------------------------------- ffmpeg
def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    for p in (r"C:\Program Files\imageio_ffmpeg\binaries",
              r"C:\Users\Abdelli\AppData\Local\ms-playwright"):
        for f in Path(p).rglob("ffmpeg*.exe"):
            return str(f)
    raise RuntimeError("no ffmpeg found (pip install imageio-ffmpeg)")


# ---------------------------------------------------------------- tts
def _keys() -> list:
    keys = [k.strip() for k in os.getenv("GEMINI_API_KEYS", "").split(",") if k.strip()]
    if os.getenv("GEMINI_API_KEY", "").strip():
        keys.append(os.getenv("GEMINI_API_KEY").strip())
    return list(dict.fromkeys(keys))


def speak(text: str, lang: str = "en") -> bytes:
    """Text -> WAV bytes via Gemini TTS. Returns b"" on failure."""
    import requests
    if not text.strip():
        return b""
    for model in (TTS_MODEL, TTS_FALLBACK):
        for k in _keys():
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
                    f":generateContent?key={k}",
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": text}]}],
                          "generationConfig": {
                              "responseModalities": ["AUDIO"],
                              "speechConfig": {"voiceConfig": {
                                  "prebuiltVoiceConfig": {
                                      "voiceName": VOICE.get(lang, "Kore")}}},
                          }},
                    timeout=120)
                d = r.json() or {}
                if d.get("error"):
                    continue
                part = d["candidates"][0]["content"]["parts"][0]
                data = part.get("inlineData") or {}
                raw = base64.b64decode(data.get("data") or "")
                if not raw:
                    continue
                if "wav" in (data.get("mimeType") or ""):
                    return raw
                # raw PCM (L16, 24 kHz) -> wrap it in a WAV header
                return _pcm_to_wav(raw, 24000, 1, 2)
            except Exception as e:  # noqa: BLE001
                print(f"  tts {model}: {type(e).__name__}", file=sys.stderr)
                continue
    return b""


def _pcm_to_wav(pcm: bytes, rate: int, channels: int, width: int) -> bytes:
    import struct
    data_len = len(pcm)
    header = b"RIFF" + struct.pack("<I", 36 + data_len) + b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 1, channels, rate,
                          rate * channels * width, channels * width, width * 8)
    header += b"data" + struct.pack("<I", data_len)
    return header + pcm


# ---------------------------------------------------------------- the script
SCRIPT_SYSTEM = {
    "en": ("Write a 2-sentence VOICEOVER for a 12-second vertical reel about a "
           "market or AI story. Spoken English, plain, no emoji, no hashtags, no "
           "'subscribe'/'like'. The first sentence states the fact and the number. "
           "The second says what it means for a normal person. Output only the "
           "two sentences, nothing else."),
    "ar": ("اكتب جملتين للتعليق الصوتي في فيديو عمودي مدته 12 ثانية عن خبر في "
           "الأسواق أو الذكاء الاصطناعي. لهجة عربية فصحى مبسطة، بدون إيموجي "
           "ولا هاشتاغ ولا 'شارك'. الجملة الأولى فيها الخبر والرقم. الثانية "
           "تقول ماذا يعني هذا لشخص عادي. الجملتين فقط، بدون شيء آخر."),
}


def voiceover_script(post_text: str, lang: str = "en", llm=None) -> str:
    """A short spoken script. Falls back to the post's first lines."""
    if llm:
        try:
            out = llm(SCRIPT_SYSTEM[lang], f"Post:\n{post_text[:700]}")
            out = (out or "").strip()
            out = re.sub(r"^[\"'`]|[\"'`]$", "", out)
            out = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", "", out)
            if len(out) > 20:
                return out[:400]
        except Exception as e:  # noqa: BLE001
            print(f"  script: {type(e).__name__}", file=sys.stderr)
    lines = [ln.strip() for ln in (post_text or "").split("\n") if ln.strip()]
    return " ".join(lines[:2])[:300]


# ---------------------------------------------------------------- scenes
def _scene_brand(brand: str, topic: str, tag: str) -> Image.Image:
    b = cd.BRANDS.get(brand, cd.BRANDS["ethan"])
    img = cd._gradient((VW, VH), b["bg_top"], b["bg_bot"])
    d = ImageDraw.Draw(img)
    glow = Image.new("RGB", (VW, VH), b["bg_bot"])
    gd = ImageDraw.Draw(glow)
    gd.ellipse((VW - 700, -400, VW + 400, 700), fill=b["accent"])
    glow = glow.filter(ImageDraw.__class__ and __import__("PIL.ImageFilter",
                                                          fromlist=["ImageFilter"])
                       .GaussianBlur(220))
    img = Image.blend(img, glow, 0.18)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, VW, 10), fill=b["accent"])
    f = cd._font(96, bold=True)
    if b["lang"] == "ar":
        fa = cd._arabic_font(96, bold=True)
        w1 = cd._text_size(d, cd.ar(b["word"]), fa)[0]
        w2 = cd._text_size(d, cd.ar(b["word2"]), fa)[0]
        x = VW - 90 - (w1 + w2 + 12)
        d.text((x, 120), cd.ar(b["word2"]), font=fa, fill=b["text"])
        d.text((x + w2 + 12, 120), cd.ar(b["word"]), font=fa, fill=b["accent"])
    else:
        w1 = cd._text_size(d, b["word"], f)[0]
        d.text((90, 120), b["word"], font=f, fill=b["text"])
        d.text((90 + w1 + 12, 120), b["word2"], font=f, fill=b["accent"])
    fp = cd._font(42, bold=True)
    tw = cd._text_size(d, tag, fp)[0] + 60
    d.rounded_rectangle((90, 290, 90 + tw, 360), radius=35, outline=b["accent"], width=3)
    d.text((120, 302), tag, font=fp, fill=b["accent"])
    return img


def _scene_number(brand: str, num: str, direction: int, headline: str,
                   lang: str) -> Image.Image:
    b = cd.BRANDS.get(brand, cd.BRANDS["ethan"])
    img = cd._gradient((VW, VH), b["bg_top"], b["bg_bot"])
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, VW, 10), fill=b["accent"])
    ar_page = cd.is_arabic(headline)
    if num:
        fn = cd._font(300, bold=True)
        while cd._text_size(d, num, fn)[0] > VW - 200 and fn.size > 120:
            fn = cd._font(fn.size - 8, bold=True)
        if direction:
            d.text((80, 470), ("▲" if direction > 0 else "▼"),
                   font=cd._font(90, bold=True), fill=b["accent"])
            d.text((200, 470), num, font=fn, fill=b["accent"])
        else:
            d.text((90, 470), num, font=fn, fill=b["accent"])
    if headline:
        fh = cd._fit(d, headline if not ar_page else cd.ar(headline), VW - 180, 74,
                     bold=True, arabic=ar_page, min_size=44)
        y = 900 if num else 560
        for ln in cd._wrap(d, headline if not ar_page else cd.ar(headline), fh,
                           VW - 180)[:5]:
            d.text((90, y), ln, font=fh, fill=b["text"])
            y += 86
    return img


def _scene_end(brand: str, cta: str, strip: str, lang: str) -> Image.Image:
    b = cd.BRANDS.get(brand, cd.BRANDS["ethan"])
    img = cd._gradient((VW, VH), b["bg_top"], b["bg_bot"])
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, VW, 10), fill=b["accent"])
    f = cd._font(58, bold=True)
    y = 780
    for ln in cd._wrap(d, cta, f, VW - 180)[:4]:
        d.text((90, y), ln, font=f, fill=b["text"])
        y += 78
    d.rectangle((90, y + 30, 990, y + 34), fill=b["accent"])
    fs = cd._font(28, bold=True)
    cd._letterspace(d, 90, y + 80, strip, fs, b["muted"], 2)
    return img


# ---------------------------------------------------------------- build
def build_reel(post_text: str, topics=None, outlet: str = "", brand: str = "ethan",
               lang: str = "en", llm=None, workdir: Path | None = None) -> bytes:
    """Return mp4 bytes. Empty bytes on failure."""
    if cd is None:
        return b""
    b = cd.BRANDS.get(brand, cd.BRANDS["ethan"])
    work = workdir or Path(tempfile.mkdtemp(prefix="reel_"))
    work.mkdir(parents=True, exist_ok=True)

    hook = cd.clean_hook(post_text)
    num, direction = cd.find_number(hook) or cd.find_number(post_text)
    cats = [str(t).replace("_", " ").replace("+", "").upper()
            for t in (topics or []) if t and not str(t).startswith("+")]
    tag = cats[0] if cats else ("MARKETS" if lang == "en" else "الأسواق")

    script = voiceover_script(post_text, lang, llm)
    audio = speak(script, lang)
    if not audio:
        print("  reel: no voiceover - falling back to a silent reel", file=sys.stderr)

    cta = ("Full breakdown on the page" if lang == "en"
           else "التفاصيل الكاملة في الصفحة")

    scenes = [
        (_scene_brand(brand, tag, tag), 3.0),
        (_scene_number(brand, num, direction, hook, lang), 6.0),
        (_scene_end(brand, cta, "  ·  ".join(b["strip"]), lang), 3.5),
    ]

    paths = []
    for i, (im, dur) in enumerate(scenes):
        p = work / f"scene{i}.png"
        im.save(p, "PNG")
        paths.append((p, dur))

    # subtitles from the voiceover script, split into 2 timed lines
    ass = work / "subs.ass"
    _write_ass(ass, script, lang, total=sum(d for _, d in scenes))

    wav = work / "voice.wav"
    if audio:
        wav.write_bytes(audio)

    out = work / "reel.mp4"
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
    for p, _ in paths:
        cmd += ["-loop", "1", "-t", "20", "-i", str(p)]
    if wav.exists():
        cmd += ["-i", str(wav)]

    # zoompan each scene, concat them, burn the subtitles, then mux the audio
    total = sum(d for _, d in paths)
    zf = []
    for i, (_, dur) in enumerate(paths):
        zf.append(
            f"[{i}:v]scale=1400:2489:force_original_aspect_ratio=increase,"
            f"crop=1400:2489,"
            f"zoompan=z='min(zoom+0.0006,1.10)':d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={VW}x{VH}:fps={FPS},setsar=1[v{i}]")
    zf.append("".join(f"[v{i}]" for i in range(len(paths))) +
              f"concat=n={len(paths)}:v=1:a=0[vc]")
    # the subtitles filter takes ONE input (the video)
    zf.append(f"[vc]subtitles='{str(ass).replace(chr(92), '/')}"
              .replace(":", r"\:").replace("'", r"\'") + "[vsub]")
    if wav.exists():
        zf.append(f"[{len(paths)}:a]atrim=0:{total},asetpts=N/SR/TB[ac]")

    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
    # each scene input is exactly its own duration at 30 fps, and zoompan is
    # told d=1 (one output frame per input frame) - with d=N on a looping
    # image ffmpeg emits N frames for EVERY input frame, which stretches the
    # scene to minutes.
    for p, dur in paths:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.2f}",
                "-i", str(p)]
    if wav.exists():
        cmd += ["-i", str(wav)]
    cmd += ["-filter_complex", ";".join(zf),
            "-map", "[vsub]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-t", f"{total:.2f}"]
    if wav.exists():
        cmd += ["-map", "[ac]", "-c:a", "aac", "-b:a", "128k"]
    cmd += [str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:  # noqa: BLE001
        print(f"  reel: ffmpeg failed: {e}", file=sys.stderr)
        return b""
    if not out.exists() or out.stat().st_size < 5000:
        print(f"  reel: ffmpeg produced nothing: {(r.stderr or '')[:300]}",
              file=sys.stderr)
        return b""
    return out.read_bytes()


def _wrap_sub(s: str, width: int = 40) -> str:
    """Wrap to explicit ASS lines (\\N) so libass never has to guess."""
    words = s.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if len(trial) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return r"\N".join(lines)


def _write_ass(path: Path, script: str, lang: str, total: float) -> None:
    """Timed subtitles, wrapped to explicit lines, split across the audio."""
    text = (script or "").strip()
    if not text:
        text = " "
    # two timed blocks, each wrapped to at most 2 short lines
    words = text.split()
    half = max(1, len(words) // 2)
    block1 = " ".join(words[:half])
    block2 = " ".join(words[half:])
    half_t = total / 2

    def ts(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n"
        "ScaledBorderAndShadow: yes\nWrapStyle: 2\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
        "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Tahoma,44,&H00FFFFFF,&H00FFFFFF,&H00202020,"
        "&HA0000000,1,0,0,0,100,100,0,0,1,3,1,2,40,40,150,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n")
    lines = header
    if block1.strip():
        lines += (f"Dialogue: 0,{ts(0.15)},{ts(half_t)},Default,,0,0,0,,"
                  f"{_wrap_sub(block1)}\n")
    if block2.strip():
        lines += (f"Dialogue: 0,{ts(half_t + 0.05)},{ts(total)},Default,,0,0,0,,"
                  f"{_wrap_sub(block2)}\n")
    path.write_text(lines, encoding="utf-8")
