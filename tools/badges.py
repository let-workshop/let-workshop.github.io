#!/usr/bin/env python3
"""Print a name badge for everyone on the roster.

    python3 tools/badges.py --art art/badge-light.svg
    python3 tools/badges.py --art art/badge-light.svg --sort name --blanks 12

Writes, into --out (default ~/Downloads/let-badges):

    let-2026-badges.pdf     one card per page, 90 x 130mm
    roster.txt              who is on which card, for the desk

The card is the one in poster.py's BADGE layout and nothing else — same formula
drawing, same photograph behind it, same veil, same type at the same sizes, the
name above centre because a lanyard curls forward at the bottom. This script
changes whose names are on it and gets a PDF out. There is no second
description of the card here that could drift from the first, which is the
whole reason it is done this way round rather than redrawn.

Two things have to be handled to get from that page to a printable file.

A hundred and nine cards is 53,000 CSS pixels of document. Chrome's
print-to-pdf runs for two minutes on that and produces nothing at all, so the
roster is cut into chunks, each printed on its own, and the PDFs joined. The
seam is invisible: every card is the same template at the same size and nothing
spans two of them.

And the drawing has to be rasterised first. The badge puts it in a CSS
`background-image`, and Chrome re-embeds a vector background once per page — 20
cards came to 129MB, which is 700MB for the roster, at 35 seconds a chunk. The
same drawing as a PNG at 300 DPI is embedded once and shared: 1.2MB for 20
cards, in 4 seconds. It is a picture held at 34% opacity behind a name, and
nothing about it at that size is vector in any way anyone can see.

The four roles and how someone gets one are in tools/roster.py.
"""

import argparse
import base64
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import roster as roster_mod                                    # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# 90 x 130mm at 300 DPI, which is what the drawing is rasterised at.
CARD_PX = (1063, 1535)
ART_RE = r'\.art \{ background-image:url\("([^"]+)"\)'


def run(*cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        sys.exit(f"{Path(str(cmd[0])).name} failed:\n{(r.stderr or r.stdout)[-2000:]}")
    return r.stdout


def chrome(*args):
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", *[str(a) for a in args]],
                   capture_output=True, text=True)



def background_geometry(png, shift_mm):
    """Where the background sits, and how big, to move it `shift_mm` right.

    `cover` scales the picture until it covers the card, and the sheet is
    426:600 against the card's 90:130 — so it covers by height and hangs over
    the sides by 2.3mm in total, which is all the room there is to move it.
    Asking for more than that with `cover` would drag a corner off the card and
    leave the ground showing.

    So the picture is enlarged by exactly what the shift needs: enough width to
    hold the card plus the shift on both sides, and not a millimetre more. At
    the default 3mm it grows 4%.
    """
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    w, h = Image.open(png).size
    r = w / h
    need_w = 90 + 2 * abs(shift_mm)
    height_mm = max(130.0, need_w / r)
    return f"calc(50% + {shift_mm:.2f}mm) center", f"auto {height_mm:.2f}mm"


def poster_png(work, port, poster_art, ghost, scheme, out_png, dpi=600,
               palette=None, stem="poster"):
    """The poster's background, as a picture, at badge resolution.

    Not a crop of the sheet and not a second solve at badge size — the sheet's
    own background, made smaller. Everything that makes the poster look like
    the poster is already in it and comes along: the formulas at the sheet's
    density, drawn in art_ink rather than the black a CSS background-image
    falls back to; the photograph under them at the sheet's ghost_alpha; and
    the veil over both. The badge draws that one picture and nothing else.

    Rendered at 600 DPI rather than 300. The formulas are the sheet's, which
    means a row of them is 0.38mm tall — 4.5 pixels at 300 DPI, where a stroke
    falls below one pixel and the writing turns to grey. At 600 it is 9, which
    is the difference between a texture of marks and a texture of smudge. The
    vector route would be better still and is not available: the sheet's
    artwork is 190,000 formulas, Chrome re-embeds a vector background once per
    page, and five cards did not finish printing in ten minutes.
    """
    if out_png.exists():
        return out_png
    page = work / f"{stem}.html"
    run(sys.executable, ROOT / "tools/poster.py", "--art", poster_art,
        "--ghost", ghost, "--layout", "festival",
        *(("--scheme", scheme) if scheme else ()),
        *(("--palette", palette) if palette else ()),
        "-o", page, cwd=ROOT)
    bare = work / f"{stem}-bg.html"
    # Only the type goes. The three background layers are the point of this.
    bare.write_text(page.read_text().replace("</style>", ".wrap{visibility:hidden}</style>"),
                    encoding="utf-8")
    px = round(90 / 25.4 * dpi)
    chrome("--hide-scrollbars", f"--force-device-scale-factor={px / 1610:.5f}",
           "--window-size=1610,2268", "--virtual-time-budget=180000",
           f"--screenshot={out_png}", f"http://localhost:{port}/{bare.name}")
    if not out_png.exists():
        sys.exit("  could not render the poster background")
    return out_png


