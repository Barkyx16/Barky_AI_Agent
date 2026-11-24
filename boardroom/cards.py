"""Share-card images for verdicts (1200x630 PNG), drawn with the app's own fonts.

Used as the link-preview image for shared verdicts and as a downloadable image
people can post anywhere.
"""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).parent / "static" / "fonts"
W, H = 1200, 630
BG = (13, 17, 23)
TEXT = (236, 235, 230)
MUTED = (169, 173, 181)
FAINT = (111, 118, 130)
GOLD = (201, 169, 110)
ADVISOR_COLORS = {
    "analyst": (59, 130, 246), "skeptic": (239, 68, 68), "strategist": (245, 158, 11),
    "operator": (16, 185, 129), "guest": (236, 72, 153),
}
POSITION_COLORS = {"for": (47, 191, 138), "mixed": (224, 163, 58), "against": (236, 106, 106)}


def _font(name: str, size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONTS / name), size)
    try:
        font.set_variation_by_axes([weight])
    except OSError:
        pass
    return font


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int) -> list[str]:
    words, lines, line = " ".join(text.split()).split(" "), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        line = word
        if len(lines) == max_lines:
            break
    if line and len(lines) < max_lines:
        lines.append(line)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        lines[-1] = last.rstrip(" ,.;:") + "…"
    return lines


def _glow(img: Image.Image) -> None:
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((-250, -330, 650, 260), fill=(*GOLD, 46))
    d.ellipse((820, 380, 1460, 900), fill=(59, 130, 246, 26))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(110)))


def _logo(d: ImageDraw.ImageDraw, x: int, y: int) -> None:
    d.rounded_rectangle((x, y, x + 46, y + 46), radius=11, fill=(21, 26, 34))
    d.ellipse((x + 11, y + 18, x + 35, y + 32), outline=GOLD, width=3)
    for (cx, cy), col in zip(((23, 10), (6, 25), (40, 25), (14, 38), (32, 38)),
                             ((139, 92, 246), (59, 130, 246), (239, 68, 68), (245, 158, 11), (16, 185, 129))):
        d.ellipse((x + cx - 4, y + cy - 4, x + cx + 4, y + cy + 4), fill=col)


def _ring(img: Image.Image, cx: int, cy: int, r: int, pct: int) -> None:
    scale = 3  # draw large and shrink, for smooth arcs
    size = (r * 2 + 20) * scale
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    box = (10 * scale, 10 * scale, size - 10 * scale, size - 10 * scale)
    d.ellipse(box, outline=(45, 52, 64), width=16 * scale)
    if pct > 0:
        d.arc(box, start=-90, end=-90 + 360 * pct / 100, fill=GOLD, width=16 * scale)
    layer = layer.resize((r * 2 + 20, r * 2 + 20), Image.LANCZOS)
    img.alpha_composite(layer, (cx - r - 10, cy - r - 10))
    d = ImageDraw.Draw(img)
    big = _font("newsreader-latin-wght-normal.woff2", 52, 600)
    small = _font("inter-latin-wght-normal.woff2", 15, 650)
    d.text((cx, cy - 6), f"{pct}%", font=big, fill=TEXT, anchor="mm")
    d.text((cx, cy + 34), "CONFIDENCE", font=small, fill=FAINT, anchor="mm")


@lru_cache(maxsize=256)
def _render(question: str, headline: str, confidence: int, votes: tuple[tuple[str, str, str], ...]) -> bytes:
    img = Image.new("RGBA", (W, H), (*BG, 255))
    _glow(img)
    d = ImageDraw.Draw(img)

    _logo(d, 64, 56)
    d.text((124, 79), "Boardroom", font=_font("newsreader-latin-wght-normal.woff2", 32, 600), fill=TEXT, anchor="lm")

    kicker = _font("inter-latin-wght-normal.woff2", 17, 650)
    d.text((64, 158), "THE BOARD'S VERDICT", font=kicker, fill=GOLD)

    text_w = 760
    q_font = _font("inter-latin-wght-normal.woff2", 25, 450)
    y = 196
    for line in _wrap(d, f"“{question}”", q_font, text_w, 2):
        d.text((64, y), line, font=q_font, fill=MUTED)
        y += 36

    h_size = 58 if len(headline) < 60 else 50
    h_font = _font("newsreader-latin-wght-normal.woff2", h_size, 600)
    y += 22
    for line in _wrap(d, headline, h_font, text_w, 3):
        d.text((64, y), line, font=h_font, fill=TEXT)
        y += int(h_size * 1.12)

    _ring(img, 1010, 250, 118, max(0, min(100, confidence)))

    # The board's votes, as coloured seats along the bottom.
    d = ImageDraw.Draw(img)
    name_font = _font("inter-latin-wght-normal.woff2", 16, 500)
    label = _font("inter-latin-wght-normal.woff2", 15, 700)
    x, base = 64, 548
    for advisor, name, position in votes[:5]:
        col = ADVISOR_COLORS.get(advisor, (139, 92, 246))
        d.ellipse((x, base - 8, x + 16, base + 8), fill=(*col, 255))
        d.text((x + 24, base), name, font=name_font, fill=MUTED, anchor="lm")
        x += 24 + int(d.textlength(name, font=name_font)) + 8
        word = position.upper()
        d.text((x, base), word, font=label, fill=POSITION_COLORS.get(position, MUTED), anchor="lm")
        x += int(d.textlength(word, font=label)) + 28
    cta = _font("inter-latin-wght-normal.woff2", 18, 550)
    if x < W - 64 - d.textlength("Convene your own board", font=cta) - 20:
        d.text((W - 64, base), "Convene your own board", font=cta, fill=MUTED, anchor="rm")

    out = io.BytesIO()
    img.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


NAMES = {"analyst": "Analyst", "skeptic": "Skeptic", "strategist": "Strategist", "operator": "Operator"}


def verdict_card(question: str, verdict: dict, guest_name: str = "") -> bytes:
    names = {**NAMES, "guest": (guest_name or "Guest")[:18]}
    votes = tuple(
        (v.get("advisor", ""), names.get(v.get("advisor", ""), "Advisor"), v.get("position", ""))
        for v in verdict.get("votes", [])
    )
    return _render(question.strip(), verdict.get("headline", "").strip(), int(verdict.get("confidence", 0)), votes)
