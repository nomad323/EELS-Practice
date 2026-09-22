#!/usr/bin/env python3
"""Generate documentation strips showing each coefficient's spot evolution."""
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eels_sim import Config, POWERS, TERMS, simulate  # noqa: E402
from eels_sim.presentation import grayscale  # noqa: E402

OUTPUT = ROOT / "docs" / "assets" / "coefficient-trends"
VALUES = (-120, -60, 0, 60, 120)
MONOMIALS = {
    "D10": "u", "D01": "v", "D20": "u²", "D11": "uv", "D02": "v²",
    "D30": "u³", "D21": "u²v", "D12": "uv²", "D03": "v³",
    "D40": "u⁴", "D31": "u³v", "D22": "u²v²", "D13": "uv³", "D04": "v⁴",
    "D50": "u⁵", "D41": "u⁴v", "D32": "u³v²", "D23": "u²v³", "D14": "uv⁴", "D05": "v⁵",
}
DISPLAY_NAMES = {"D10": "FX (D10)", "D01": "FY (D01)", "D02": "C (D02)",
                 "D20": "D (D20)", "D11": "SY (D11)"}
ORDER_NAMES = {1: "一阶", 2: "二阶", 3: "三阶", 4: "四阶", 5: "五阶"}


def font(size, bold=False):
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for candidate in candidates:
        try:
            # Some Unicode fonts have only one face; use size/color rather than
            # a guessed collection index for emphasis so glyph coverage stays intact.
            return ImageFont.truetype(candidate, size=size, index=0)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def dashed(draw, xy, fill, width=1, dash=5):
    x0, y0, x1, y1 = xy
    if x0 == x1:
        for y in range(y0, y1, dash * 2):
            draw.line((x0, y, x1, min(y + dash, y1)), fill=fill, width=width)
    else:
        for x in range(x0, x1, dash * 2):
            draw.line((x, y0, min(x + dash, x1), y1), fill=fill, width=width)


def render_term(term, power, config):
    panel_w, panel_h, gap = 270, 190, 28
    left, top, bottom = 62, 92, 88
    width = left + len(VALUES) * panel_w + (len(VALUES) - 1) * gap + 28
    height = top + panel_h + bottom
    canvas = Image.new("RGB", (width, height), "#101418")
    draw = ImageDraw.Draw(canvas)
    title_font, body_font, small_font = font(28, True), font(19), font(15)
    display = DISPLAY_NAMES.get(term, term)
    order = sum(power)
    draw.text((left, 20), f"{display} · E = {term} × {MONOMIALS[term]} · {ORDER_NAMES[order]}",
              font=title_font, fill="#f4f7f8")

    for index, value in enumerate(VALUES):
        result = simulate({term: value}, config)
        pixels, _ = grayscale(result.counts, gamma=0.5)
        spot = Image.fromarray(np.flipud(pixels), mode="L").resize(
            (panel_w, panel_h), Image.Resampling.BILINEAR).convert("RGB")
        x = left + index * (panel_w + gap)
        canvas.paste(spot, (x, top))
        draw.rectangle((x, top, x + panel_w - 1, top + panel_h - 1), outline="#52616a", width=1)
        dashed(draw, (x + panel_w // 2, top, x + panel_w // 2, top + panel_h), "#28505d")
        dashed(draw, (x, top + panel_h // 2, x + panel_w, top + panel_h // 2), "#28343a")
        label = f"{value:+d} meV" if value else "0 meV（基线）"
        box = draw.textbbox((0, 0), label, font=body_font)
        draw.text((x + (panel_w - (box[2] - box[0])) / 2, top - 30), label,
                  font=body_font, fill="#dce7eb" if value else "#61d3ee")
        for tick, text, align in ((2, "−180", "left"), (panel_w // 2, "0", "center"),
                                  (panel_w - 2, "+180", "right")):
            bbox = draw.textbbox((0, 0), text, font=small_font)
            text_width = bbox[2] - bbox[0]
            tx = x + tick - (text_width / 2 if align == "center" else text_width if align == "right" else 0)
            draw.text((tx, top + panel_h + 7), text, font=small_font, fill="#82939c")

    axis = "能量 E / meV"
    axis_box = draw.textbbox((0, 0), axis, font=small_font)
    draw.text(((width - (axis_box[2] - axis_box[0])) / 2, top + panel_h + 29),
              axis, font=small_font, fill="#82939c")
    draw.text((12, top + panel_h / 2 - 10), "v", font=body_font, fill="#82939c")
    note = "各格独立自动亮度 · γ=0.5 · 固定视野 E ±180 meV、v ±1.6 · 合成教学模型"
    note_box = draw.textbbox((0, 0), note, font=small_font)
    draw.text(((width - (note_box[2] - note_box[0])) / 2, top + panel_h + 53),
              note, font=small_font, fill="#667780")
    return canvas


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config = Config(n_rays=65_536, energy_half_range_mev=180, energy_bins=801, y_bins=181)
    for term, power in zip(TERMS, POWERS):
        target = OUTPUT / f"{term}.png"
        render_term(term, power, config).save(target, optimize=True)
        print(target.relative_to(ROOT))


if __name__ == "__main__":
    main()
