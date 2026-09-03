#!/usr/bin/env python3
"""Lay out the A2 poster from the same data the site is built from.

    python3 tools/poster.py --art static/hero-art.svg -o /tmp/poster/poster.html

Writes one HTML file with the formula art inlined, ready for Chrome to print to
a vector PDF at 426 x 600 mm — A2 with 3 mm of bleed on every side.

Why generate it rather than draw it. The programme is the part of a poster that
changes: a speaker withdraws, a session moves, an affiliation is wrong. Reading
data/program.yml means the sheet cannot disagree with the website, and a new
version is one command rather than an afternoon of retyping into a layout.

The art is inlined rather than referenced. A CSS mask or a linked image is
rasterised on the way to PDF — measured, Chrome baked it at 863 px across a
426 mm sheet, about 51 dpi — while paths in the page stay paths.
"""

import argparse
import base64
import html
import io
import re
import sys
from pathlib import Path

try:
    import segno
    import yaml
    from PIL import Image, ImageEnhance, ImageOps
except ModuleNotFoundError as exc:  # pragma: no cover
    sys.exit(f"missing dependency '{exc.name}'\n  pip install pyyaml segno")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# The site's own palette: one cool family, near-white for the headline, the
# coral accent kept for labels. `art` is the colour baked into the formula SVG,
# and is deliberately a step below the headline — the field is enormous and at
# the headline's brightness it competes with the name.
PALETTE = {
    "ground": "#0f1826",
    "ground2": "#0b111c",
    # Near white. Across a room the sheet read as dark before it read as
    # anything else — the drawing is light marks on a dark field, and what
    # carries at that distance is how much light the marks put back.
    "art_ink": "#ffffff",
    "ink": "#f5f5f7",
    "ink_dim": "#a8b8cd",
    "cool": "#93a2b8",
    "cool_dim": "#6d7f96",
    "hot": "#ff8a75",
    "gold": "#f2cda0",  # the warm line an academic sheet puts its dates in
    "band": "#0b1523",
    # The light-ground layouts. Ink on paper rather than light on a dark field,
    # which reverses what the artwork has to do — see formula-art.py --invert.
    "paper": "#f4f1ea",
    "paper2": "#ffffff",
    "carbon": "#1b1b1b",
    "carbon2": "#5a5a5a",
    "accent": "#e8503a",
    "sky": "#4ec3e0",
    "rule": "rgba(255,255,255,.18)",
    # The veil, as five stops down the sheet. It exists to hold a photograph
    # back from the type on a dark ground; a scheme that puts a flat field in
    # the sky and a plate under the campus wants far less of it, or the veil
    # simply repaints the whole sheet in the ground colour. Palette values, so
    # a scheme can set them without a second template.
    # Thinner across the sky, and untouched at the two ends. The veil was taking
    # a third of the drawing's light with it, but it cannot simply be lifted:
    # the accent is a mid-light colour and so is a bright drawing, so past a
    # point the two meet. Lifting the top took the mark from 3.3:1 against its
    # own ground to 2.2:1, under the 3:1 a 32mm word needs, and lifting the
    # bottom took the programme with it. So the first stop goes up to cover the
    # strip the mark sits in, the last two stay where they always were behind
    # the programme, and the two in the middle — the sky — come down hard.
    #
    # That is as far as it goes without a halo behind the coral, and a halo is
    # furniture this sheet does not otherwise have. Measured: mean luminance 52
    # before, 74.5 now; mark 3.6:1, rails 3.1:1, programme 15.2:1, every one of
    # them at or above where it started.
    # And one across, not down. The rails are coral over the drawing at the left
    # edge, and the sky above them is now bright enough that the two meet at
    # 3.1:1 — a hair over what a 9mm word needs and no more. A halo under the
    # letters would fix it and is furniture; darkening the strip they stand on
    # is the same veil doing the same job on the other axis, and across a fifth
    # of the sheet it reads as the corner falling away rather than as a panel.
    "veilx": ".26",
    "veil1": ".66", "veil2": ".04", "veil3": ".14", "veil4": ".80", "veil5": ".96",
    # How strongly the formulas themselves are drawn. On the dark sheet they
    # are the picture and run at full strength; a scheme that also lays a solid
    # plate under the campus wants them quieter, or the two together bury the
    # title.
    "art_alpha": "1",
    # The photograph behind the formulas, as two tones and a drive.
    "ghost_shadow": "#0a111d",
    "ghost_light": "#b9cbe4",
    "ghost_contrast": "0.92",
    # And how strongly the photograph behind the formulas is felt. On the dark
    # sheet it is there to hold the shape together between the marks and is
    # meant to be felt rather than seen. On paper it has more to do: the ground
    # is pale, the drawing's darkest mark is only so dark, and without the
    # photograph carrying some of it the building and the sky arrive at almost
    # the same tone.
    "ghost_alpha": ".3",
    # The veils and rules of the other four pieces, so a scheme can turn them
    # over too. Each piece veils a different shape at a different reading
    # distance, so they are separate values rather than one shared set.
    "veil_b_mid1": ".74", "veil_b_mid2": ".46", "veil_b_end": ".93",
    "veil_x1": ".52", "veil_x2": ".66", "veil_x3": ".80", "veil_x4": ".97",
    "scrim1": "rgba(15,24,38,.62)", "scrim2": "rgba(15,24,38,.42)",
    "scrim3": "rgba(15,24,38,.70)", "scrim4": "rgba(15,24,38,.96)",
    "scrim5": "rgba(15,24,38,.90)", "scrim6": "rgba(15,24,38,.86)",
    "keyline": "rgba(245,245,247,.34)", "rule_soft": "rgba(245,245,247,.20)",
    "rule_mid": "rgba(245,245,247,.30)", "rule_strong": "rgba(245,245,247,.42)",
    "chip": "rgba(255,255,255,.34)",
}


def esc(s):
    return html.escape(str(s), quote=False)


