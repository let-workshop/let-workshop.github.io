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

# What the page draws. See the module docstring for why not the original.
WIDE = 1600
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
                    help="take this much off the top first, 0.33 for a third — "
                         "a room photographed whole is mostly ceiling")
    args = ap.parse_args()

    if not args.source.exists():
        raise SystemExit(f"no such file: {args.source}")
    OUT.mkdir(parents=True, exist_ok=True)

    # Phones write the orientation in EXIF rather than in the pixels, and
    # Pillow does not apply it on open — so a portrait arrives on its side.
    im = ImageOps.exif_transpose(Image.open(args.source)).convert("RGB")
    print(f"{args.source.name}  {im.width}×{im.height}")
    if args.crop_top:
        if not 0 < args.crop_top < 1:
            raise SystemExit("--crop-top is a fraction of the height, 0 to 1")
        cut = round(im.height * args.crop_top)
        im = im.crop((0, cut, im.width, im.height))
        print(f"  cut {cut}px off the top  ->  {im.width}×{im.height}")

    wide = im if im.width <= WIDE else im.resize(
        (WIDE, round(im.height * WIDE / im.width)), Image.LANCZOS)
    save(wide, OUT / f"{args.slug}.jpg", QUALITY)
    if not args.no_full:
        save(im, OUT / f"{args.slug}-full.jpg", FULL_QUALITY)

    print("\n  - file: gallery/%s.jpg" % args.slug)
    if not args.no_full:
        print("    full: gallery/%s-full.jpg" % args.slug)
    print(f"    width: {wide.width}")
    print(f"    height: {wide.height}")
    print("    title: \n    title_ko: \n    caption: \n    caption_ko: ")


if __name__ == "__main__":
    main()