def rasterise_art(work, port, page):
    """The drawing as it is actually drawn, once, as a PNG.

    Taken out of the page rather than off disk. poster.py tints the artwork to
    whichever scheme was asked for before inlining it, so the file in art/ is
    not necessarily what the badge shows; the data URI in the page is.

    It comes out black with the picture in its alpha channel, which is correct
    and not a bug to chase: the SVG fills with `currentColor`, and a background
    image has no colour to inherit, so this is what the badge has always drawn.
    """
    png = work / "art.png"
    if png.exists():
        return png
    url = re.search(ART_RE, page.read_text()).group(1)
    svg = base64.b64decode(url.split(",", 1)[1]).decode("utf-8")
    (work / "art.svg").write_text(svg, encoding="utf-8")
    (work / "art.html").write_text(
        '<!doctype html><meta charset="utf-8">'
        "<style>html,body{margin:0;padding:0}"
        f"img{{display:block;width:{CARD_PX[0]}px;height:{CARD_PX[1]}px}}</style>"
        '<img src="art.svg">', encoding="utf-8")
    chrome("--hide-scrollbars", "--default-background-color=00000000",
           f"--window-size={CARD_PX[0]},{CARD_PX[1]}", "--virtual-time-budget=60000",
           f"--screenshot={png}", f"http://localhost:{port}/art.html")
    if not png.exists():
        sys.exit("  could not rasterise the drawing")
    return png


ROLE_ART_RE = r'\.card\.(\w+) \.art \{ background-image:url\("([^"]+)"\)'