def photo_svg(source, shadow, highlight, width, height, contrast=0.92):
    """The photograph itself, in two tones, wrapped so a layout can drop it in
    wherever it would have put the formulas.

    Same reduction the website's backdrop uses: luminance, stretched to its own
    range, then mapped onto a ramp between two colours of the sheet. A poster
    that is one ink wants its picture in that ink.

    It is wrapped in an SVG because every layout here places its artwork by
    inlining one — this way the plain-photograph variants need no separate code
    path, only a different file.

    One thing to know before printing it. The source is 1280px across; an A2
    sheet at 300 dpi wants about 5000. Enlarged that far the photograph is
    noticeably soft, which is the objection that made a vector picture worth
    building in the first place. At normal viewing distance for a poster it is
    acceptable; held at arm's length it is not.
    """
    im = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    im = ImageOps.fit(im, (width, height), Image.LANCZOS, centering=(0.5, 0.45))
    grey = ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=(1, 2))
    grey = ImageEnhance.Contrast(grey).enhance(contrast)
    a = tuple(int(shadow.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(highlight.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    ramp = []
    for ch in range(3):
        ramp += [round(a[ch] + (b[ch] - a[ch]) * (v / 255)) for v in range(256)]
    toned = grey.convert("RGB").point(ramp)
    buf = io.BytesIO()
    toned.save(buf, "JPEG", quality=88, optimize=True, progressive=True)
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'preserveAspectRatio="xMidYMid slice">'
        f'<image x="0" y="0" width="{width}" height="{height}" '
        f'preserveAspectRatio="xMidYMid slice" href="data:image/jpeg;base64,{data}"/></svg>'
    )


def logo_row(logos, colour, cap=3.4, flat=True):
    """The host marks, embedded — flattened to one tone, or as their owners drew them.

    Logos arrive in their own brand colours, which on a sheet built from one
    ink is three palettes fighting. With `flat`, the alpha channel carries the
    shape, the art is discarded and the silhouette refilled — that also
    sidesteps the reproduction rules both universities publish, which govern
    the mark in its own colours, not a monotone courtesy credit.

    The banner asks for `flat=False`. A credit line at the foot of a six-metre
    cloth is not a sheet's monotone courtesy credit — it is the row that says
    who is running this, read from a few metres by people who know these marks
    by their colour before they can read the letters. Greyed out at that size
    a crest reads as a placeholder for a logo rather than as one. Rendering
    them as published means the published rules apply: clear space, minimum
    size, no recolouring — which is what this branch does.
    """
    out = []
    for logo in logos:
        name = logo["name"]
        # Whichever extension the mark is shipped in. It was written as .png,
        # and when the site moved its logos to WebP the sheet stopped finding
        # them and printed a foot with no institutions on it — silently, since
        # a missing file was something to skip past. Now it is something to
        # say out loud.
        for f in (ROOT / "static" / "logos" / f"{name.lower()}{ext}"
                  for ext in (".webp", ".png", ".jpg")):
            if f.exists():
                break
        else:
            raise SystemExit(f"  no logo for {name} in static/logos/")
        im = ImageOps.exif_transpose(Image.open(f)).convert("RGBA")
        if flat:
            rgb = tuple(int(colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            mark = Image.new("RGBA", im.size, rgb + (0,))
            mark.putalpha(im.getchannel("A"))
        else:
            mark = im
        buf = io.BytesIO()
        mark.save(buf, "PNG", optimize=True)
        data = base64.b64encode(buf.getvalue()).decode("ascii")
        # Sized by its letters and dropped onto one line with the others, from
        # the two numbers in data/site.yml — the same pair the page uses, so
        # the sheet and the site draw the marks in the same proportions. The
        # row is aligned on its bottom edge, so a mark whose letters sit high
        # above its own bottom is pushed down by exactly that difference.
        ratio = float(logo.get("ratio") or 1)
        baseline = float(logo.get("baseline") or 1)
        # The optical correction the page applies, applied here too, or the
        # sheet and the site would set the same three marks differently.
        box = cap * ratio * float(logo.get("nudge") or 1)
        out.append(
            f'<img alt="{esc(name)}" style="height:{box:.2f}mm;'
            f'margin-bottom:{cap * 0.9 - (1 - baseline) * box:.2f}mm"'
            f' src="data:image/png;base64,{data}">')
    return "".join(out)


def cutout_svg(source, shadow, highlight, width, height, contrast=0.95):
    """The buildings with the sky already gone, toned to the sheet's ink.

    Two differences from the plain photograph, and both matter. It keeps its
    alpha, so it is saved as a PNG rather than a JPEG — a JPEG would fill the
    sky back in with black. And it is fitted rather than cropped, aligned to
    the foot of its box: a cut-out has a silhouette, and cropping one throws
    away the part that makes it read as a building rather than as a texture.
    """
    im = ImageOps.exif_transpose(Image.open(source)).convert("RGBA")
    im.thumbnail((width * 2, width * 2), Image.LANCZOS)
    rgb, alpha = im.convert("RGB"), im.getchannel("A")
    grey = ImageOps.autocontrast(ImageOps.grayscale(rgb), cutoff=(1, 2))
    grey = ImageEnhance.Contrast(grey).enhance(contrast)
    a = tuple(int(shadow.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    b = tuple(int(highlight.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    ramp = []
    for ch in range(3):
        ramp += [round(a[ch] + (b[ch] - a[ch]) * (v / 255)) for v in range(256)]
    toned = grey.convert("RGB").point(ramp)
    toned.putalpha(alpha)
    buf = io.BytesIO()
    toned.save(buf, "PNG", optimize=True)
    data = base64.b64encode(buf.getvalue()).decode("ascii")
    # The box keeps the container's proportion and the building is laid into it
    # at full width, standing on the bottom edge. Fitting it instead would put
    # it in the middle of a tall box with air above and below; slicing it would
    # crop the silhouette, which is the whole of what a cut-out has. Whatever
    # overflows the top is sky, and sky is transparent now.
    img_h = round(width * toned.height / toned.width)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" preserveAspectRatio="xMidYMax slice">'
        f'<image x="0" y="{height - img_h}" width="{width}" height="{img_h}" '
        f'href="data:image/png;base64,{data}"/></svg>'
    )


def acronym_html(full_name, mark):
    """The full name with the letters that make the acronym picked out.

    The mark is LeT and the name is Learning Theory Workshop; the letters that
    make the one out of the other are picked out in the accent. Setting the
    name in capitals, which is what the sheets were doing, throws that away —
    it becomes three words in caps and the acronym is a coincidence again. In
    mixed case with those letters coloured, the name shows its own working.
    """
    want = list(mark.upper())
    out = []
    for word in full_name.split():
        if want and word[:1].upper() == want[0]:
            out.append(f'<b>{esc(word[0])}</b>{esc(word[1:])}')
            want.pop(0)
        else:
            out.append(esc(word))
    return " ".join(out)


def qr_svg(url, dark, light=None):
    """The site address as an SVG QR, sized by CSS rather than by pixels.

    Error correction at H, the highest of the four levels: a poster gets rained
    on, taped over a corner and photographed at an angle, and H can lose almost
    a third of the symbol and still decode. It costs a denser grid, which at
    30 mm square is still far above what a phone camera needs.

    Drawn as vector so it prints at the press's own resolution — a QR is the one
    element on the sheet where a soft edge actually costs something, since the
    decoder is looking for hard transitions.
    """
    qr = segno.make(url, error="h")
    buf = io.BytesIO()  # segno writes bytes even for SVG
    qr.save(buf, kind="svg", xmldecl=False, svgns=True, dark=dark, light=light,
            border=2, unit="", svgclass=None, lineclass=None)
    svg = buf.getvalue().decode("utf-8")
    # segno writes fixed width/height and no viewBox, and an SVG without a
    # viewBox does not scale — asked to fill a 30 mm plate it drew itself at its
    # natural size in one corner instead. Trade them for a viewBox so the plate
    # decides how big the code is.
    m = re.search(r'<svg[^>]*?width="([\d.]+)"[^>]*?height="([\d.]+)"', svg)
    if m:
        w, h = m.group(1), m.group(2)
        head = svg[: svg.index(">") + 1]
        fixed = re.sub(r'\s(width|height)="[\d.]+"', "", head)
        fixed = fixed[:-1] + f' viewBox="0 0 {w} {h}">'
        svg = fixed + svg[svg.index(">") + 1 :]
    return svg


def sessions(program):
    """Talk sessions with their speakers, day by day."""
    out = []
    for day in program["days"]:
        blocks = []
        for e in day["events"]:
            if e.get("type") not in ("block", "tutorial", "keynote"):
                continue
            # Every slot the session has, named or not. A session with nobody
            # named yet is still a session, and leaving it off makes the day
            # look shorter than it is; a session with one name and one slot
            # still open is the same argument for the slot. Reading only the
            # named ones dropped the second half of Bandits II the moment the
            # first half was filled — the sheet quietly lost a talk.
            people = [
                s if s.get("name") and s["name"] != "TBD" else {"name": "TBD", "affil": ""}
                for s in e.get("speakers", []) or []
            ]
            if not people:
                continue
            blocks.append(
                {
                    "title": e["title"],
                    "start": e.get("start", ""),
                    "end": e.get("end", ""),
                    "people": people,
                }
            )
        out.append({"label": day.get("label", ""), "theme": day.get("theme"), "blocks": blocks})
    return out


def programme_html(program, affils):
    cols = []
    for day in sessions(program):
        rows = []
        for b in day["blocks"]:
            people = "".join(
                f'<li><b>{esc(p["name"])}</b> <span class="aff">{esc(p.get("affil", ""))}</span>'
                + (f'<i>{esc(p["topic"])}</i>' if p.get("topic") else "")
                + "</li>"
                for p in b["people"]
            )
            rows.append(
                f'<div class="sess"><h4>{esc(b["title"])}'
                f'<span class="clock">{esc(b["start"])}–{esc(b["end"])}</span></h4>'
                f"<ul>{people}</ul></div>"
            )
        head = esc(day["label"])
        sub = f'<p class="daysub">{esc(day["theme"])}</p>' if day.get("theme") else ""
        cols.append(f'<div class="day"><h3>{head}</h3>{sub}{"".join(rows)}</div>')
    return "".join(cols)


TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster</title>
<style>
  /* A2 plus 3 mm of bleed all round. No trim marks: the printer sets those. */
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  /* Fontshare's CDN serves these with the name table blanked to the string
     "false". A browser never looks — @font-face supplies the name — but a
     printed PDF embeds whatever the file calls itself, and one export went out
     carrying a font called "false". The copies in static/fonts have their
     names written back, one file per weight.

     Satoshi is cut at 300, 400, 500, 700 and 900 — there is no 600. A missing
     weight is not an error a browser reports: it takes the nearest face and,
     in some engines, smears it. The sheet asks only for weights that exist. */
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:900; src:url("fonts/satoshi-900.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{ground}; color:{ink};
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  /* The art is given the top of the sheet and nothing else. Type over a field
     this busy has to be either very large or somewhere else; the programme is
     small, so it goes somewhere else. */
  .art {{ position:absolute; inset:0; overflow:hidden; }}
  .art svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* Only where the type actually is. */
  .fade {{ position:absolute; left:0; right:0; top:150mm; bottom:0; }}
  .fade svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .wrap {{ position:absolute; inset:0; padding:20mm 20mm 15mm; display:flex; flex-direction:column; }}
  .eyebrow {{
    font-family:"JetBrains Mono",monospace; font-size:3.9mm; font-weight:500;
    letter-spacing:.2em; text-transform:uppercase; color:{hot};
    border:.3mm solid rgba(255,138,117,.42); border-radius:99mm; padding:1.9mm 4.4mm;
    align-self:flex-start; background:rgba(11,17,28,.62);
  }}
  .mid {{ margin-top:auto; }}
  h1 {{
    font-family:"Jost",sans-serif; font-weight:500; font-size:58mm; line-height:.88;
    letter-spacing:-.022em; margin:0 0 3.5mm; color:{ink};
  }}
  h1 b {{ font-weight:700; color:{hot}; }}
  h1 .year {{ font-weight:300; color:{ink}; opacity:.86; }}
  .acronym {{
    font-family:"JetBrains Mono",monospace; font-size:5.1mm; font-weight:500;
    letter-spacing:.16em; text-transform:uppercase; color:{cool}; margin:0 0 3.5mm;
  }}
  .theme {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:6.6mm; font-weight:500;
    color:{ink}; margin:0 0 3.5mm; opacity:.9;
  }}
  .theme b {{ font-weight:700; }}
  .facts {{
    display:flex; gap:12mm; font-family:"JetBrains Mono",monospace;
    font-size:4.6mm; font-weight:500; color:{ink}; margin:0 0 4.5mm;
  }}
  .facts span {{ color:{cool}; }}
  .rule {{ height:.3mm; background:{rule}; margin:0 0 3.5mm; }}
  /* The programme. Four columns of small type at the foot, the way a season
     card does it — the poster has to survive being read from a metre away for
     the name and from arm's length for the schedule. */
  .prog {{ display:grid; grid-template-columns:1fr 1fr; gap:10mm; align-items:start; }}
  .day h3 {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:9.4mm; font-weight:700;
    color:{ink}; margin:0 0 1mm;
  }}
  .daysub {{
    font-family:"JetBrains Mono",monospace; font-size:4.6mm; letter-spacing:.12em;
    text-transform:uppercase; color:{hot}; margin:0 0 6.5mm;
  }}
  .sess {{ margin:0 0 4.4mm; break-inside:avoid; }}
  .sess h4 {{
    font-family:"JetBrains Mono",monospace; font-size:4mm; font-weight:500;
    letter-spacing:.14em; text-transform:uppercase; color:{hot};
    margin:0 0 1.8mm; display:flex; justify-content:space-between; gap:4mm;
  }}
  .clock {{ color:{cool}; letter-spacing:.06em; opacity:.8; }}
  .sess ul {{ margin:0; padding:0; list-style:none; }}
  .sess li {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:9.4mm; color:{ink};
    line-height:1.1; margin:0 0 2.1mm;
  }}
  .sess li b {{ font-weight:700; }}
  .aff {{ color:{cool}; font-weight:500; font-size:6.4mm; }}
  /* The topic lines are gone. Eight of them under the names is a third column
     of grey the sheet did not need, and taking them out is most of what moves
     the title down the page. */
  .sess li i {{ display:none; }}
  .tail {{
    display:flex; justify-content:space-between; align-items:baseline; margin-top:6mm;
    font-family:"JetBrains Mono",monospace; font-size:3.9mm; letter-spacing:.1em;
    text-transform:uppercase; color:{cool}; gap:10mm;
  }}
  .tail b {{ color:{ink}; font-weight:500; }}
  /* The QR sits on its own light patch. A code drawn light-on-dark decodes on
     most phones but not all — the quiet zone and the polarity are the two
     things cheap decoders are strict about, so both are given properly. */
  .qr-card {{ grid-column:2; display:flex; align-items:center; gap:5mm; margin-top:0; }}
  .qr {{ display:flex; align-items:flex-end; gap:5mm; }}
  .qr-plate {{ width:34mm; height:34mm; flex:none; background:{art_ink}; padding:1.6mm; border-radius:1mm; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
  .qr-say {{ text-align:left; }}
  .qr-say b {{ display:block; font-size:5.2mm; color:{ink}; letter-spacing:.06em; }}
  .qr-say span {{ display:block; font-size:4mm; color:{cool}; margin-top:1.2mm; text-transform:none; letter-spacing:.02em; }}
</style>
<div class="sheet">
  <div class="art">{art}</div>
  <div class="fade"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 100" preserveAspectRatio="none">
    <defs><linearGradient id="f" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{ground}" stop-opacity="0"/>
      <stop offset=".28" stop-color="{ground}" stop-opacity=".72"/>
      <stop offset=".46" stop-color="{ground}" stop-opacity=".94"/>
      <stop offset="1" stop-color="{ground}" stop-opacity="1"/>
    </linearGradient></defs>
    <rect width="10" height="100" fill="url(#f)"/>
  </svg></div>
  <div class="wrap">
    <p class="eyebrow">{eyebrow}</p>
    <div class="mid">
      <h1><b>{mark}</b> <span class="year">{year}</span></h1>
      <p class="acronym">{full_name}</p>
      <p class="theme">{theme_label} · <b>{theme}</b></p>
      <div class="facts">{facts}</div>
      <div class="rule"></div>
      <div class="prog">{prog}
        <div class="qr-card">
          <div class="qr-plate">{qr}</div>
          <div class="qr-say"><b>{cta}</b><span>{url}</span></div>
        </div>
      </div>
      <div class="tail"><span>{sponsors}</span><span>{venue_short}</span></div>
    </div>
  </div>
</div>
"""


LISTING = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster, ruled</title>
<style>
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  /* Fontshare's CDN serves these with the name table blanked to the string
     "false". A browser never looks — @font-face supplies the name — but a
     printed PDF embeds whatever the file calls itself, and one export went out
     carrying a font called "false". The copies in static/fonts have their
     names written back, one file per weight.

     Satoshi is cut at 300, 400, 500, 700 and 900 — there is no 600. A missing
     weight is not an error a browser reports: it takes the nearest face and,
     in some engines, smears it. The sheet asks only for weights that exist. */
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:900; src:url("fonts/satoshi-900.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  /* One ink on one ground, and every division drawn as a hairline rule. The
     layout is a stack of boxes with nothing between them, so the sheet has no
     margins in the usual sense — the rules are the margins. */
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{ground}; color:{art_ink}; box-sizing:border-box; padding:10mm;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
    font-family:"Satoshi","Helvetica Neue",sans-serif;
  }}
  .frame {{
    height:100%; box-sizing:border-box; border:.45mm solid {art_ink};
    display:flex; flex-direction:column;
  }}
  .row {{ display:flex; border-bottom:.45mm solid {art_ink}; }}
  .row:last-child {{ border-bottom:0; }}
  .cell {{ padding:7mm 8mm; box-sizing:border-box; }}
  .cell + .cell {{ border-left:.45mm solid {art_ink}; }}
  /* The listing. Day-of-month, then what happens, then when — the rhythm the
     reference gets its texture from. */
  .list {{ flex:1; }}
  .list ul {{ margin:0; padding:0; list-style:none; }}
  .list li {{
    font-size:8.8mm; line-height:1.26; font-weight:500; margin:0 0 2.2mm;
    display:flex; gap:3.5mm; align-items:baseline;
  }}
  .list .d {{ font-family:"JetBrains Mono",monospace; font-weight:600; flex:none; }}
  .list .who {{ flex:1; }}
  .list .who b {{ font-weight:700; }}
  .list .t {{ font-family:"JetBrains Mono",monospace; font-size:6.2mm; flex:none; opacity:.72; }}
  /* The month, big, with the diagonal above it. */
  .month {{ width:118mm; display:flex; flex-direction:column; }}
  .slash {{ height:52mm; }}
  .slash svg {{ display:block; width:100%; height:100%; }}
  .month h2 {{
    font-family:"Jost",sans-serif; font-weight:300; font-size:26mm;
    margin:auto 0 0; letter-spacing:-.01em; text-align:right; line-height:1;
  }}
  /* The picture, in its own box. */
  .plate {{ flex:1; position:relative; overflow:hidden; border-bottom:.45mm solid {art_ink}; }}
  .plate svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .stamp {{
    font-family:"Jost",sans-serif; font-weight:300; font-size:24mm;
    letter-spacing:.01em; line-height:1; padding:6mm 8mm;
  }}
  .foot {{ align-items:stretch; }}
  .name {{ flex:1; }}
  .name h1 {{
    font-family:"Jost",sans-serif; font-weight:400; font-size:26mm; line-height:1.02;
    margin:0; letter-spacing:-.012em;
  }}
  .name h1 b {{ font-weight:600; }}
  .name p {{
    font-family:"JetBrains Mono",monospace; font-size:4.2mm; letter-spacing:.14em;
    text-transform:uppercase; margin:4mm 0 0; opacity:.8;
  }}
  .badge {{ width:118mm; display:flex; flex-direction:column; justify-content:space-between; }}
  .qr-plate {{ width:34mm; height:34mm; background:{art_ink}; padding:1.8mm; box-sizing:border-box; align-self:flex-end; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
  .badge address {{
    font-style:normal; font-family:"JetBrains Mono",monospace; font-size:4mm;
    line-height:1.5; text-align:right; margin-top:5mm; opacity:.82;
  }}
</style>
<div class="sheet"><div class="frame">
  <div class="row">
    <div class="cell list"><ul>{listing}</ul></div>
    <div class="cell month">
      <div class="slash"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" preserveAspectRatio="none">
        <line x1="8" y1="92" x2="92" y2="8" stroke="{art_ink}" stroke-width="1.1" vector-effect="non-scaling-stroke"/>
      </svg></div>
      <h2>{month}</h2>
    </div>
  </div>
  <div class="row" style="flex:1"><div class="cell plate" style="flex:1;padding:0;border-bottom:0">{art}</div></div>
  <div class="row"><div class="cell stamp">{stamp}</div></div>
  <div class="row foot">
    <div class="cell name">
      <h1><b>{mark}</b> {year}</h1>
      <p>{full_name}</p>
    </div>
    <div class="cell badge">
      <div class="qr-plate">{qr}</div>
      <address>{venue_name}<br>{venue_addr}<br>{url}</address>
    </div>
  </div>
</div></div>
"""


FESTIVAL = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster, festival</title>
<style>
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  /* Fontshare's CDN serves these with the name table blanked to the string
     "false". A browser never looks — @font-face supplies the name — but a
     printed PDF embeds whatever the file calls itself, and one export went out
     carrying a font called "false". The copies in static/fonts have their
     names written back, one file per weight.

     Satoshi is cut at 300, 400, 500, 700 and 900 — there is no 600. A missing
     weight is not an error a browser reports: it takes the nearest face and,
     in some engines, smears it. The sheet asks only for weights that exist. */
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:900; src:url("fonts/satoshi-900.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi","Helvetica Neue",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  /* The drawing sets its own colour. Its strokes are currentColor, so with no
     colour of its own here it inherited the sheet's — which on a dark ground
     is white and happens to be right, and on paper is the near-black the type
     is set in. That is why the light sheet's formulas stayed black however
     often art_ink was changed: the palette value was reaching the recolour
     pass, finding no white to replace, and never reaching the page. */
  .art {{ position:absolute; inset:0; overflow:hidden; opacity:{art_alpha}; color:{art_ink}; }}
  .art svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .ghost {{ position:absolute; inset:0; overflow:hidden; opacity:{ghost_alpha}; }}
  .ghost svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* Held well back. In the reference the ground is a soft bloom that the type
     sits on without contest; ours is a field of small marks, which is busier,
     so it is dimmed further than a photograph would need to be. */
  .veil {{ position:absolute; inset:0; }}
  .veil svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* The sheet is 426x600: A2 plus 3mm of bleed all round, so 20mm here is
     17mm from the trim. The bottom was 16mm, which is 13mm trimmed — four
     millimetres shy of the other three sides, and a poster whose content sits
     lower than its own margin reads as sliding off the bottom edge. */
  .wrap {{ position:absolute; inset:0; padding:20mm; display:flex; flex-direction:column; }}
  .top {{ display:flex; justify-content:space-between; align-items:flex-start; }}
  .mark {{
    font-family:"Jost",sans-serif; font-weight:700; font-size:32mm;
    line-height:1; color:{hot}; letter-spacing:-.02em; margin:0;
  }}
  .mark span {{ font-weight:300; }}
  .stamps {{ color:{hot}; text-align:right; line-height:1.7; }}
  /* Mixed case, and the four letters of the acronym in the accent — the name
     is written so that K, O, L and T fall where they do, and capitals would
     hide it. */
  /* One quiet line under the mark, in the mono the sheet names its fields
     with. Set in the text face it was a second, smaller statement competing
     with the first; in the mono and in capitals it reads as a caption on the
     mark rather than as a line of its own, which is what it is — the mark
     spelled out. Held closer to the title and fainter for the same reason.

     5.8mm, which is the size at which the line ends where the mark ends. LeT
     2026 sets 155mm. The face is monospaced, so the width goes with the
     character count and nothing else: at 6.5mm the shorter name set 154.7mm
     over 33 characters, and 1st adds four more.

     The optical indent stays optical but the number changes with the face and
     the size: JetBrains Mono's sidebearing is 0.080 of the em against Jost's
     0.0738, so against a 32mm mark and a 5.8mm line the correction is 1.9mm. */
  .longname {{
    font-family:"JetBrains Mono",monospace; font-weight:600; font-size:5.8mm;
    letter-spacing:.1em; text-transform:uppercase; color:{ink};
    opacity:.46; margin:1.6mm 0 0 1.9mm;
  }}
  .cols h4 {{
    font-family:"JetBrains Mono",monospace; font-size:3.4mm; font-weight:500;
    letter-spacing:.16em; text-transform:uppercase; color:{hot}; margin:7mm 0 2mm;
  }}
  /* Names in one column, affiliations in another, the way the programme sets
     them. As plain lines each affiliation began wherever its name ended, so
     six of them made a ragged edge down the middle of the block. */
  .orgs {{
    display:inline-grid; grid-template-columns:auto auto; column-gap:4mm;
    row-gap:0; align-items:baseline;
  }}
  .orgs b {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:4.6mm; font-weight:700;
    color:{ink}; line-height:1.5; white-space:nowrap;
  }}
  /* Ranged right inside their column, so the affiliations make an edge of
     their own instead of six lines each ending wherever its name let it. */
  .orgs span {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:4.6mm; font-weight:400;
    color:{cool}; line-height:1.5; white-space:nowrap; text-align:right;
  }}
  .cols .theme {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:5mm; font-weight:700;
    color:{ink}; margin:0; line-height:1.3;
  }}
  /* The two rotated blocks down the left edge. */
  /* 4.5mm between the two, not 9. A rail line's own box is 11.9mm across and
     the space between them was 9.8mm — nearly a line's width of nothing, so
     the venue and the theme read as two separate marks rather than as the pair
     they are. Less than half the line box holds them together. */
  /* Not pinned to a measurement. The rails are the only thing between the
     title and the programme, so they take the space between them and sit in
     the middle of it: auto margins above and below share the free height
     equally, and the panel below keeps its place because the column is a fixed
     height and there is nothing left for it to move into. Fixed at 118mm the
     gap above and the gap below were whatever the two blocks happened to
     leave.

     Then nudged down 33mm. Auto margins centre the rails between the title and
     the panel, but the panel opens with the programme's right-hand column and
     the thing on the left they are actually read against is the date, which
     starts 66mm lower. Measured on the sheet: title bottom 61.3, date top
     403.9, so the midpoint is 232.6 and the rails were sitting at 199.8. */
  /* Out of the column, not in it. The rails were a flex item with auto
     margins, which centres them while there is room and pushes everything
     below them once there is not — and past a certain rail length there is
     not. That is what ate the sheet's bottom margin: 20mm on three sides and
     7mm on the fourth, with the foot all but touching the trim, and nothing
     said so because a poster that overflows still prints.

     Taken out of the flow it cannot push anything, and its size is free to be
     whatever the longest line needs. 223mm is where the auto margins were
     putting it: centred in the band between the title and the panel, which
     measured 52mm to 328mm, and then the same 33mm down. */
  .rails {{
    position:absolute; left:20mm; right:20mm; top:223mm;
    transform:translateY(-50%); display:flex; gap:4.5mm;
  }}
  .rail {{
    writing-mode:vertical-rl; transform:rotate(180deg);
    font-family:"Satoshi","Helvetica Neue",sans-serif; color:{hot};
  }}
  /* One line, sizes the other way round: the field name small, the thing
     itself large. Venue and Theme are the words a reader can
     supply for themselves — what they cannot is which venue and which theme,
     and that is what the edge should be saying at a distance.

     So everything the label had — the size, the accent, the weight — moves to
     the particular in one piece, and the label takes what the particular had:
     the small mono the sheet uses everywhere else to name a field, set quiet
     in the paper colour. Moving the size alone left the emphasis where it was
     and only made the loud thing small.

     A proportional face rather than the mono it started in: a monospaced face
     at this size sets 33 characters over 165mm and the rails would have run
     into the programme. 9mm rather than 10, for the same reason — Geist is
     wider than the Inter Tight this replaced, 177.7mm against 161.6mm on the
     venue line, which was 4mm past where the programme begins.

     The paper colour rather than the cool grey the sheet uses for a second
     voice elsewhere: these lines sit over the drawing rather than over flat
     ground, and a mid grey on a mottled mid ground is the one pairing that
     does not survive being printed.

     The field name is given a box of its own so both rails start their large
     text at the same point. VENUE measures 15.2mm and THEME 2026 measures
     30.4mm; set next to their own words the two would have begun 15mm apart
     and the edge would read as two unrelated lines rather than as a list.
     34mm is the longer of the two plus a word space. As inline-size, not
     width: the rails are turned, and the axis this has to hold is the one the
     text runs along, whichever way that ends up pointing. */
  /* Field names — VENUE, THEME, HOMEPAGE, ORGANISERS, the stamps at the top —
     all speak in the mono at one size. They were set at 4mm, 3.8mm and, in the
     case of Organizers, at whatever a browser gives an unstyled h4, which was
     16px. Nothing was gained by any of the differences. */
  .rail b, .side h4, .stamps, .prog-grid i u small {{
    font-family:"JetBrains Mono",monospace; font-size:3.8mm; font-weight:400;
    letter-spacing:.16em; text-transform:uppercase;
  }}
  /* Right-aligned in its box, so the label ends against the line it opens
     instead of floating a word's width away from it. text-align is resolved on
     the inline axis, which these rails have turned and one of them has turned
     again, so it is set logically. */
  .rail b {{
    display:inline-block; inline-size:32mm; vertical-align:baseline;
    text-align:end; padding-inline-end:2.6mm; box-sizing:border-box;
    color:{ink}; opacity:.72;
  }}
  .side h4 {{ color:{ink}; opacity:.72; margin:7mm 0 2.5mm; }}
  /* Black, not Bold. A contrast ratio says nothing about how much of the
     letter there is, and on a busy drawing that is most of what legibility is:
     at 900 the rails put down 12.0% ink against 10.4% at 700, and the thicker
     stroke is what lets the strip behind them stay lighter. */
  /* 8mm — as large as the sheet has room for, measured rather than guessed.
     Two things stop it. The rails run down the left edge and must finish above
     the date stack, which begins at 398mm; and the rails sit in auto margins,
     so past a certain length they stop being absorbed and start pushing the
     panel — and the foot with it — off the bottom of the sheet. At 8mm the
     rail is 264mm and the stack moves 2mm; at 8.5mm it moves 17mm and at 9mm
     the foot hangs 11mm past the trim.

     The cap went with it. 228mm was cutting the theme into two lines at any
     size worth reading, which is what made the edge small in the first place —
     the line was being made to fit a number that no longer meant anything.
     236mm is the theme's own length at 8mm plus a few millimetres, so a longer
     theme still wraps rather than running off the paper. */
  .rail span {{
    display:inline-block; max-inline-size:236mm; vertical-align:baseline;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:8mm;
    font-weight:900; letter-spacing:-.014em; line-height:1.22; color:{hot};
  }}
  /* A third rail on the opposite edge. It is a member of the same flex row
     rather than its own absolute block, which is what makes the alignment
     hold: the row stretches all three to one height, and since each is flipped
     within its own box the three labels finish on the same line. Given its own
     top it would have started level with the others but ended wherever its
     shorter text ran out, and the labels — the part the eye actually lines up
     — would have sat at three different heights.

     On the same 20mm column as everything else on that edge. It was pushed out
     to 8mm to stay clear of the programme, which does reach the column's right
     edge — but 100mm lower down, and the rail ends well above it. The only
     thing 8mm bought was a rail that did not line up with the schedule, the
     code or the sheet's own margin. */
  /* The homepage rail rides the same row as the other two but is read against
     different neighbours: on the right the things above and below it are the
     stamp at the top and the programme's first day, not the title and the
     date. Measured on the sheet: stamp bottom 26.5mm, Oct 7 at 338.2, so the
     midpoint is 182.3 and the row leaves it at 232.8. Fifty back up. */
  .rail-right {{ margin-left:auto; position:relative; top:-50.5mm; }}
  /* One thin line, not a statement. An address is a single fact and the left
     edge is where the sheet makes its statements; at the display size on the
     opposite edge it would have been a second shout for a URL. */
  .rail-right b {{
    inline-size:auto; margin-inline-end:2.4mm; color:{hot}; opacity:1;
  }}
  .rail-right span {{
    font-family:"JetBrains Mono",monospace; font-size:4.6mm; font-weight:400;
    letter-spacing:.06em; color:{ink}; opacity:.82;
  }}
  /* Including its label. The size on .rail em is the display size the left
     edge is set at, and it reaches here too — this rail is one of the rails.
     The whole line is small, which is the point of it. */
  /* The programme, against one right edge. It sits on the bottom padding: the
     rails used to hold it there by filling the space above it, and they no
     longer occupy any. */
  .panel {{ margin-top:auto; }}
  .bill {{ margin:0 0 0 auto; text-align:right; }}
  /* Named, like the organisers are. The block underneath was the only list on
     the sheet a reader had to work out for themselves; the column opposite has
     said Organizers over its names all along. Set against the right edge,
     because that is the edge this half is set against. */
  .bill h4 {{
    color:{ink}; opacity:.72; margin:0 0 3mm; text-align:right;
  }}

  /* The rule and the space between sessions live on the label, because a
     display:contents element cannot carry either. */

  .slot ul {{ margin:0; padding:0; list-style:none; }}
  /* Three columns, one grid, shared by the whole programme: the date, the
     name, the affiliation. The session titles and the hours are gone — a
     poster is read standing up and what it has to deliver is who is speaking;
     the schedule belongs on the page the QR leads to. */
  .prog-grid {{
    display:inline-grid; grid-template-columns:auto auto;
    column-gap:4mm; row-gap:0; justify-items:end; align-items:baseline;
    text-align:right;
  }}
  /* The session names range left. Everything to their right — the speakers,
     the affiliations, the days — is set against the sheet's right edge, so
     ranging these right too pushed them up against the names they label and
     left a ragged edge on the outside of the block, where the eye first meets
     it. The dayrow keeps its own alignment; it is a heading, not a label. */
  .prog-grid i {{
    font-style:normal; white-space:nowrap; align-self:baseline;
    justify-self:start; text-align:left;
  }}
  /* The day gets the whole width and sits at the right edge, over the
     affiliations rather than out beyond the session labels. It is the heading
     of the block under it, and a heading belongs on the side the block is set
     against — this one is set right.

     Where the break's air sits matters as much as how much of it there is. It
     began at 18.8mm against names that sit flush inside a day, which read as
     the list stopping rather than dividing; halving that left the rule 2.2mm
     under the last name of the first day and 3.8mm above the heading of the
     second, so it sat closer to the group it ended than to the one it opens. A
     rule belongs to what follows it. 5.5mm above and 2.0mm below now. */
  .prog-grid i.dayrow {{
    grid-column:1 / -1; justify-self:end; text-align:right; padding-top:0.5mm;
  }}
  /* 10.4mm. The names are what the sheet is for and they were set smaller
     than the date beside them; the list grows upward from a fixed foot, so the
     size is bounded by where the panel begins rather than by the column, and
     at 10.4 the block still opens 37mm below that. */
  .prog-grid em {{
    font-style:normal; font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:10.4mm;
    font-weight:700; line-height:1.34; letter-spacing:-.012em; color:{ink};
    white-space:nowrap;
  }}
  .prog-grid span {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:5.6mm; font-weight:400;
    color:{cool}; white-space:nowrap;
  }}
  /* The session, named once over the people in it. No hour with it: the title
     says what the block is, which is what a reader standing in front of the
     sheet wants; the times are on the page the code leads to. */
  .prog-grid i b {{
    display:block; font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:4.6mm;
    font-weight:700; letter-spacing:0; color:{hot};
  }}
  .prog-grid i u {{
    display:block; text-decoration:none; font-family:"Jost",sans-serif;
    font-size:7.6mm; font-weight:500; letter-spacing:-.01em; color:{ink};
  }}
  .prog-grid i u small {{
    display:block; font-weight:400; color:{cool}; margin-top:.8mm;
  }}
  .prog-grid i b {{ margin-bottom:0; }}
  .dayrule {{
    grid-column:1 / -1; width:100%; height:0; margin:5.5mm 0 1.5mm;
    border:0; border-top:.4mm solid rgba(255,255,255,.34);
  }}
  .dates {{ display:flex; justify-content:space-between; align-items:flex-end; gap:16mm; margin:0; }}

  /* The date keeps Inter Tight, the face it was set in before the sheet moved
     to Satoshi. It is the one block here that is pure figures, and Inter Tight
     is drawn narrow — at 23mm over three lines that reads as a stack rather
     than as three separate numbers, which is the whole of the effect. */
  .stack {{
    margin-bottom:1mm;
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:23mm;
    line-height:1.02; letter-spacing:-.03em; color:{hot};
  }}
  /* The hour each day runs from and to, against the day it belongs to. A
     travel claim wants the span and not just the dates, and the pair set on
     their own lines says which hour goes with which day without a word of
     explanation — which "09:00-17:15" under both dates would not.
     The same face and the same colour as the figures they sit with, at 0.7 of
     the size. Set small in the mono they read as an annotation on the date; at
     this size and in this colour they are part of it, which is what they are —
     the date is when, and the date is not complete without them. Not the full
     23mm: "10.7 09:00" would then run 160mm and the block would stop being a
     stack, which is the whole of its effect. */
  .stack small {{
    font-family:inherit; font-size:16mm; font-weight:700;
    letter-spacing:-.03em; color:inherit; margin-left:4mm;
  }}
  /* What the first hour in the stack is. The stack gives a span — 10:00 to
     18:10 across two days — and a span's opening figure reads as the edge of a
     range rather than as an instruction to be somewhere. This says which it
     is, in the mono the sheet names its fields with, so the number above it
     stops being one end of a bracket. It comes from the programme's first
     event, so it cannot drift from it. */
  .opens {{
    font-family:"JetBrains Mono",monospace; font-size:3.6mm; font-weight:500;
    letter-spacing:.16em; text-transform:uppercase; color:{cool};
    margin:2.5mm 0 0;
  }}
  /* The venue lives in the rail; the country is the one thing neither the rail
     nor the stack says, so it goes with the day. */
  .datesub {{ display:none; }}
  .side {{ flex:none; }}
  .side h4 {{ margin-top:7mm; }}
  .cols h4 {{
    font-family:"JetBrains Mono",monospace; font-size:3.6mm; font-weight:500;
    letter-spacing:.16em; text-transform:uppercase; color:{hot}; margin:0 0 3mm;
  }}
  .cols ul {{ margin:0; padding:0; list-style:none; }}
  .cols li {{
    font-size:5.2mm; font-weight:700; line-height:1.42; color:{ink};
    text-transform:uppercase; letter-spacing:.02em;
  }}
  .cols li span {{ font-weight:400; color:{cool}; text-transform:none; letter-spacing:0; }}
  .mid {{ text-align:center; }}
  .mid ul li {{ text-transform:none; font-weight:500; }}
  .r {{ text-align:right; }}
  .marks {{ display:flex; align-items:flex-end; gap:9mm; }}
  /* Height comes from logo_row, one mark at a time: the marks are matched
     on their letters, not on their boxes. */
  .marks img {{ width:auto; display:block; opacity:.72; }}
  /* The marks and the grant sit under both columns, and 9mm under a list set
     at 5.2mm/1.42 is barely more than one of its own lines — the row read as
     the last entry of the organisers' column rather than as the sheet's foot.
     18mm is a gap that belongs to neither, which is what it is for. The row
     itself is unchanged: this is space above it, not a bigger foot. */
  .foot {{
    display:flex; justify-content:space-between; align-items:flex-end; margin-top:18mm; gap:10mm;
    font-family:"JetBrains Mono",monospace; font-size:3.8mm; letter-spacing:.14em;
    text-transform:uppercase; color:{cool};
  }}
  .qr-plate {{ width:32mm; height:32mm; background:{art_ink}; padding:1.6mm; box-sizing:border-box; }}
  /* Centred over the code rather than ranged with the sheet's right edge. It
     is a label on the square below it, not a line of the foot: against the
     edge it read as a third item in the row, over the middle of the code it
     reads as its caption. */
  .top .cta {{ text-align:center; }}
  /* The acknowledgement, in the wording the grant requires. It takes the width
     the marks leave and sets small: it is a condition of funding rather than a
     line anybody reads the poster for, and at any larger size it would be
     arguing with the programme. */
  .grant {{
    flex:1; margin:0; align-self:flex-end;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:3.1mm;
    font-weight:400; line-height:1.42; color:{ink}; opacity:.62;
    text-align:right; word-break:keep-all;
  }}
  .foot .cta b {{ display:block; font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:4.6mm;
                  font-weight:700; color:{hot}; margin-bottom:2.5mm; letter-spacing:0;
                  text-transform:none; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
</style>
<div class="sheet">
  {ghost}<div class="art">{art}</div>
  <div class="veil"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 100" preserveAspectRatio="none">
    <defs><linearGradient id="v" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{ground}" stop-opacity="{veil1}"/>
      <stop offset=".22" stop-color="{ground}" stop-opacity="{veil2}"/>
      <stop offset=".52" stop-color="{ground}" stop-opacity="{veil3}"/>
      <stop offset=".70" stop-color="{ground}" stop-opacity="{veil4}"/>
      <stop offset="1" stop-color="{ground}" stop-opacity="{veil5}"/>
    </linearGradient></defs>
    <defs><linearGradient id="vx" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{ground}" stop-opacity="{veilx}"/>
      <stop offset=".10" stop-color="{ground}" stop-opacity="{veilx}"/>
      <stop offset="1" stop-color="{ground}" stop-opacity="0"/>
    </linearGradient></defs>
    <rect width="10" height="100" fill="url(#v)"/>
    <rect width="10" height="100" fill="url(#vx)"/>
  </svg></div>
  <div class="wrap">
    <div class="top">
      <div><h1 class="mark">{mark} <span>{year}</span></h1>
        <p class="longname">{long_name_ed}</p></div>
      <div class="cta"><b>{cta_short}</b><div class="qr-plate">{qr}</div></div>
    </div>
    <div class="rails">
      <div class="rail"><b>Venue</b><span>{venue_name}, {city}</span></div>
      {theme_rail}
      <div class="rail rail-right"><b>Homepage</b><span>{url}</span></div>
    </div>
    <div class="panel">
      <div class="dates">
        <div class="side">
          <div class="stack">{yyyy}.<br>{md1}<small>{hour1}</small> –<br>{md2}<small>{hour2}</small></div>
          <p class="opens">{opens}</p>
          <h4>Organizers</h4>
          <div class="orgs">{organisers}</div>
        </div>
        <div class="bill"><h4>Speakers</h4><div class="prog-grid">{programme}</div></div>
      </div>
      <div class="foot">
        <span class="marks">{logos}</span>
        <p class="grant">{grant}</p>
      </div>
    </div>
  </div>
</div>
"""


# ─────────────────────────────────────────────────────────────
# The two large-format pieces, in the sheet's own language: the
# coral mark in Jost, everything else in Satoshi, field names in
# the mono, the campus written out in formulas behind a veil.
#
# What changes is the reading distance. A poster is read at arm's
# length and can carry a programme; a banner is read across a
# room or a courtyard and can carry a name, a date and a place.
# Anything more is decoration at that size, so there is nothing
# more on either of them.
# ─────────────────────────────────────────────────────────────

BANNER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>LeT Workshop — banner, 6000x900mm</title>
<style>
  @page {{ size: 6000mm 900mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:900; src:url("fonts/satoshi-900.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:6000mm; height:900mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  /* The drawing is a block on the right, not a field under everything.
     Across the whole cloth it had to be held back by a veil wherever type sat
     on it, which is most of a six-metre banner — so the picture was faint
     everywhere in order to be readable anywhere. Given a third of the width
     and none of the type, it can be drawn at full strength. It is a different
     picture at that size, too: the campus is not legible as a campus in
     1900mm, and the clock tower is the one thing that survives being made
     small, so the artwork is cropped around the tower rather than scaled down
     from the band. */
  .stage {{
    position:absolute; top:0; right:0; bottom:0; width:2600mm; overflow:hidden;
    /* Bled off three edges, faded on the fourth. The fade is what keeps this
       from reading as a photograph pasted onto the cloth — the drawing thins
       into the ground the type is set on rather than stopping at a line.
       What was wrong before was the width, not the fade: at 1900mm the block
       cut the picture short, so the fade was eating a quarter of what little
       there was. At 2600 there is picture to spare.
       The gradient holds at nothing for its first 15% and only then begins to
       rise, reaching full at 33%. That is what keeps the credit line clear:
       the logos end at 3891mm, which is 19% into the block, and a ramp that
       started at the block's own left edge had the drawing at 70% strength
       behind them — measured, the ground under the right-hand marks was three
       times as busy as the ground under the rest of the row. Held back this
       way it is 22% there instead. */
    -webkit-mask-image:linear-gradient(to right, transparent 0, transparent 15%, #000 33%, #000 100%);
    mask-image:linear-gradient(to right, transparent 0, transparent 15%, #000 33%, #000 100%);
  }}
  .ghost {{ position:absolute; inset:0; overflow:hidden; opacity:.3; }}
  .art {{ position:absolute; inset:0; overflow:hidden; }}
  .art svg, .ghost svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* A banner is hung, and the top and bottom 60mm go into the hem or round a
     pole. Nothing that has to be read lives there. */
  /* The same keyline the X-banner and the square set carry, inset to the line
     the type is set to. It is what stops a dark field dissolving into whatever
     wall or crowd is behind it. */
  .frame {{
    position:absolute; inset:56mm; border:1.4mm solid {keyline};
    pointer-events:none;
  }}
  /* Everything the banner says is set against the left edge, in one column:
     the name, then the credit line under it. The right of the cloth is left to
     the drawing, because that is where the clock tower falls and a banner with
     type across its whole width has nothing to look at from a distance.
     `align-items:flex-start` keeps the blocks their own width rather than the
     column\'s, so the credit line does not stretch to meet the mark. */
  .wrap {{
    position:absolute; inset:56mm; padding:144mm 120mm 76mm;
    display:flex; flex-direction:column; align-items:flex-start;
    justify-content:space-between;
  }}
  /* The mark takes the accent here, as it does on the sheet. On the banner it
     used to be white with the accent spent on the date, on the reasoning that
     the loudest element should not also carry the colour — but the banner no
     longer has a date the size of the name to compete with, and a five-metre
     cloth read at forty metres is one word before it is anything else. */
  .mark {{
    font-family:"Jost",sans-serif; font-weight:700; font-size:360mm;
    line-height:.92; color:{hot}; letter-spacing:-.02em; margin:0;
  }}
  .mark span {{ font-weight:300; }}
  /* Beside the name, not under it. Six metres is a long line and a banner is
     read across rather than down: set below, the long name was a second row
     the eye had to come back for, and it is the same words as the mark said
     already. On the baseline it reads as the name's own expansion — "LeT
     Workshop, which is the Learning Theory Workshop" — in one pass. */
  .lead {{ display:flex; align-items:baseline; gap:70mm; }}
  .longname {{
    font-family:"Satoshi",sans-serif; font-weight:500; font-size:76mm;
    letter-spacing:-.01em; color:{ink}; opacity:.58; margin:0;
  }}
  /* The credit line every Korean banner carries: when, where, and under whose
     marks — one row, at the foot, in the order someone reads them. The hosts
     are their logos and nothing else. A row of marks needs no label: a
     university crest on a banner is already the sentence "run by", and the
     word in front of it only takes room from the marks themselves. */
  .strip {{ display:flex; align-items:center; gap:64mm; margin-left:13mm; }}
  .fact {{
    display:flex; align-items:baseline; gap:26mm;
    font-family:"Satoshi",sans-serif; font-weight:700; font-size:78mm;
    letter-spacing:-.014em; color:{ink};
  }}
  .fact b {{
    font-family:"JetBrains Mono",monospace; font-size:34mm; font-weight:400;
    letter-spacing:.16em; text-transform:uppercase; color:{hot};
  }}
  .rule {{ width:1.3mm; height:70mm; background:{ink}; opacity:.24; }}
  /* Bottom-aligned, because that is what logo_row's margins assume: it sets
     every mark to the same cap height and then pushes each one down by the
     distance its letters sit above its own bottom edge. Centred, that
     correction is applied to a row that has already been re-centred, and the
     letters come out on three different lines. */
  .marks {{ display:flex; align-items:flex-end; gap:62mm; margin-left:26mm; }}
  /* As published, at full strength. See logo_row's `flat` switch for why a
     credit row is not the place for a silhouette. Height is not set here —
     logo_row writes it per mark, from the ratios in data/site.yml. */
  .marks img {{ width:auto; display:block; }}
  /* The funder\'s own sentence. Smallest thing on a six-metre banner and the
     only one nobody will read from across the courtyard, which is right: it is
     there for the record, not for the passer-by. */
  .grant {{
    font-family:"JetBrains Mono",monospace; font-size:11mm; font-weight:400;
    letter-spacing:.06em; line-height:1.5; color:{ink}; opacity:.5;
    margin:24mm 0 0 13mm; max-width:2400mm;
  }}
</style></head><body>
<div class="sheet">
  <div class="stage">{ghost}<div class="art">{art}</div></div>
  <div class="frame"></div>
  <div class="wrap">
    <div class="lead">
      <h1 class="mark">{mark} <span>{year}</span></h1>
      <p class="longname">{long_name_ed}</p>
    </div>
    <div class="foot">
      <div class="strip">
        <span class="fact"><b>Date</b>{dates_long}</span>
        <span class="rule"></span>
        <span class="fact"><b>Venue</b>{venue_name}, {city}</span>
        <span class="rule"></span>
        <span class="marks">{logos_colour}</span>
      </div>
      <p class="grant">{grant}</p>
    </div>
  </div>
</div>
</body></html>
"""


XBANNER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>LeT Workshop — X-banner, 600x1800mm</title>
<style>
  @page {{ size: 600mm 1800mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:900; src:url("fonts/satoshi-900.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:600mm; height:1800mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  .ghost {{ position:absolute; inset:0; overflow:hidden; opacity:.3; }}
  .art {{ position:absolute; inset:0; overflow:hidden; }}
  .art svg, .ghost svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .veil {{ position:absolute; inset:0; }}
  .veil svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* An X-banner hangs from four corner eyelets and stands on the floor. The
     lower 250mm is below the knee of anyone reading it and is usually behind
     the frame's foot, so it carries the marks and nothing that must be read. */
  /* A keyline, as the square set has, inset to the line the type is set to.
     A banner is seen against a wall, a window and a crowd, and an edge is what
     stops it dissolving into whichever one is behind it. */
  .frame {{
    position:absolute; inset:46mm; border:1.2mm solid {keyline};
    pointer-events:none;
  }}
  .wrap {{
    position:absolute; inset:46mm; padding:80mm 44mm 60mm;
    display:flex; flex-direction:column;
  }}
  /* The three facts, evenly spaced between the title and the foot, each opened
     by a rule its label sits on. Centred as one block they left a third of the
     banner empty under them and the spacing read as an accident; distributed,
     the same air is divided into equal parts and reads as a measure. */
  .facts {{ flex:1; display:flex; flex-direction:column; justify-content:space-evenly; margin:0; }}
  .fact {{ padding-top:12mm; border-top:.8mm solid {rule_soft}; }}
  /* 100mm, not 132. The mark was cut when the name was four capitals over a
     year; it is two words now and the second is long. Measured on the rendered
     stand: at 132 the word "Workshop" set 532.6mm inside a 420mm column and
     hung 68.6mm past the keyline the rest of the banner is set inside. */
  .mark {{
    font-family:"Jost",sans-serif; font-weight:700; font-size:100mm;
    line-height:.98; color:{ink}; letter-spacing:-.02em; margin:0;
  }}
  .mark span {{ font-weight:300; }}
  /* 22mm. At 33 the name ran 565mm inside what was then a 474mm column and
     broke over two lines under a mark that is already two; the keyline since
     took the column to 414mm, and 24mm would clear it by three millimetres,
     which is not a margin. At 22 it sets 377mm and stays whole. */
  .longname {{
    font-family:"Satoshi",sans-serif; font-weight:500; font-size:22mm;
    letter-spacing:-.01em; color:{ink}; opacity:.58; margin:14mm 0 0 6mm;
  }}
  .field {{
    font-family:"JetBrains Mono",monospace; font-size:15mm; font-weight:400;
    letter-spacing:.16em; text-transform:uppercase; color:{hot};
    margin:0 0 6mm;
  }}
  /* 30mm is the largest size at which both of the two lines this sets — the
     venue and the theme — stay whole in the 420mm column the keyline leaves:
     the venue 355mm with the city under it, the theme 407mm on one line. At
     40mm the venue broke into three and the theme into two, and a banner read
     from across a hall wants each fact in one piece. */
  .line {{
    font-family:"Satoshi",sans-serif; font-weight:700; font-size:27mm;
    letter-spacing:-.014em; color:{ink}; margin:0;
  }}
  .stack small {{
    font-family:"JetBrains Mono",monospace; font-size:.26em; font-weight:400;
    letter-spacing:.06em; opacity:.66; margin-left:.16em;
  }}
  .stack {{
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:96mm;
    line-height:1.02; letter-spacing:-.03em; color:{ink}; margin:0;
  }}
  .foot {{
    display:flex; align-items:flex-end; justify-content:space-between; gap:30mm;
    padding-top:16mm; border-top:.8mm solid {rule_soft};
  }}
  /* 22mm, not 34. At 34 the two marks measured 386mm and the foot needed
     386 + 30 of gap + 110 of code = 526mm inside a 420mm column, so the code
     hung 62mm off the edge of the banner. */
  .marks {{ display:flex; align-items:flex-end; gap:24mm; }}
  .marks img {{ width:auto; display:block; opacity:.72; }}
  .cta {{ text-align:right; }}
  .cta b {{
    display:block; font-family:"Satoshi",sans-serif; font-size:16mm;
    font-weight:700; color:{hot}; margin-bottom:8mm;
  }}
  .qr-plate {{ width:110mm; height:110mm; background:{art_ink}; padding:5mm; box-sizing:border-box; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
  .grant {{
    font-family:"JetBrains Mono",monospace; font-size:5mm; font-weight:400;
    letter-spacing:.06em; line-height:1.6; color:{ink}; opacity:.5;
    margin:14mm 0 0;
  }}
</style></head><body>
<div class="sheet">
  {ghost}<div class="art">{art}</div>
  <div class="veil"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 100" preserveAspectRatio="none">
    <defs><linearGradient id="v" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{ground}" stop-opacity="{veil_x3}"/>
      <stop offset=".26" stop-color="{ground}" stop-opacity="{veil_x1}"/>
      <stop offset=".58" stop-color="{ground}" stop-opacity="{veil_x2}"/>
      <stop offset="1" stop-color="{ground}" stop-opacity="{veil_x4}"/>
    </linearGradient></defs>
    <rect width="10" height="100" fill="url(#v)"/>
  </svg></div>
  <div class="frame"></div>
  <div class="wrap">
    <div>
      <h1 class="mark">{mark}<br><span>{year}</span></h1>
      <p class="longname">{long_name_ed}</p>
    </div>
    <div class="facts">
      <div class="fact">
        <p class="field">Venue</p>
        <p class="line">{venue_name}<br>{city}</p>
      </div>
{theme_fact}      <div class="fact">
        <p class="field">Dates</p>
        <p class="stack">{yyyy}.<br>{md1}<small>{hour1}</small> –<br>{md2}<small>{hour2}</small></p>
      </div>
    </div>
    <div class="foot">
      <span class="marks">{logos}</span>
      <div class="cta"><b>{cta_short}</b><div class="qr-plate">{qr}</div></div>
    </div>
    <p class="grant">{grant}</p>
  </div>
</div>
</body></html>
"""


# ─────────────────────────────────────────────────────────────
# The square set, for a carousel. Six slides of 1080x1080 in one
# document, one under the other; tools/poster.py --layout social
# writes the page and the export slices it into six files.
#
# A phone holds it at arm's length for a second and a half, so
# each slide carries one thing. The cover is the only one with
# the drawing at full strength — behind a list of names it makes
# them unreadable, and a carousel that cannot be read in the
# first second is not read at all.
# ─────────────────────────────────────────────────────────────

SOCIAL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>LeT Workshop — square set</title>
<style>
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:900; src:url("fonts/satoshi-900.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; background:#000; }}
  .card {{
    position:relative; width:1080px; height:1080px; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi",sans-serif;
  }}
  .art, .ghost {{ position:absolute; inset:0; overflow:hidden; }}
  .ghost {{ opacity:.26; }}
  .art svg, .ghost svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* Every slide but the cover holds the drawing well down: it is the same
     picture doing the same job, but a list of names over it at this size is a
     list nobody reads. */
  .card.quiet .art {{ opacity:.42; }}
  .card.quiet .ghost {{ opacity:.20; }}
  .veil {{ position:absolute; inset:0;
    background:linear-gradient(180deg,
      {scrim1} 0%, {scrim2} 34%,
      {scrim3} 72%, {scrim4} 100%); }}
  .card.quiet .veil {{ background:linear-gradient(180deg,
      {scrim5} 0%, {scrim6} 50%, {scrim4} 100%); }}
  /* A keyline inset from the edge. A carousel is shown on a white feed and a
     black one, and a dark square with no edge bleeds into the first and
     vanishes into the second; the rule gives every slide the same frame and
     makes the set read as a set. It is also the margin the type is set to, so
     it is doing two jobs. */
  .frame {{
    position:absolute; inset:44px; border:1.5px solid {keyline};
    border-radius:6px; pointer-events:none;
  }}
  .pad {{ position:absolute; inset:44px; padding:52px 54px 48px; display:flex; flex-direction:column; }}
  .head {{ display:flex; align-items:baseline; justify-content:space-between; gap:24px; }}
  .kicker {{
    font-family:"JetBrains Mono",monospace; font-size:22px; font-weight:400;
    letter-spacing:.16em; text-transform:uppercase; color:{ink}; opacity:.72; margin:0;
  }}
  .kicker.hot {{ color:{hot}; opacity:1; }}
  .num {{ font-family:"JetBrains Mono",monospace; font-size:22px; letter-spacing:.16em;
          color:{ink}; opacity:.45; }}
  .mark {{
    font-family:"Jost",sans-serif; font-weight:700; font-size:176px;
    line-height:.94; color:{ink}; letter-spacing:-.02em; margin:0;
  }}
  .mark span {{ font-weight:300; }}
  .longname {{
    font-family:"Satoshi",sans-serif; font-weight:500; font-size:38px;
    letter-spacing:-.01em; color:{ink}; opacity:.6; margin:14px 0 0 7px;
  }}
  h2 {{
    font-family:"Satoshi",sans-serif; font-weight:700; font-size:74px;
    line-height:1.1; letter-spacing:-.02em; color:{ink}; margin:0;
  }}
  h2.ink {{ color:{ink}; }}
  .stack {{
    font-family:"Inter Tight",sans-serif; font-weight:700; font-size:118px;
    line-height:1.02; letter-spacing:-.03em; color:{ink}; margin:0;
  }}
  .body {{ font-size:32px; font-weight:400; line-height:1.45; color:{ink}; opacity:.82; margin:22px 0 0; }}
  /* The foot is the same on every slide: a rule, the address, and one fact
     that belongs to that slide. A single screenshot of any one of them still
     says where to go. */
  .foot {{
    margin-top:auto; padding-top:22px; border-top:1px solid {rule_soft};
    display:flex; align-items:baseline; justify-content:space-between; gap:24px;
    font-family:"JetBrains Mono",monospace; font-size:21px; letter-spacing:.1em;
    text-transform:uppercase; color:{ink}; opacity:.6;
  }}
  .foot b {{ color:{hot}; font-weight:400; opacity:1; }}
  .mid {{ margin:auto 0; }}
  .facts {{ font-family:"JetBrains Mono",monospace; font-size:26px; letter-spacing:.1em;
            text-transform:uppercase; color:{ink}; opacity:.78; line-height:2; margin:0; }}
  .facts b {{ color:{hot}; font-weight:400; }}
  /* Speakers, grouped under the session that holds them. Two columns so the
     affiliations make an edge, the way they do on the sheet. */
  /* The timetable. A row per session, opened by its hour and closed by a rule
     — the shape a printed programme has had for a century, and the reason it
     survives is that the eye can find one row in it without reading the rest.
     The hour is the column that makes that possible, and the earlier version
     of these slides left it out entirely. */
  .when-head {{ display:flex; align-items:baseline; justify-content:space-between;
                gap:24px; margin:0 0 6px; }}
  .when-head p {{ font-family:"Inter Tight",sans-serif; font-weight:700; font-size:56px;
                  letter-spacing:-.03em; color:{ink}; margin:0; }}
  .when-head p.hot {{ color:{ink}; }}
  .tags {{ display:flex; align-items:center; gap:14px; }}
  .tag {{
    font-family:"JetBrains Mono",monospace; font-size:20px; font-weight:500;
    letter-spacing:.14em; text-transform:uppercase; color:{hot};
    border:1.5px solid {hot}; border-radius:999px; padding:7px 16px;
  }}
  .tag.plain {{ color:{ink}; border-color:{rule_strong}; opacity:.8; }}
  .rows {{ margin-top:6px; }}
  .row {{
    display:grid; grid-template-columns:150px 1fr; column-gap:24px;
    padding:20px 0 18px; border-top:1.5px solid {rule_mid};
  }}
  .hour {{ font-family:"JetBrains Mono",monospace; font-size:28px; letter-spacing:.04em;
           color:{ink}; opacity:.72; margin:0; }}
  .what {{ font-family:"Satoshi",sans-serif; font-weight:700; font-size:38px;
           letter-spacing:-.014em; color:{ink}; margin:0 0 6px; line-height:1.16; }}
  .whom {{ font-family:"Satoshi",sans-serif; font-weight:400; font-size:29px;
           color:{ink}; opacity:.78; margin:0; line-height:1.4; }}
  .whom i {{ font-style:normal; font-size:24px; color:{cool}; }}
  .people {{ display:grid; grid-template-columns:auto auto; column-gap:22px; row-gap:0;
             align-items:baseline; justify-content:start; }}
  .people b {{ font-size:40px; font-weight:700; letter-spacing:-.014em; color:{ink};
               line-height:1.36; white-space:nowrap; }}
  .people span {{ font-size:28px; font-weight:400; color:{cool}; text-align:right; white-space:nowrap; }}
  .orgs2 {{ display:grid; grid-template-columns:auto auto; column-gap:22px;
            align-items:baseline; justify-content:start; }}
  .orgs2 b {{ font-size:36px; font-weight:700; color:{ink}; line-height:1.52; white-space:nowrap; }}
  .orgs2 span {{ font-size:28px; font-weight:400; color:{cool}; text-align:right; white-space:nowrap; }}
  .marks {{ display:flex; align-items:flex-end; gap:38px; }}
  .marks img {{ width:auto; display:block; opacity:.72; }}
  .qr-plate {{ width:186px; height:186px; background:{art_ink}; padding:9px; box-sizing:border-box; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
  .join {{ display:flex; align-items:flex-end; justify-content:space-between; gap:30px; margin-top:34px; }}
</style></head><body>

<div class="card">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker hot">{eyebrow}</p><span class="num">1/6</span></div>
    <div class="mid"></div>
    <div>
      <h1 class="mark">{mark} <span>{year}</span></h1>
      <p class="longname">{long_name_ed}</p>
    </div>
    <div class="foot"><span><b>{yyyy}.{md1}–{md2}</b></span><span>{venue_name}, {city}</span></div>
  </div>
</div>

<div class="card quiet">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker">What it is</p><span class="num">2/6</span></div>
    <div class="mid">
      {theme_social}<p class="body">{blurb}</p>
    </div>
    <div class="foot"><span>{url}</span><span><b>Free to attend</b></span></div>
  </div>
</div>

<div class="card quiet">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker">When &amp; where</p><span class="num">3/6</span></div>
    <div class="mid">
      <p class="stack">{yyyy}.<br>{md1}–{md2}</p>
      <h2 class="ink" style="font-size:48px;margin-top:32px">{venue_name}</h2>
      <p class="body" style="font-size:28px;margin-top:8px">{venue_addr}</p>
      <p class="facts" style="margin-top:26px">{rooms}</p>
    </div>
    <div class="foot"><span>2 days · Korean</span><span><b>Details are tentative</b></span></div>
  </div>
</div>

<div class="card quiet">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker">Programme</p><span class="num">4/6</span></div>
    <div class="when-head">
      <p class="hot">{day1_date}</p><p>{day1_span}</p>
    </div>
    <div class="tags"><span class="tag">{day1_label}</span><span class="tag plain">{room}</span></div>
    <div class="rows mid">{day1_rows}</div>
    <div class="foot"><span>Day 1 of 2</span><span>Programme subject to change</span></div>
  </div>
</div>

<div class="card quiet">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker">Programme</p><span class="num">5/6</span></div>
    <div class="when-head">
      <p class="hot">{day2_date}</p><p>{day2_span}</p>
    </div>
    <div class="tags"><span class="tag">{day2_label}</span><span class="tag plain">{room}</span></div>
    <div class="rows mid">{day2_rows}</div>
    <div class="foot"><span>Day 2 of 2</span><span>Programme subject to change</span></div>
  </div>
</div>

<div class="card quiet">
  {ghost}<div class="art">{art}</div><div class="veil"></div><div class="frame"></div>
  <div class="pad">
    <div class="head"><p class="kicker">Organizers</p><span class="num">6/6</span></div>
    <div class="mid">
      <div class="orgs2">{organisers}</div>
      <div class="join">
        <div>
          <p class="kicker hot" style="margin-bottom:12px">Registration {reg_note}</p>
          <p class="body" style="font-size:30px;margin:0 0 24px">{url}</p>
          <span class="marks">{logos}</span>
        </div>
        <div class="qr-plate">{qr}</div>
      </div>
    </div>
    <div class="foot"><span>{mark} {year}</span><span><b>See you in {city}</b></span></div>
  </div>
</div>

</body></html>
"""
# ─────────────────────────────────────────────────────────────
# Name badges, 90x130mm — the usual insert for a lanyard holder.
# One card per page, so a print shop can take the file as it is.
#
# A badge is read across a handshake, which is about a metre, and
# what is read is the name. Everything else is for the second
# look: the affiliation to place the person, the role to say why
# they are on the programme, the mark so a badge left on a table
# still says which workshop it belongs to.
# ─────────────────────────────────────────────────────────────

BADGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>LeT Workshop — name badges, 90x130mm</title>
<style>
  @page {{ size: 90mm 130mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:900; src:url("fonts/satoshi-900.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; background:#000; }}
  .card {{
    position:relative; width:90mm; height:130mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi",sans-serif;
    page-break-after:always; break-after:page;
  }}
  .card:last-child {{ page-break-after:auto; break-after:auto; }}
  /* The drawing is carried once, in the stylesheet, and the twenty-one cards
     reference it. Inlined into each card the document came to 21MB and Chrome
     would not finish printing it; as one data URI behind a background-image it
     is stored once and painted twenty-one times.

     Held right down either way. It is why the badge belongs to this workshop
     and not another, and it is the one thing on the card that must not compete
     with a name read across a handshake. */
  .art, .ghost {{ position:absolute; inset:0; background-position:center;
                  background-size:cover; background-repeat:no-repeat; }}
  .art {{ background-image:url("{art_url}"); opacity:.34; }}
  .ghost {{ background-image:url("{ghost_url}"); opacity:.16; }}
  .veil {{ position:absolute; inset:0;
    background:linear-gradient(180deg,
      {scrim1} 0%, {scrim5} 46%, {scrim4} 100%); }}
  .pad {{ position:absolute; inset:0; padding:9mm 8mm 8mm; display:flex; flex-direction:column; }}
  .top {{ display:flex; align-items:baseline; justify-content:space-between; gap:4mm; }}
  /* 9mm and unbreakable. At 11 the mark measured 53mm of the 74mm the card
     has, the date column took the rest, and the mark wrapped onto two lines —
     a wordmark split across a line break stops being a wordmark. */
  .mark {{
    font-family:"Jost",sans-serif; font-weight:700; font-size:9mm; white-space:nowrap;
    line-height:1; color:{ink}; letter-spacing:-.02em; margin:0;
  }}
  .mark span {{ font-weight:300; }}
  .when {{
    font-family:"JetBrains Mono",monospace; font-size:2.8mm; letter-spacing:.1em;
    text-transform:uppercase; color:{ink}; opacity:.5; text-align:right; line-height:1.5;
  }}
  /* The name sits above centre, not on it: a lanyard holder curls forward at
     the bottom and a card worn on a chest is read from above. */
  .who {{ margin-top:13mm; }}
  .role {{
    display:inline-block; font-family:"JetBrains Mono",monospace; font-size:2.9mm;
    font-weight:500; letter-spacing:.16em; text-transform:uppercase; color:{hot};
    border:.3mm solid {hot}; border-radius:1.6mm; padding:1.4mm 2.6mm; margin:0 0 4mm;
  }}
  .role.plain {{ color:{ink}; border-color:{rule_strong}; opacity:.7; }}
  .name {{
    font-family:"Satoshi",sans-serif; font-weight:700; font-size:11mm;
    line-height:1.12; letter-spacing:-.016em; color:{ink}; margin:0;
  }}
  .name-ko {{
    font-family:"Satoshi",sans-serif; font-weight:500; font-size:5.4mm;
    color:{ink}; opacity:.62; margin:1.6mm 0 0;
  }}
  .affil {{
    font-family:"Satoshi",sans-serif; font-weight:500; font-size:5mm;
    color:{cool}; margin:3.4mm 0 0;
  }}
  /* Ruled space instead of a printed name, for anyone registering on the day.
     The rule is what tells a person there is something to write. */
  .write {{ margin-top:6mm; }}
  .write i {{ display:block; height:.35mm; background:{rule_mid}; margin-bottom:9mm; }}
  .foot {{
    margin-top:auto; padding-top:4mm; border-top:.3mm solid {rule_soft};
    display:flex; align-items:flex-end; justify-content:space-between; gap:4mm;
    font-family:"JetBrains Mono",monospace; font-size:2.7mm; letter-spacing:.1em;
    text-transform:uppercase; color:{ink}; opacity:.55;
  }}
  .foot .longname {{ margin:0; max-width:44mm; line-height:1.5; }}
  .qr-plate {{ width:16mm; height:16mm; background:{art_ink}; padding:.8mm; box-sizing:border-box; flex:none; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
</style></head><body>
{badges}
</body></html>
"""


def listing_html(program):
    """One line per session: day of the month, who, and when."""
    out = []
    for day in program["days"]:
        dom = str(day["date"]).split("-")[-1]
        for e in day["events"]:
            if e.get("type") not in ("block", "tutorial", "keynote"):
                continue
            people = [s["name"] for s in e.get("speakers", []) if s.get("name") and s["name"] != "TBD"]
            if not people:
                continue
            out.append(
                f'<li><span class="d">{esc(dom)}</span>'
                f'<span class="who"><b>{esc(e["title"])}</b> &middot; {esc(", ".join(people))}</span>'
                f'<span class="t">{esc(e.get("start", ""))}</span></li>'
            )
    return "".join(out)


ACADEMIC = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster, academic</title>
<style>
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Jost"; font-weight:100 900; src:url("fonts/jost-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"JetBrains Mono"; font-weight:400 600; src:url("fonts/jetbrains-mono-latin.woff2") format("woff2"); }}
  /* Fontshare's CDN serves these with the name table blanked to the string
     "false". A browser never looks — @font-face supplies the name — but a
     printed PDF embeds whatever the file calls itself, and one export went out
     carrying a font called "false". The copies in static/fonts have their
     names written back, one file per weight.

     Satoshi is cut at 300, 400, 500, 700 and 900 — there is no 600. A missing
     weight is not an error a browser reports: it takes the nearest face and,
     in some engines, smears it. The sheet asks only for weights that exist. */
  @font-face {{ font-family:"Satoshi"; font-weight:300; src:url("fonts/satoshi-300.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:400; src:url("fonts/satoshi-400.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:500; src:url("fonts/satoshi-500.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:700; src:url("fonts/satoshi-700.woff2") format("woff2"); }}
  @font-face {{ font-family:"Satoshi"; font-weight:900; src:url("fonts/satoshi-900.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{ground}; color:{ink}; font-family:"Satoshi","Helvetica Neue",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  /* The picture is an accent here, not a field. In the sheet this follows, a
     wireframe surface runs down the right edge and into the corners and the
     type sits on plain ground; the formulas do the same job, held right back
     and masked away from the column the names occupy. */
  .art {{ position:absolute; inset:0; overflow:hidden; opacity:.62; }}
  .art svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .art {{
    -webkit-mask-image: radial-gradient(115% 78% at 108% 30%, #000 12%, transparent 62%),
                        radial-gradient(85% 55% at -8% 88%, #000 8%, transparent 60%);
    mask-image: radial-gradient(115% 78% at 108% 30%, #000 12%, transparent 62%),
                radial-gradient(85% 55% at -8% 88%, #000 8%, transparent 60%);
  }}
  .wrap {{ position:absolute; inset:0; padding:26mm 24mm 0; display:flex; flex-direction:column; }}
  h1 {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:24mm;
    line-height:1.05; letter-spacing:-.02em; margin:0 0 10mm; color:#fff;
  }}
  .when {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:11mm;
    line-height:1.36; color:{gold}; margin:0 0 14mm;
  }}
  .when span {{ display:block; }}
  .when .thm {{ color:{ink}; font-weight:500; font-size:8.6mm; margin-top:3mm; }}
  .bill {{ display:grid; grid-template-columns:1fr 1fr; gap:9mm 12mm; margin:0; padding:0; }}
  .bill li {{ list-style:none; margin:0 0 9mm; }}
  .bill b {{
    display:block; font-size:13mm; font-weight:700; line-height:1.1;
    letter-spacing:-.014em; color:#fff;
  }}
  .bill span {{
    display:block; font-size:7.6mm; font-weight:400; line-height:1.2;
    color:{cool}; margin-top:1.2mm;
  }}
  /* The strip along the foot, a shade darker than the sheet. */
  .band {{
    position:absolute; left:0; right:0; bottom:0; height:118mm;
    background:{band}; border-top:.4mm solid rgba(255,255,255,.10);
    padding:14mm 24mm; box-sizing:border-box; display:flex; gap:14mm; align-items:flex-start;
  }}
  .band h4 {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:7mm; font-weight:700;
    color:{gold}; margin:0 0 4.5mm;
  }}
  .orgs {{ flex:1; }}
  .orgs ul {{ margin:0; padding:0; list-style:none; }}
  .orgs li {{ font-size:7mm; font-weight:700; color:#fff; line-height:1.52; }}
  .orgs li span {{ font-weight:400; color:{cool}; }}
  .cta {{ text-align:center; }}
  .qr-plate {{ width:44mm; height:44mm; background:#fff; padding:2mm; box-sizing:border-box; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
  .cta b {{
    display:block; font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:6.4mm;
    font-weight:700; color:{gold}; margin-top:3.5mm;
  }}
  .site {{
    position:absolute; left:24mm; right:24mm; bottom:9mm;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-size:5.6mm; font-weight:500;
    color:#fff; display:flex; justify-content:space-between; align-items:baseline;
  }}
  .site span {{ color:{cool}; font-size:4.6mm; }}
</style>
<div class="sheet">
  <div class="art">{art}</div>
  <div class="wrap">
    <h1>{mark} {year}<br>{full_title}</h1>
    <p class="when"><span>{dates_long}</span><span>{venue_name}, {city}, {country}</span><span class="thm">{theme}</span></p>
    <ul class="bill">{bill_academic}</ul>
  </div>
  <div class="band">
    <div class="orgs">
      <h4>Organizers</h4>
      <ul>{organisers}</ul>
    </div>
    <div class="cta">
      <div class="qr-plate">{qr}</div>
      <b>{cta_short}</b>
    </div>
  </div>
  <div class="site"><span>{sponsors}</span><b>{url}</b></div>
</div>
"""


CIVIC = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster, civic</title>
<style>
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter"; font-weight:400 700; src:url("fonts/inter-latin.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{paper2}; color:{carbon}; font-family:"Inter",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  /* The chevron. One flat shape, cut from the ground, that the rest of the
     sheet is arranged around — the whole device of the poster this follows. */
  .shape {{ position:absolute; inset:0; }}
  .shape svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  /* And the picture as a band along the foot, in ink rather than light. */
  .band {{ position:absolute; left:0; right:0; bottom:0; height:170mm; overflow:hidden; }}
  .band svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  .rail {{
    position:absolute; right:34mm; top:34mm; height:250mm;
    border:1.2mm solid {sky}; padding:9mm 7mm; box-sizing:border-box;
  }}
  .rail h1 {{
    writing-mode:vertical-rl; margin:0; font-family:"Satoshi","Helvetica Neue",sans-serif;
    font-weight:700; font-size:19mm; letter-spacing:.06em; line-height:1;
    text-transform:uppercase; color:{carbon};
  }}
  .rail2 {{
    position:absolute; right:12mm; top:34mm;
    writing-mode:vertical-rl; font-family:"Satoshi","Helvetica Neue",sans-serif;
    font-weight:700; font-size:11mm; letter-spacing:.1em; text-transform:uppercase;
    color:{carbon};
  }}
  .blurb {{
    position:absolute; right:14mm; top:300mm; width:60mm;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:7mm;
    line-height:1.3; color:{carbon};
  }}
  .left {{ position:absolute; left:26mm; top:104mm; width:146mm; }}
  .kicker {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:6.4mm;
    letter-spacing:.06em; text-transform:uppercase; margin:0 0 6mm; line-height:1.24;
  }}
  .when {{ font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:9mm; line-height:1.18; margin:0 0 3mm; }}
  .where {{ font-size:4.8mm; line-height:1.4; color:{carbon2}; margin:0 0 14mm; }}
  .grp {{ margin:0 0 9mm; }}
  .grp h4 {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:500; font-size:4.2mm;
    letter-spacing:.1em; text-transform:uppercase; color:{carbon2}; margin:0 0 2.5mm;
  }}
  .grp ul {{ margin:0; padding:0; list-style:none; }}
  .grp li {{ margin:0 0 3.4mm; }}
  .grp b {{ display:block; font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:8mm; line-height:1.1; }}
  .grp span {{ display:block; font-size:4.4mm; color:{carbon2}; line-height:1.34; margin-top:.8mm; }}
  .side {{ position:absolute; right:14mm; top:336mm; width:104mm; font-size:4.8mm; line-height:1.46; color:{carbon}; }}
  .cols h4 {{
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:500; font-size:4mm;
    letter-spacing:.1em; text-transform:uppercase; color:{carbon2}; margin:0 0 2mm;
  }}
  .side ul {{ margin:0 0 8mm; padding:0; list-style:none; }}
  .side a {{ color:{carbon}; font-weight:700; }}
  .qr-plate {{ position:absolute; left:26mm; bottom:22mm; width:36mm; height:36mm; background:#fff; padding:1.8mm; box-sizing:border-box; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
</style>
<div class="sheet">
  <div class="shape"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 426 600" preserveAspectRatio="none">
    <path d="M196 322 L300 246 L300 322 L404 246 L404 486 L300 486 L300 412 L196 486 Z" fill="{sky}"/>
  </svg></div>
  <div class="band">{art}</div>
  <div class="rail"><h1>{mark} {year}</h1></div>
  <div class="rail2">{full_name}</div>
  <p class="blurb">{theme}</p>
  <div class="left">
    <p class="kicker">{eyebrow}</p>
    <p class="when">{dates_long}</p>
    <p class="where">{venue_name}<br>{city}, {country}</p>
    <div class="grp"><h4>Day 1 · {d1}</h4><ul>{day1}</ul></div>
    <div class="grp"><h4>Day 2 · {d2}</h4><ul>{day2}</ul></div>
  </div>
  <div class="side">
    <h4>Organizers</h4><ul>{organisers}</ul>
    <p>Programme and registration<br><a>{url}</a></p>
  </div>
  <div class="qr-plate">{qr}</div>
</div>
"""


BAUHAUS = """<!doctype html>
<meta charset="utf-8">
<title>{name} — A2 poster, bauhaus</title>
<style>
  @page {{ size: 426mm 600mm; margin: 0; }}
  @font-face {{ font-family:"Inter Tight"; font-weight:100 900; src:url("fonts/inter-tight-latin.woff2") format("woff2"); }}
  @font-face {{ font-family:"Inter"; font-weight:400 700; src:url("fonts/inter-latin.woff2") format("woff2"); }}
  html, body {{ margin:0; padding:0; }}
  .sheet {{
    position:relative; width:426mm; height:600mm; overflow:hidden;
    background:{paper}; color:{carbon}; font-family:"Inter",sans-serif;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  .hair {{ position:absolute; background:rgba(27,27,27,.22); }}
  .vline {{ left:212mm; top:0; bottom:0; width:.25mm; }}
  /* The disc, half behind the picture. */
  .disc {{ position:absolute; left:96mm; top:214mm; width:150mm; height:150mm; border-radius:50%; background:{accent}; }}
  .plate {{ position:absolute; left:212mm; top:214mm; right:0; height:290mm; overflow:hidden; }}
  .plate svg {{ position:absolute; inset:0; width:100%; height:100%; display:block; }}
  h1 {{
    position:absolute; left:24mm; top:26mm; margin:0;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:78mm;
    line-height:.86; letter-spacing:-.045em; text-transform:lowercase;
  }}
  .motto {{
    position:absolute; left:24mm; top:246mm; margin:0; width:64mm;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:11mm;
    line-height:1.18; letter-spacing:-.02em; text-transform:lowercase;
  }}
  .motto i {{ font-style:normal; color:{accent}; }}
  .meta {{ position:absolute; left:228mm; top:30mm; width:110mm; font-size:6.4mm; line-height:1.44; text-transform:lowercase; }}
  .meta .lead {{ color:{carbon2}; margin:0 0 6mm; }}
  .meta .big {{ font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:8mm; line-height:1.24; margin:0 0 5mm; }}
  .meta .red {{ color:{accent}; font-weight:700; margin:0 0 8mm; }}
  .meta .hours {{ color:{carbon2}; margin:0; }}
  .dates {{
    position:absolute; right:22mm; top:26mm; text-align:right;
    font-family:"Satoshi","Helvetica Neue",sans-serif; font-weight:700; font-size:19mm; line-height:1.1;
  }}
  .dates hr {{ border:0; border-top:.4mm solid {carbon}; margin:3mm 0; }}
  .dates small {{ display:block; font-size:11mm; font-weight:500; }}
  .names {{
    position:absolute; left:24mm; top:398mm; width:172mm; margin:0; padding:0; list-style:none;
    font-size:6.4mm; line-height:1.66; text-transform:lowercase;
    columns:2; column-gap:10mm;
  }}
  .tickets {{
    position:absolute; left:24mm; bottom:44mm; font-size:6mm; line-height:1.5; text-transform:lowercase;
  }}
  .tickets b {{ display:block; color:{accent}; font-weight:700; }}
  .swatch {{ position:absolute; left:24mm; bottom:20mm; width:12mm; height:12mm; background:{accent}; }}
  .dots {{ position:absolute; right:24mm; bottom:26mm; display:grid; grid-template-columns:repeat(5,5mm); gap:4mm; }}
  .dots i {{ width:2.6mm; height:2.6mm; border-radius:50%; background:{paper}; display:block; }}
  .credit {{
    position:absolute; right:6mm; bottom:26mm; writing-mode:vertical-rl;
    font-size:3.4mm; color:{carbon2};
  }}
  .qr-plate {{ position:absolute; right:22mm; top:150mm; width:34mm; height:34mm; background:{paper}; padding:1.6mm; box-sizing:border-box; }}
  .qr-plate svg {{ display:block; width:100%; height:100%; }}
</style>
<div class="sheet">
  <div class="hair vline"></div>
  <div class="disc"></div>
  <div class="plate">{art}</div>
  <h1>{mark}<br>{year}</h1>
  <p class="motto">theory<br>follows<br>practice<i>.</i></p>
  <div class="meta">
    <p class="lead">{eyebrow}</p>
    <p class="big">{venue_name}<br>{city}, {country}</p>
    <p class="red">{theme}</p>
    <p class="hours">{full_name}<br>{days_long}</p>
  </div>
  <div class="dates">{d1}<hr>{d2}<small>{yyyy}</small></div>
  <ul class="names">{names_flat}</ul>
  <div class="qr-plate">{qr}</div>
  <p class="tickets">programme &amp; registration<br><b>{url}</b></p>
  <div class="swatch"></div>
  <div class="dots">{dots}</div>
  <div class="credit">{sponsors}</div>
</div>
"""


def festival_bits(program, organizers, site):
    """The pieces the festival sheet needs that the others do not."""
    bill, sess = [], []
    for day in program["days"]:
        for e in day["events"]:
            if e.get("type") not in ("block", "tutorial", "keynote"):
                continue
            # Every slot the session has, named or not. A session with nobody
            # named yet is still a session, and leaving it off makes the day
            # look shorter than it is; a session with one name and one slot
            # still open is the same argument for the slot. Reading only the
            # named ones dropped the second half of Bandits II the moment the
            # first half was filled — the sheet quietly lost a talk.
            people = [
                s if s.get("name") and s["name"] != "TBD" else {"name": "TBD", "affil": ""}
                for s in e.get("speakers", []) or []
            ]
            if not people:
                continue
            sess.append(f"<li>{esc(e['title'])}</li>")
            for p in people:
                bill.append(
                    f'<li>{esc(p["name"])}<sup>{esc(p.get("affil", ""))}</sup></li>'
                )
    # Two cells per person, not one line each: the affiliations then form a
    # column of their own instead of starting wherever the name happens to end.
    orgs = "".join(
        f'<b>{esc(m["name"])}</b><span>{esc(m.get("affil", ""))}</span>'
        for m in organizers["members"]
    )
    days = " ".join(str(d["date"]).split("-")[-1] for d in program["days"])
    return "".join(bill), "".join(sess), orgs, days


# The pixel size the photographic layers are generated at, per layout. Not the
# print size — this is the raster the duotone is computed on, and it only has to
# match the shape of the piece so nothing is cropped into or stretched across.
ART_FIT = {
    # The banner's drawing is cut to the shape of the block it fills — 1900 x
    # 900mm on the right of the cloth — so there is nothing left to crop and
    # nothing to squash. It is cropped around the clock tower rather than taken
    # across the campus: at a third of the cloth's width the campus stops being
    # legible as a campus, and the tower is what survives being made small.
    "banner": "xMidYMid slice",
}

GHOST_SIZE = {
    "civic": (1700, 820),
    "listing": (1700, 1520),
    "bauhaus": (1000, 1360),
    "banner": (1800, 623),      # the 2600 x 900mm block on the right, not the cloth
    "xbanner": (900, 2700),     # 600 x 1800mm
    "social": (1400, 1400),     # 1080 x 1080 square
    "badge": (900, 1300),       # 90 x 130mm
}


# The two sheets that are printed. Everything else in the palette is shared;
# a scheme is only what has to change to turn the sheet over.
#
# The light one is not the dark one with the colours swapped. Ink on paper is
# the opposite job — the drawing has to be dark marks with the ground showing
# between them rather than light marks on a dark field, so it needs its own
# artwork from `formula-art.py --invert`. The veil almost disappears: it exists
# to hold a photograph back from type on a dark ground, and over a pale one it
# simply repaints the sheet in the ground colour.
#
# The accent is the dark sheet's coral, carried down. It used to be the same
# value in both, on the reasoning that the two sheets are one poster printed
# either way round and a poster whose accent changes with the paper is two
# posters. That held while the accent only set session labels. It stopped
# holding when the accent took the name: measured against the ground actually
# behind it, #ff8a75 is 1.75:1 on the sheet and 1.66:1 on the banner, and six
# metres of cloth read at forty is one word before it is anything else.
#
# So it is deepened rather than replaced. Same hue — 9.1 degrees, to the
# decimal — with the saturation up and the value down, which is what "the same
# coral, printed heavier" means numerically. That lands at 3.25:1 on the sheet
# and 3.07:1 on the banner, over the 3:1 the large type it sets is held to.
# The dark sheet keeps #ff8a75: there it measures 6.2:1 and has nothing to
# apologise for.
#
# What actually shipped lived in a --palette argument typed at a shell for a
# while, and this dict drifted behind it. It is the same values now, which is
# what makes tools/export-poster.py able to ask for the scheme by name.
SCHEMES = {
    "light": {
        "ground": "#cfe4f5", "ground2": "#b9d6ee", "band": "#b9d6ee",
        "hot": "#db472c", "art_alpha": "1",
        # The formulas, not the type. At #16324f the darkest strokes were very
        # nearly black on paper and read as holes punched in the sheet rather
        # than as writing over it; this is the same hue carried up out of
        # the bottom of the range and turned further towards blue, so the
        # densest part of the drawing is a colour rather than an absence.
        # A stop further up, at #2c5480, the campus stopped being legible as a
        # building — the drawing is the only thing carrying the picture on this
        # sheet, and it has to stay dense enough to draw with.
        "art_ink": "#234a75", "ink": "#0d2137", "cool": "#456080",
        "veil1": ".20", "veil2": "0", "veil3": "0", "veil4": ".74", "veil5": ".93",
        "veilx": ".10", "ghost_alpha": ".45",
        # The photograph behind the formulas, printed in paper tones. The two
        # defaults are for a dark ground — a near-black shadow and a pale blue
        # highlight — and on paper that reads as a negative: the sky comes out
        # heavier than the building in front of it. Here the dark end takes
        # ink and the light end is the paper itself, driven a little harder
        # than the default, because on a pale sheet the photograph has to carry
        # the whole difference between a pale building and a pale sky.
        "ghost_shadow": "#1b3a5c", "ghost_light": "#cfe4f5",
        "ghost_contrast": "1.15",
        # The other four, turned over the same way: the veil almost gone where
        # the picture is and back at the ends where type has to be read off it,
        # and every rule and keyline in ink rather than in paper.
        "veil_b_mid1": ".60", "veil_b_mid2": ".14", "veil_b_end": ".80",
        "veil_x1": ".10", "veil_x2": ".20", "veil_x3": ".60", "veil_x4": ".88",
        "scrim1": "rgba(207,228,245,.30)", "scrim2": "rgba(207,228,245,.10)",
        "scrim3": "rgba(207,228,245,.34)", "scrim4": "rgba(203,224,242,.92)",
        "scrim5": "rgba(203,224,242,.80)", "scrim6": "rgba(203,224,242,.72)",
        "keyline": "rgba(13,33,55,.30)", "rule_soft": "rgba(13,33,55,.18)",
        "rule_mid": "rgba(13,33,55,.26)", "rule_strong": "rgba(13,33,55,.36)",
    },
}


def on_paper():
    """True when the sheet is ink on paper rather than light on a dark field.

    Asked of the palette, not of the layout. The photographic layers — the
    ghost behind the formulas, the duotone, the cut-out — each need to know
    which way round the sheet is, and for a long time they asked which layout
    was being drawn. That was right while only two layouts had light grounds
    and every palette was dark. It stopped being right the moment a palette
    could be swapped: a pale sheet then got the dark-ground duotone, a nearly
    black photograph laid over pale blue at 30%, which is what made every light
    scheme look washed and flat. The ground's own luminance is the thing that
    was always meant.
    """
    c = PALETTE["ground"].lstrip("#")
    ch = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2] > 0.35


def main(art_path, out_path, layout="stack", photo=None, cutout=None, duotone=None,
         ghost=None, silhouette=None):
    site = yaml.safe_load((DATA / "site.yml").read_text(encoding="utf-8"))
    program = yaml.safe_load((DATA / "program.yml").read_text(encoding="utf-8"))
    venue = yaml.safe_load((DATA / "venue.yml").read_text(encoding="utf-8"))

    ghost_layer = ""
    if silhouette:
        # A flat plate in the shape of the subject, under the formulas. The
        # drawing alone is thin strokes, and at any distance a field of thin
        # strokes reads as a tint rather than as a thing; the plate gives it a
        # mass and the formulas become the texture on it. Written as a mask on
        # a coloured box rather than as a coloured image, so the plate follows
        # whatever art_ink the scheme sets.
        data = base64.b64encode(Path(silhouette).read_bytes()).decode("ascii")
        url = f"data:image/png;base64,{data}"
        ghost_layer = (
            f'<div style="position:absolute;inset:0;background:{PALETTE["art_ink"]};'
            f'-webkit-mask:url({url}) 0 0/100% 100% no-repeat;'
            f'mask:url({url}) 0 0/100% 100% no-repeat;opacity:.9"></div>')
    elif ghost:
        # The same two layers the website's hero uses. The formulas alone are a
        # drawing of the photograph; the photograph faintly behind them is what
        # holds the shape together between the marks, and it is the reason the
        # hero reads as a place rather than as a texture. Held right down — it
        # is there to be felt, not seen.
        light_ground = on_paper()
        gw, gh = GHOST_SIZE.get(layout, (1700, 2398))
        # shadow first, highlight second — the photograph's dark end and its
        # light end, in that order. On paper those were the other way round,
        # which made the ghost a negative: the sky came out darker than the
        # building it stands behind, and turning the layer up made the picture
        # more wrong rather than more present. On a light sheet the dark end of
        # the photograph is the one that gets ink.
        # A wider tonal range on paper. photo_svg's default squeezes the
        # picture — right on a dark ground, where the drawing is doing the
        # describing and the photograph is only holding the shape together
        # between the marks. On a pale sheet the photograph has to carry the
        # difference between a pale building and a pale sky, and at the default
        # the two arrive within a few levels of each other.
        # The two tones the photograph is printed in, and how hard it is driven.
        # Palette values, because a sheet on paper wants them the other way up
        # from a sheet on a dark ground and the layout alone cannot tell which
        # of the two a scheme is.
        ghost_layer = (
            '<div class="ghost">'
            + photo_svg(ghost, PALETTE["ghost_shadow"], PALETTE["ghost_light"],
                        gw, gh, contrast=float(PALETTE["ghost_contrast"]))
            + "</div>")

    if cutout:
        light_ground = on_paper()
        w, h = GHOST_SIZE.get(layout, (1700, 2398))
        art = cutout_svg(
            cutout,
            PALETTE["carbon"] if light_ground else "#24374f",
            PALETTE["paper"] if light_ground else "#e4edfa",
            w, h,
        )
    elif photo:
        # Light grounds want ink on paper; dark ones want light on the field.
        light_ground = on_paper()
        w, h = GHOST_SIZE.get(layout, (1700, 2398))
        shadow, highlight = (
            duotone.split(",") if duotone else
            ((PALETTE["paper"], PALETTE["carbon"]) if light_ground
             else ("#0a111d", PALETTE["art_ink"]))
        )
        art = photo_svg(photo, shadow, highlight, w, h)
    else:
        art = Path(art_path).read_text(encoding="utf-8")
        # How the drawing is fitted to a box that is not its shape. Slicing
        # crops; it never squashes, which is what a wide banner would otherwise
        # do to a photograph taken in 4:3. The anchor says which part survives
        # the crop, and for the banner that is the top — the clock tower is the
        # thing on this campus a passer-by recognises, and a centred crop cuts
        # its head off.
        fit = ART_FIT.get(layout, "xMidYMid slice")
        if "preserveAspectRatio" in art.split(">", 1)[0]:
            art = re.sub(r'preserveAspectRatio="[^"]*"', f'preserveAspectRatio="{fit}"', art, count=1)
        else:
            art = art.replace("<svg ", f'<svg preserveAspectRatio="{fit}" ', 1)

    name = site["name"]
    mark, year = (name.rsplit(" ", 1) + [""])[:2] if " " in name else (name, "")
    facts = " ".join(
        f"<div>{esc(v)}<span> · {esc(n)}</span></div>" if n else f"<div>{esc(v)}</div>"
        for v, n in [
            (site["dates"], None),
            (venue["name"], f"{site['venue']}, {site['city']}"),
        ]
    )
    tpl = {"listing": LISTING, "festival": FESTIVAL, "academic": ACADEMIC,
           "civic": CIVIC, "bauhaus": BAUHAUS,
           "banner": BANNER, "xbanner": XBANNER,
           "social": SOCIAL, "badge": BADGE}.get(layout, TEMPLATE)
    organizers = yaml.safe_load((DATA / "organizers.yml").read_text(encoding="utf-8"))
    bill, sessions_list, organisers, days = festival_bits(program, organizers, site)
    day_people = []
    for d in sessions(program):
        day_people.append("".join(
            f'<li><b>{esc(p["name"])}</b><span>{esc(p.get("affil", ""))}'
            + (f' &middot; {esc(p["topic"])}' if p.get("topic") else "")
            + "</span></li>"
            for b in d["blocks"] for p in b["people"]))
    # One list, alphabetical, name and affiliation. It used to be grouped by
    # day and by session — Oct 7 over four sessions, Oct 8 over three, each
    # opened by its own label. That is a timetable, and a timetable is what the
    # page the code leads to is for. On the sheet it asked a reader standing in
    # front of it to hold a structure in their head before they could find the
    # one thing they came to look for, which is whether someone they know is
    # speaking. Sorted by name, that question is answered by running a finger
    # down the column.
    people = [p2 for d in sessions(program) for b in d["blocks"] for p2 in b["people"]]
    seen, ordered = set(), []
    # By family name, which on these is the last word — "Kwang-Sung Jun" files
    # under J. Sorting on the whole string instead files it under K, which is
    # alphabetical but not the alphabet anyone looks a speaker up in.
    def filed_as(x):
        parts = x["name"].split()
        return (parts[-1].lower(), " ".join(parts[:-1]).lower()) if parts else ("", "")

    for p2 in sorted(people, key=filed_as):
        if p2["name"] in seen:
            continue
        seen.add(p2["name"])
        ordered.append(p2)
    programme_block = "".join(
        f'<em>{esc(p2["name"])}</em><span>{esc(p2.get("affil", ""))}</span>'
        for p2 in ordered)
    names_flat = "".join(
        f'<li>{esc(p["name"].lower())}</li>'
        for d in sessions(program) for b in d["blocks"] for p in b["people"])
    month = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"][
        int(str(program["days"][0]["date"]).split("-")[1]) - 1]
    d0 = str(program["days"][0]["date"]).split("-")
    # Pieces only the square set needs: a day's speakers as grid cells, the
    # rooms as one mono block, and the day's own label.
    # The day slides are a timetable, not a list of names: a row per session,
    # opened by its hour and separated by a rule. The hour is what a reader
    # actually wants from a programme, and it was the one thing the earlier
    # version left out.
    day_rows, day_spans = [], []
    for day in program["days"]:
        talks = [e for e in day["events"]
                 if e.get("type") in ("block", "tutorial", "keynote") and e.get("speakers")]
        rows = []
        for e in talks:
            people = " · ".join(
                f'{esc(s["name"])} <i>{esc(s.get("affil", ""))}</i>'
                for s in e["speakers"] if s.get("name") and s["name"] != "TBD")
            rows.append(
                f'<div class="row">'
                f'<p class="hour">{esc(e.get("start", ""))}</p>'
                f'<div><p class="what">{esc(e["title"])}</p>'
                f'<p class="whom">{people}</p></div></div>')
        day_rows.append("".join(rows))
        first, last = day["events"][0], day["events"][-1]
        day_spans.append(f'{first.get("start", "")} – {last.get("end", "")}')

    day_grids, day_labels = [], []
    for d in sessions(program):
        # Grouped under the session that holds them rather than run together:
        # fourteen names in one column say who is coming, and nothing about
        # what the two days are made of.
        groups = []
        for b in d["blocks"]:
            people = "".join(
                f'<b>{esc(p["name"])}</b><span>{esc(p.get("affil", ""))}</span>'
                for p in b["people"])
            groups.append(f'<p class="sess">{esc(b["title"])}</p>'
                          f'<div class="people">{people}</div>')
        day_grids.append("".join(groups))
        raw = d["label"].split("·")[-1].strip() if "·" in d["label"] else d["label"]
        day_labels.append(esc(raw.replace("(", "· ").rstrip(")")))
    # One card per person the programme already names, then a run of blanks for
    # whoever registers on the day. Speakers before organisers, and a speaker
    # who is also an organiser is billed as a speaker — that is the reason they
    # are on the programme, and two cards for one person is a card wasted.
    # "October 7-8, 2026" is three lines in the badge's corner and the month is
    # the least of what it says; the short form is one.
    # When each day starts and when the last one finishes. Read off the
    # programme rather than written down here: a sheet that disagrees with the
    # schedule it is advertising is worse than a sheet with no hours on it.
    def _first(day):
        for e in day["events"]:
            if e.get("start"):
                return e["start"]
        return ""

    def _first_title(prog):
        """What the first hour of the first day actually is.

        "Registration & Welcome Coffee" is the programme's own wording and is
        too long for the sheet; what matters is the first word of it, which is
        the thing a reader is being told to turn up for.
        """
        for e in prog["days"][0]["events"]:
            if e.get("start"):
                return (e.get("title") or "Doors").split(" &")[0].split(" and")[0]
        return "Doors"

    def _last(day):
        for e in reversed(day["events"]):
            if e.get("end"):
                return e["end"]
        return ""

    # Without the leading zero. The programme pads its hours so a column of
    # them lines up; a sheet setting one hour beside a date has no column to
    # line it up with, and 09:00 there is a timetable's habit rather than how
    # the hour is said.
    hh = lambda s: re.sub(r"^0", "", s)
    hour1 = esc(hh(_first(program["days"][0])))
    hour2 = esc(hh(_last(program["days"][-1])))

    short_dates = re.sub(r"^(\w{3})\w*", lambda m: m.group(1), site["dates"])
    as_url = lambda svg: "data:image/svg+xml;base64," + base64.b64encode(
        svg.encode("utf-8")).decode("ascii")
    art_url = as_url(art)
    ghost_url = as_url(ghost_layer[len('<div class="ghost">'):-len("</div>")]) if ghost_layer else ""

    def badge_card(role, hot, name="", name_ko="", affil=""):
        who = (f'<p class="name">{esc(name)}</p>'
               + (f'<p class="name-ko">{esc(name_ko)}</p>' if name_ko else "")
               + (f'<p class="affil">{esc(affil)}</p>' if affil else "")) if name else (
               '<div class="write"><i></i><i></i></div>')
        return (
            '<div class="card"><div class="ghost"></div><div class="art"></div>'
            '<div class="veil"></div><div class="pad">'
            f'<div class="top"><h1 class="mark">{esc(mark)} <span>{esc(year)}</span></h1>'
            f'<div class="when">{esc(short_dates)}<br>{esc(site["venue"])}, {esc(site["city"])}</div></div>'
            f'<div class="who"><span class="role{"" if hot else " plain"}">{esc(role)}</span>{who}</div>'
            '<div class="foot">'
            f'<p class="longname">{esc(site["full_name"].upper())}</p>'
            f'<div class="qr-plate">{qr_svg(site["url"], dark=PALETTE["ground2"], light=None)}</div>'
            "</div></div></div>")

    speaker_names = set()
    badge_cards = []
    for d in sessions(program):
        for b in d["blocks"]:
            for person in b["people"]:
                if person["name"] in speaker_names:
                    continue
                speaker_names.add(person["name"])
                badge_cards.append(badge_card(
                    "Speaker", True, person["name"],
                    person.get("name_ko", ""), person.get("affil", "")))
    for mbr in organizers["members"]:
        if mbr["name"] in speaker_names:
            continue
        badge_cards.append(badge_card(
            "Organiser", True, mbr["name"], mbr.get("name_ko", ""), mbr.get("affil", "")))
    badge_cards += [badge_card("Participant", False) for _ in range(4)]
    badges = "".join(badge_cards)

    # A room is its name and, quieter, where in the building it is and how
    # many it holds. Reading `label` for the first half is what this used to do
    # and it stopped existing when the site's travel card was rewritten — which
    # took the whole export down, so the sheet quietly stayed at the version
    # before it. `.get` on both halves, so a missing field costs a word rather
    # than every poster.
    rooms = "<br>".join(
        f'<b>{esc(r.get("name", ""))}</b> {esc(r.get("detail") or r.get("label") or "")}'
        for r in venue.get("rooms", [])) or esc(venue.get("address", ""))

    doc = tpl.format(
        art=art,
        name=esc(name),
        mark=esc(mark),
        year=esc(year),
        full_name=esc(site["full_name"]),
        theme_label=f"{site['year']} Theme",
        theme=esc(site.get("theme") or ""),
        # An edition with no stated theme simply has one rail on that edge,
        # and one fewer field on the stand. A field name over an empty line
        # is worse than no field: it reads as something that failed to load.
        theme_fact=(f'<div class="fact"><p class="field">Theme {esc(str(site["year"]))}</p>'
                    f'<p class="line">{esc(site["theme"])}</p></div>'
                    if site.get("theme") else ""),
        # `Theme {year}` was here, and {year} is the second word of the name
        # rather than a year — with the workshop renamed from "KOLT 2026" to
        # "LeT Workshop" the slide printed "Theme Workshop" in the accent
        # colour over an empty heading, which is the failure the sheet's
        # theme_fact was written to avoid. Same guard, same reason: a field
        # name over an empty line reads as something that failed to load.
        theme_social=(f'<p class="kicker hot" style="margin-bottom:14px">'
                      f'{esc(str(site["year"]))} Theme</p><h2>{esc(site["theme"])}</h2>'
                      if site.get("theme") else ""),
        theme_rail=(f'<div class="rail"><b>Theme {esc(str(site["year"]))}</b>'
                    f'<span>{esc(site["theme"])}</span></div>'
                    if site.get("theme") else ""),
        eyebrow=esc(site.get("eyebrow") or ""),
        # The funder's own sentence, printed as given. English only on the
        # sheet: the Korean runs to two more lines than the foot has, and the
        # page carries both.
        grant=esc(((site.get("sponsors") or {}).get("note") or "").strip()),
        facts=facts,
        prog=programme_html(program, site.get("affiliations", {})),
        url=esc(site["url"].split("//")[-1].rstrip("/")),
        cta="Programme &amp; registration",
        qr=qr_svg(site["url"], dark=PALETTE["ground2"], light=None),
        sponsors=esc(" · ".join(h["name"] for h in site["sponsors"]["logos"])) if site.get("sponsors") else "",
        listing=listing_html(program),
        month=month,
        stamp=f"{d0[1]}.{d0[0]}",
        venue_name=esc(venue["name"]),
        venue_addr=esc(venue.get("address", "")),
        venue_short=esc(f"{site['venue']}, {site['city']}"),
        bill=bill,
        sessions_list=sessions_list,
        organisers=organisers,
        days=esc(days),
        days_range=esc('–'.join(str(d['date']).split('-')[-1] for d in program['days'])),
        bill_academic=bill.replace("<sup>", "<span>(").replace("</sup>", ")</span>")
                          .replace("<li>", "<li><b>").replace("<span>(", "</b><span>("),
        dates_long=esc(site["dates"]),
        city=esc(site["city"]),
        country=esc(site["country"]),
        cta_short="Register",
        logos=logo_row(site["sponsors"]["logos"], PALETTE["cool"])
              if site.get("sponsors") else "",
        # A six-metre cloth, not a sheet's foot: the letters in the marks are
        # set at 44mm, which puts KAIST at 80mm tall, POSTECH at 75 and the
        # NRF's stacked mark at 122. They differ because they are different
        # marks — matching their letters is what makes them look like one row,
        # and forcing all three to the same box height is what made KAIST's
        # letters half again the size of the NRF's.
        logos_colour=logo_row(site["sponsors"]["logos"],
                              PALETTE["cool"], cap=44.0, flat=False)
                     if site.get("sponsors") else "",
        acronym_name=acronym_html(site["full_name"], mark),
        long_name=esc(site["full_name"].title()),
        # The sheet says which one this is; the banners and the badges do not,
        # because a first edition is news on a poster and clutter on a name tag.
        long_name_ed=esc(f'{site["edition"]} ' + site["full_name"].title()),
        ghost=ghost_layer,
        d1=esc(str(program["days"][0]["date"]).split("-")[-1]),
        d2=esc(str(program["days"][-1]["date"]).split("-")[-1]),
        yyyy=esc(str(program["days"][0]["date"]).split("-")[0]),
        mon3=month[:3].upper(),
        hour1=hour1,
        # Named from the programme rather than typed: the first event on day one
        # is "Registration & Welcome Coffee" at 10:00, and if that moves the
        # sheet moves with it.
        opens=esc(f"{_first_title(program)} from {hour1}"),
        hour2=hour2,
        md1=".".join(str(program["days"][0]["date"]).split("-")[1:]).lstrip("0").replace(".0", "."),
        md2=".".join(str(program["days"][-1]["date"]).split("-")[1:]).lstrip("0").replace(".0", "."),
        days_long=esc(site["dates"]),
        day1=day_people[0],
        day2=day_people[1] if len(day_people) > 1 else "",
        names_flat=names_flat,
        programme=programme_block,
        dots="<i></i>" * 15,
        full_title=esc(" ".join(
            w if w.isupper() and len(w) > 1
            else w.lower() if w.lower() in ("on", "of", "and", "the", "for", "in")
            else w.capitalize()
            for w in site["full_name"].split())),
        reg_note=esc((site["hero_actions"][0].get("note") or "Opens soon")),
        badges=badges,
        art_url=art_url,
        ghost_url=ghost_url,
        blurb=esc(site.get("blurb", "")),
        rooms=rooms,
        day1_label=day_labels[0] if day_labels else "",
        day2_label=day_labels[1] if len(day_labels) > 1 else "",
        day1_grid=day_grids[0] if day_grids else "",
        day2_grid=day_grids[1] if len(day_grids) > 1 else "",
        day1_rows=day_rows[0] if day_rows else "",
        day2_rows=day_rows[1] if len(day_rows) > 1 else "",
        day1_span=esc(day_spans[0]) if day_spans else "",
        day2_span=esc(day_spans[1]) if len(day_spans) > 1 else "",
        day1_date=esc(str(program["days"][0]["date"]).replace("-", ".")[2:]),
        day2_date=esc(str(program["days"][-1]["date"]).replace("-", ".")[2:]),
        room=esc(venue["rooms"][0]["name"]) if venue.get("rooms") else esc(venue["name"]),
        **PALETTE,
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    n = sum(len(b["people"]) for d in sessions(program) for b in d["blocks"])
    print(f"  {n} speakers across {sum(len(d['blocks']) for d in sessions(program))} sessions")
    print(f"  -> {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--art", help="the formula art SVG to inline")
    ap.add_argument("--photo", help="use a two-tone photograph instead of the formulas")
    ap.add_argument("--cutout", help="use a sky-removed PNG (see tools/cut-sky.py)")
    ap.add_argument("--ghost", metavar="IMAGE",
                    help="a faint photograph behind the formulas, as the website has")
    ap.add_argument("--duotone", metavar="SHADOW,HIGHLIGHT",
                    help="two colours for the photograph, e.g. '#1b2a4a,#ff8a75'")
    ap.add_argument("--silhouette", metavar="PNG",
                    help="a cut-out PNG whose alpha is filled flat in art_ink, "
                         "laid under the formulas so the subject reads as a mass")
    ap.add_argument("--scheme", choices=sorted(SCHEMES),
                    help="a named palette; 'light' is the ink-on-paper sheet, "
                         "which also wants the artwork from formula-art.py --invert")
    ap.add_argument("--palette", metavar="JSON",
                    help="override palette entries, e.g. '{\"ground\":\"#101010\"}'. "
                         "The artwork's own ink is recoloured to match art_ink.")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--layout",
                    choices=("stack", "listing", "festival", "academic", "civic",
                             "bauhaus", "banner", "xbanner", "social", "badge"),
                    default="stack",
                    help="a poster layout, or banner (5000x900mm) / xbanner (600x1800mm)")
    args = ap.parse_args()
    if args.scheme or args.palette:
        import json
        override = dict(SCHEMES.get(args.scheme, {}))
        if args.palette:
            override.update(json.loads(args.palette))
        # The drawing carries its ink colour inside the file, so a new palette
        # has to reach in and change it too or the formulas keep the old one.
        OLD_ART_INK = PALETTE["art_ink"]
        PALETTE.update(override)
        if "art_ink" in override and args.art:
            src = Path(args.art)
            patched = src.with_name(src.stem + "__tinted.svg")
            patched.write_text(src.read_text(encoding="utf-8")
                               .replace(OLD_ART_INK, override["art_ink"]), encoding="utf-8")
            args.art = str(patched)
    main(args.art, args.out, args.layout, args.photo, args.cutout, args.duotone,
         args.ghost, args.silhouette)
