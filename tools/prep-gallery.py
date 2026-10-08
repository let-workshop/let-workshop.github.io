#!/usr/bin/env python3
"""Turn a camera file into the two copies the gallery wants.

    python3 tools/prep-gallery.py ~/Downloads/let1일차/0_all.jpg day1-group
    python3 tools/prep-gallery.py ~/Downloads/let1일차/9_ws1.jpg day1-room --no-full

Writes static/gallery/<slug>.jpg at 1600px wide, and <slug>-full.jpg at the
original size unless --no-full. Prints the block to paste into data/gallery.yml,
dimensions filled in — the page holds the space from them, so a picture added
without them makes the page jump as it loads, and build.py refuses.

Two copies rather than one because they answer different questions. The page
draws the small one: the widest it is ever shown is the 1136px wrap, so 1600
covers that and a retina phone, at a quarter of the bytes. The big one is only
ever fetched by somebody who asked for it by name.

Needs Pillow, which is a local tool dependency — the site build does not touch
images. See prep-photos.py, which does the same job for a headshot.
"""

import argparse
import os
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "gallery"

# What the sheet draws. See the module docstring for why not the original.
WIDE = 1600
# What the grid draws. A thumbnail is shown about 360px wide, so 640 covers it
# on a retina screen — and seventy of them at the sheet's size would be 14MB of
# scrolling to look at a wall of small pictures.
THUMB = 640
# 82 is where this photograph stopped losing anything a reader could see; the
# file is a third of what 95 cost. Progressive, so a slow connection gets a
# whole picture early rather than a band of one.
QUALITY = 82
FULL_QUALITY = 86


def save(im: Image.Image, path: Path, quality: int) -> None:
    im.save(path, quality=quality, optimize=True, progressive=True)
    print(f"  {path.relative_to(ROOT)}  {im.width}×{im.height}  "
          f"{os.path.getsize(path) / 1e6:.2f} MB")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("slug", help="the file name to write, without .jpg")
    ap.add_argument("--no-full", action="store_true",
                    help="skip the full-size copy, for a picture not worth zooming")
    ap.add_argument("--crop-top", type=float, default=0, metavar="FRACTION",
                    help="take this much off the top of the drawn copy, 0.25 for "
                         "a quarter — a room photographed whole is mostly "
                         "ceiling. The full-size copy is never cropped: it is "
                         "the picture as it was taken, which is what somebody "
                         "opening it at full size came for")
    args = ap.parse_args()

    if not args.source.exists():
        raise SystemExit(f"no such file: {args.source}")
    OUT.mkdir(parents=True, exist_ok=True)

    # Phones write the orientation in EXIF rather than in the pixels, and
    # Pillow does not apply it on open — so a portrait arrives on its side.
    im = ImageOps.exif_transpose(Image.open(args.source)).convert("RGB")
    print(f"{args.source.name}  {im.width}×{im.height}")

    # The crop is the page's, not the picture's. What the page draws is a
    # composition — the ceiling is nothing to look at in a strip two hundred
    # pixels tall — and what opens at full size is the photograph, where the
    # room is part of what you are looking at.
    shown = im
    if args.crop_top:
        if not 0 < args.crop_top < 1:
            raise SystemExit("--crop-top is a fraction of the height, 0 to 1")
        cut = round(im.height * args.crop_top)
        shown = im.crop((0, cut, im.width, im.height))
        print(f"  drawn copy: {cut}px off the top  ->  {shown.width}×{shown.height}")

    wide = shown if shown.width <= WIDE else shown.resize(
        (WIDE, round(shown.height * WIDE / shown.width)), Image.LANCZOS)
    save(wide, OUT / f"{args.slug}.jpg", QUALITY)
    thumb = wide if wide.width <= THUMB else wide.resize(
        (THUMB, round(wide.height * THUMB / wide.width)), Image.LANCZOS)
    save(thumb, OUT / f"{args.slug}-thumb.jpg", QUALITY)
    if not args.no_full:
        save(im, OUT / f"{args.slug}-full.jpg", FULL_QUALITY)

    print("\n  - file: gallery/%s.jpg" % args.slug)
    print("    thumb: gallery/%s-thumb.jpg" % args.slug)
    if not args.no_full:
        print("    full: gallery/%s-full.jpg" % args.slug)
    print(f"    width: {wide.width}")
    print(f"    height: {wide.height}")
    print("    title: \n    title_ko: \n    caption: \n    caption_ko: ")


if __name__ == "__main__":
    main()