def with_raster_art(page, png, role_pngs=()):
    """The badge's three background layers replaced by the poster's picture.

    `.ghost` and `.veil` go with them: the picture already has the photograph
    and the veil in it, because it is a photograph of the sheet that has them.
    Drawing either again would be the same layer twice.
    """
    as_url = lambda f: ("data:image/png;base64,"
                        + base64.b64encode(f.read_bytes()).decode("ascii"))
    out = page.with_name(page.stem + "-r.html")
    text, n = re.subn(ART_RE, '.art { background-image:url("%s")' % as_url(png),
                      page.read_text(), count=1)
    if not n:
        sys.exit("  the badge page has no .art background to replace")
    # A role whose badge is a dark card has a drawing of its own in the page, as
    # a vector. It cannot stay: one page of it came to a 76MB stream and pypdf
    # would not read the chunk back to join it. So that rule gets its own
    # picture, rendered from the same ground, and the card is rasterised like
    # every other one.
    for role, role_png in role_pngs:
        text, k = re.subn(r'\.card\.%s \.art \{ background-image:url\("[^"]+"\)' % role,
                          '.card.%s .art { background-image:url("%s")' % (role, as_url(role_png)),
                          text, count=1)
        if not k:
            sys.exit(f"  the badge page has no .card.{role} .art background to replace")
    text = text.replace("</style>",
                        ".art{opacity:1}.ghost{display:none}.veil{display:none}</style>")
    out.write_text(text, encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--art", required=True,
                    help="any badge-shaped art; only its slot is used, since the "
                         "background comes from --poster-art")
    ap.add_argument("--poster-art", required=True,
                    help="the A2 art SVG — the badge's background is the sheet's")
    ap.add_argument("--ghost", default=str(ROOT / "art/campus.jpg"))
    ap.add_argument("--scheme", default="light")
    ap.add_argument("--roster", default=str(ROOT / "data/roster.tsv"))
    ap.add_argument("--sort", choices=("role", "name"), default="role")
    ap.add_argument("--blanks", type=int, default=6)
    ap.add_argument("--art-dark",
                    help="the drawing solved for a dark ground. The organisers' "
                         "badge is the poster's dark style, so its drawing is "
                         "its own rather than the light one inverted; that card "
                         "keeps the vector drawing, which is three pages of the "
                         "hundred and nine and not the whole document.")
    ap.add_argument("--style", choices=("plate", "open"), default="plate",
                    help="how the name stays legible over the drawing — see "
                         "BADGE_STYLES in poster.py. The file is named after it.")
    ap.add_argument("--shift", type=float, default=0.0, metavar="MM",
                    help="move the picture right by this many millimetres "
                         "(negative moves it left). `cover` leaves only 2.3mm "
                         "of slack on a 90mm card, so anything more enlarges "
                         "the background by exactly as much as it shifts it "
                         "and no more")
    ap.add_argument("--dpi", type=int, default=600,
                    help="what the background picture is baked at (default 600; "
                         "the formulas are 4.5px a row at 300)")
    ap.add_argument("--chunk", type=int, default=20,
                    help="cards per PDF before they are joined (default 20)")
    ap.add_argument("--out", default=str(Path.home() / "Downloads/let-badges"))
    ap.add_argument("--port", type=int, default=8996)
    args = ap.parse_args()

    from pypdf import PdfWriter

    if not Path(CHROME).exists():
        sys.exit(f"Chrome not at {CHROME}")
    people = roster_mod.ordered(roster_mod.read(args.roster), args.sort)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    work = out / "_work"; work.mkdir(exist_ok=True)
    (work / "fonts").mkdir(exist_ok=True)
    for f in (ROOT / "static/fonts").glob("*.woff2"):
        (work / "fonts" / f.name).write_bytes(f.read_bytes())

    server = subprocess.Popen([sys.executable, "-m", "http.server", str(args.port)],
                              cwd=work, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
    pdfs = []
    try:
        time.sleep(2)
        batches = [people[i:i + args.chunk] for i in range(0, len(people), args.chunk)]
        if args.blanks:
            batches.append([])          # the spares, drawn by the same template
        # The picture first: its shape decides how the page has to place it,
        # and the page is written with those numbers in it.
        png = poster_png(work, args.port, args.poster_art, args.ghost,
                         args.scheme, work / f"poster-bg-{args.dpi}.png", args.dpi)
        bg_pos, bg_size = background_geometry(png, args.shift)
        # And the same background in the dark sheet's style for the roles whose
        # badge is a dark card, from poster.py's own role palette so the printed
        # card is the card the export renders rather than an approximation of it.
        role_pngs = []
        if args.art_dark:
            import json
            sys.path.insert(0, str(ROOT / "tools"))
            import poster as poster_mod
            for role, (_, is_dark) in poster_mod.BADGE_ROLE_GROUNDS.items():
                if not is_dark:
                    continue
                role_pngs.append((role.lower(), poster_png(
                    work, args.port, args.art_dark, args.ghost, "",
                    work / f"poster-bg-{role.lower()}-{args.dpi}.png", args.dpi,
                    palette=json.dumps(poster_mod.badge_role_palette(role)),
                    stem=f"poster-{role.lower()}")))
        for n, batch in enumerate(batches):
            blanks = args.blanks if not batch else 0
            tsv = work / f"chunk-{n}.tsv"
            roster_mod.write(tsv, batch)
            page = work / f"badges-{n}.html"
            run(sys.executable, ROOT / "tools/poster.py", "--art", args.art,
                "--ghost", args.ghost, "--layout", "badge", "--scheme", args.scheme,
                "--roster", tsv, "--roster-sort", "file",   # the order was chosen above
                "--badge-style", args.style,
                *(("--art-dark", args.art_dark) if args.art_dark else ()),
                "--badge-bg-pos", bg_pos, "--badge-bg-size", bg_size,
                "--roster-blanks", str(blanks), "-o", page, cwd=ROOT)
            page = with_raster_art(page, png, role_pngs)
            pdf = work / f"badges-{n}.pdf"
            pdf.unlink(missing_ok=True)
            chrome("--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                   "--virtual-time-budget=120000",
                   f"http://localhost:{args.port}/{page.name}")
            if not pdf.exists():
                sys.exit(f"  Chrome produced no PDF for chunk {n}")
            pdfs.append(pdf)
            print(f"  {len(batch) or blanks:3d} cards  ->  {pdf.name}")
    finally:
        server.terminate()

    merged = out / f"let-2026-badges-{args.style}.pdf"
    writer = PdfWriter()
    for pdf in pdfs:
        writer.append(str(pdf))
    with merged.open("wb") as fh:
        writer.write(fh)

    lines = [f'{i:3d}  {p["role"]:9} {p["name"]}'
             + (f'  ({p["name_sub"]})' if p["name_sub"] else "")
             + (f'  — {p["affil"]}' if p["affil"] else "")
             for i, p in enumerate(people, 1)]
    (out / "roster.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n  {len(writer.pages)} pages -> {merged}"
          f"  ({merged.stat().st_size / 1e6:.1f}MB)")
    for r in roster_mod.ROLES:
        print(f"    {r:9} {sum(1 for p in people if p['role'] == r):3d}")
    print(f"    {'blank':9} {args.blanks:3d}")


if __name__ == "__main__":
    main()
