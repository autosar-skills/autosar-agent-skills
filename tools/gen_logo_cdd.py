#!/usr/bin/env python3
# tools/gen_logo_cdd.py
"""Generate the Agensi listing logo for cdd-arxml-consistency.

Same visual language as the other two skills' logos so the three read as a set:
dark grid, two rows of rounded squares, the mismatched cell in amber, then the
skill's name. Only the palette and the glyphs change.

Usage: python3 tools/gen_logo_cdd.py [out.png]
"""
from __future__ import annotations

import sys

from PIL import Image, ImageDraw, ImageFont

BG = (15, 17, 22)
GRID = (21, 25, 34)
CYAN = (34, 211, 238)
AMBER = (245, 158, 11)
DIM = (107, 114, 128)

SIZE = 512
CELL = 46
GAP = 12
RADIUS = 8
STROKE = 3

# Font lookup is the fiddly part on a bare VM: try the usual suspects, then
# fall back to the bitmap default so the script never fails just because a
# font is missing.
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]


def font(size: int):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def rounded(draw, box, colour, width=STROKE, radius=RADIUS):
    draw.rounded_rectangle(box, radius=radius, outline=colour, width=width)


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "logo512.png"
    img = Image.new("RGB", (SIZE, SIZE), BG)
    d = ImageDraw.Draw(img)

    # background grid, 32 px pitch, one pixel lines
    for i in range(0, SIZE, 32):
        d.line([(i, 0), (i, SIZE)], fill=GRID, width=1)
        d.line([(0, i), (SIZE, i)], fill=GRID, width=1)

    # two rows of cells. The top row is the spec (CDD), the bottom row is the
    # ECU (ARXML). One column differs — that is the whole point of the tool,
    # so it is the only amber element in the image.
    cols = 8
    total = cols * CELL + (cols - 1) * GAP
    x0 = (SIZE - total) // 2
    y_top = 165
    y_bot = y_top + CELL + 34
    mismatch = 4

    for c in range(cols):
        x = x0 + c * (CELL + GAP)
        rounded(d, [x, y_top, x + CELL, y_top + CELL], CYAN)
        if c == mismatch:
            rounded(d, [x, y_bot, x + CELL, y_bot + CELL], AMBER)
        else:
            rounded(d, [x, y_bot, x + CELL, y_bot + CELL], DIM)

    # the connector: a short stem from the mismatched cell down to the one
    # below it, so the disagreement reads as a link, not two stray boxes
    cx = x0 + mismatch * (CELL + GAP) + CELL // 2
    d.line([(cx, y_top + CELL), (cx, y_bot)], fill=AMBER, width=2)
    d.ellipse([cx - 3, y_top + CELL - 3, cx + 3, y_top + CELL + 3], fill=BG)

    # headline
    f_big = font(74)
    f_small = font(38)

    t = "CDD"
    bb = d.textbbox((0, 0), t, font=f_big)
    d.text(((SIZE - (bb[2] - bb[0])) // 2 - 6, 355), t, fill=CYAN, font=f_big)

    t2 = "×  ARXML"
    bb2 = d.textbbox((0, 0), t2, font=f_small)
    d.text(((SIZE - (bb2[2] - bb2[0])) // 2, 445), t2, fill=DIM, font=f_small)

    img.save(out)
    print(f"wrote {out} {img.size[0]}x{img.size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
