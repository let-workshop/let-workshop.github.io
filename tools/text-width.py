#!/usr/bin/env python3
"""How wide a line of text comes out, measured from the fonts the site ships.

    python3 tools/text-width.py "← Previous" --font inter --size 13.6 --weight 600
    python3 tools/text-width.py "15–20 min by car" --font mono --size 11.52

Written the week Chrome went missing from this machine, which took the
screenshots, tools/check-layout.py and the poster export with it. A layout
question is usually "does this fit", and that can be answered from the glyph
advances without rendering anything: the answer here is within a pixel of what
the browser produced on the cases both could still be run on.

It found the fault it was written for. On a 390px phone the speaker sheet's
footer wanted 394px in English — "← Previous" is a 94px pill where 이전 is 55 —
so the rail now takes a line of its own below 440px.

The faces are the real ones from static/fonts, instanced to the weight asked
for, so semibold is measured as semibold rather than guessed at.
"""
import argparse
import sys
from pathlib import Path

try:
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
except ModuleNotFoundError:
    sys.exit("needs fontTools\n  pip install -r requirements.txt")

ROOT = Path(__file__).resolve().parent.parent
FONTS = {
    "inter": "inter-latin.woff2",
    "tight": "inter-tight-latin.woff2",
    "mono": "jetbrains-mono-latin.woff2",
    "jost": "jost-latin.woff2",
    "satoshi": "satoshi-500.woff2",
}
_cache: dict = {}


def face(name: str, weight: int | None):
    key = (name, weight)
    if key not in _cache:
        f = TTFont(ROOT / "static/fonts" / FONTS[name], lazy=False)
        if weight is not None and "fvar" in f:
            f = instantiateVariableFont(f, {"wght": weight}, inplace=False,
                                        updateFontNames=False)
        _cache[key] = (f["hmtx"], f.getBestCmap(), f["head"].unitsPerEm)
    return _cache[key]


def width(text: str, font: str = "inter", size: float = 16.0,
          weight: int | None = None, tracking: float = 0.0) -> float:
    """Advance width in CSS pixels. `tracking` is letter-spacing in em."""
    hmtx, cmap, upm = face(font, weight)
    total = 0.0
    missing = []
    for ch in text:
        glyph = cmap.get(ord(ch))
        if glyph is None:
            # Half an em is roughly what a fallback face will spend on it, and
            # saying so is better than pretending the character is free.
            missing.append(ch)
            total += upm * 0.5
            continue
        total += hmtx[glyph][0]
    if missing:
        print(f"  note: not in {font} — {''.join(sorted(set(missing)))}"
              " (counted at half an em each)", file=sys.stderr)
    return total / upm * size + tracking * size * len(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", nargs="+")
    ap.add_argument("--font", default="inter", choices=sorted(FONTS))
    ap.add_argument("--size", type=float, default=16.0, help="in CSS pixels")
    ap.add_argument("--weight", type=int, help="100–900, for a variable face")
    ap.add_argument("--tracking", type=float, default=0.0, help="letter-spacing, in em")
    ap.add_argument("--fits", type=float, help="a width to compare against")
    args = ap.parse_args()

    over = 0
    for text in args.text:
        px = width(text, args.font, args.size, args.weight, args.tracking)
        verdict = ""
        if args.fits is not None:
            room = args.fits - px
            verdict = f"   fits, {room:.0f}px spare" if room >= 0 else f"   OVER by {-room:.0f}px"
            over += room < 0
        print(f"  {px:7.1f}px  {text}{verdict}")
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
