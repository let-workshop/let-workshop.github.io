#!/usr/bin/env python3
"""Who is coming, and what each of them is called on a badge.

    python3 tools/roster.py                    # what would be printed
    python3 tools/roster.py --sort name        # one run, not four bundles

Reads data/roster.tsv — the RSVP form's own export, downloaded as TSV and
dropped in unedited. The columns are found by what the questions start with
rather than by position, so a question added to the middle of the form does not
move the answers this needs:

    Timestamp / Email Address / 이름 / 연사·현장요원 / 소속 / 현재 신분 / 불참여부

Three things the export does that a naive read gets wrong.

People re-submit. Four did, and a second submission is a correction, so the
latest one per email wins — which is the opposite of what "skip the duplicate"
does. 윤상연's second answer is the one with the right graduate school on it.

Names arrive with invisible characters in them. One came through with a soft
hyphen in front of it, U+00AD, which is a character a badge would print as
nothing and a sort would file under nothing. Names also arrive with the
department in brackets after them; the badge wants the name.

The form has an empty row in it, and will have more.

Then one question per person: which of the four badges, and what goes on it.
`role_flag` is matched on the form's own wording, so anything containing
초청 연사 is a speaker and anything containing 현장 요원 is staff. Everything
else is an attendee, and being named in data/organizers.yml overrides all of
that except speaking.

Speaking overrides organising because three of the six organisers are also
giving talks, and the badge should say the thing the room needs from them.
That is the rule the printed sheet already used when it built itself out of
program.yml; this keeps it while taking the names from the roster instead.

The name is the harder half. The form collects Korean names; program.yml and
organizers.yml carry the romanised ones beside a `name_ko`, so a speaker or an
organiser can be matched on that and get both lines. Nobody else can — so an
attendee's badge is their Korean name and nothing under it, which is what they
wrote and what the person reading it across a handshake will be looking for.
Affiliation always comes from the roster rather than from the site: "KAIST AI"
is what someone put down about themselves, and "KAIST" is what a poster needs.
"""

import argparse
import csv
import re
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# The four badges, in the order they are printed and bundled. Speaker first
# because that bundle is handed over one at a time and wants to be on top.
ROLES = ("Speaker", "Organiser", "Staff", "Attendee")
HOT = {"Speaker", "Organiser", "Staff"}   # drawn in the accent; Attendee is not


# Characters a form picks up from a paste and a badge would print as nothing:
# soft hyphen, zero-width space, zero-width non-joiner and joiner, and the
# word joiner. One name in the export arrives with a soft hyphen in front of it.
INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u2060\ufeff"))


def _tidy(s):
    """One space between words, none at the ends, and nothing invisible."""
    s = unicodedata.normalize("NFC", s or "").translate(INVISIBLE)
    return re.sub(r"\s+", " ", s).strip()


def _bare_name(s):
    """The name, without the bracket someone put their department in."""
    return _tidy(re.sub(r"\s*[(（].*?[)）]\s*$", "", _tidy(s)))


# What each column is, by what its question starts with. The form's questions
# are long and get reworded; their openings do not.
COLUMNS = {
    "when": "Timestamp",
    "email": "Email Address",
    "name_ko": "이름",
    "role_flag": "연사",
    "affil": "소속",
    "position": "현재 신분",
    "absent": "불참",
}


def _columns(fieldnames):
    """Map this export's headers onto the seven fields that matter.

    Raises rather than guessing: a column that cannot be found is a form that
    was reworded, and printing a hundred badges with no affiliations on them
    because a header moved is worse than stopping.
    """
    found = {}
    for key, prefix in COLUMNS.items():
        for h in fieldnames or []:
            if (h or "").strip().startswith(prefix):
                found[key] = h
                break
        else:
            raise SystemExit(f"  no column in the roster starting with {prefix!r}\n"
                             f"  the file has: {', '.join((fieldnames or [])[:8])}…")
    return found


def known_people():
    """Korean name -> romanised name, for everyone the site already names.

    Both files, because an organiser who does not speak is only in one of them.
    Keyed on `name_ko`: it is the only field the roster and the site share.
    """
    out = {}
    program = yaml.safe_load((DATA / "program.yml").read_text(encoding="utf-8"))
    organizers = yaml.safe_load((DATA / "organizers.yml").read_text(encoding="utf-8"))
    rows = [s for d in program["days"] for e in d["events"]
            for s in (e.get("speakers") or [])]
    rows += organizers["members"]
    for r in rows:
        ko = _tidy(r.get("name_ko"))
        if ko:
            out.setdefault(ko, _tidy(r["name"]))
    return out


def organiser_names():
    o = yaml.safe_load((DATA / "organizers.yml").read_text(encoding="utf-8"))
    return {_tidy(m.get("name_ko")) for m in o["members"] if m.get("name_ko")}


def read(path=None):
    """The roster as a list of dicts, one per badge, absentees dropped.

    Each carries: role, name (what the badge says), name_ko (the line under
    it, empty when the two would be the same), affil, and the email it came
    from, which is the only thing here that is certainly unique.
    """
    path = Path(path or DATA / "roster.tsv")
    romanised, organisers = known_people(), organiser_names()
    latest = {}

    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        col = _columns(reader.fieldnames)
        for n, row in enumerate(reader):
            email = _tidy(row.get(col["email"])).lower()
            if not email:                  # the export has blank rows in it
                continue
            # A later submission is a correction, so it replaces the earlier
            # one. Ordered on the row rather than the timestamp: the timestamps
            # are American dates as text and sort wrongly, while the form only
            # ever appends.
            latest[email] = (n, row)

    people = []
    for email, (_, row) in latest.items():
        if _tidy(row.get(col["absent"])):
            continue
        ko = _bare_name(row.get(col["name_ko"]))
        flag = row.get(col["role_flag"]) or ""
        # Organiser first. Three of the six on organizers.yml are also giving
        # talks and the form has them down as invited speakers, so reading the
        # form first made them speakers and left the committee looking like
        # three people. Which of the two a badge should say is not a question
        # about the programme: an organiser is who someone with a question goes
        # to, and that is what the badge is for.
        if ko in organisers:
            role = "Organiser"
        elif "초청 연사" in flag:
            role = "Speaker"
        elif "현장 요원" in flag:
            role = "Staff"
        else:
            role = "Attendee"

        people.append({
            "role": role,
            # The Korean name leads, always, and the romanised one goes under
            # it where there is one. It was the other way round, and that gave
            # the two dozen people the site already names a different-shaped
            # badge from everyone else — and put the smaller line on the name
            # the registration desk actually searches, since the list on the
            # desk is Korean. Someone who wrote a Latin name in the form has
            # that as their name and no subtitle.
            "name": ko,
            "name_sub": romanised.get(ko, ""),
            "affil": _tidy(row.get(col["affil"])),
            "position": _tidy(row.get(col["position"])),
            "email": email,
        })
    return people



def write(path, people):
    """A roster TSV holding just these people, for re-reading by the badge tool.

    Round-tripped through the form's own wording rather than a private format,
    so a chunk is read back by exactly the code that read the export.
    """
    flags = {"Speaker": "예 (초청 연사)", "Staff": "예 (현장 요원)"}
    head = ["Timestamp", "Email Address", "이름", "연사/현장요원 여부",
            "소속", "현재 신분", "불참여부"]
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(head)
        for p2 in people:
            w.writerow(["", p2["email"], p2["name"],
                        flags.get(p2["role"], "아니오"),
                        p2["affil"], p2["position"], ""])


def ordered(people, sort="role"):
    """Print order: four bundles, one alphabetical run, or the file's own.

    Within a bundle, by the name on the card, which is the Korean one — the
    list on the desk is Korean and that is what gets searched.

    `file` leaves them alone, which is what a caller that has already decided
    the order wants. tools/badges.py cuts the sorted roster into chunks and
    hands each to poster.py; without this, poster.py would sort each chunk
    again and the order chosen for the whole would survive only inside the
    twenty cards that happened to be printed together.
    """
    if sort == "file":
        return list(people)
    key = lambda p: (p["name"], p["affil"])
    if sort == "name":
        return sorted(people, key=key)
    return sorted(people, key=lambda p: (ROLES.index(p["role"]), key(p)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roster", help="a roster TSV (default: data/roster.tsv)")
    ap.add_argument("--sort", choices=("role", "name", "file"), default="role")
    args = ap.parse_args()

    people = ordered(read(args.roster), args.sort)
    width = max(len(p["name"]) for p in people)
    for i, p in enumerate(people, 1):
        sub = f'  {p["name_sub"]}' if p["name_sub"] else ""
        print(f'  {i:3d}  {p["role"]:9} {p["name"]:{width}}{sub:18}  {p["affil"]}')
    print()
    for r in ROLES:
        n = sum(1 for p in people if p["role"] == r)
        print(f"  {r:9} {n:3d}")
    print(f"  {'total':9} {len(people):3d}")


if __name__ == "__main__":
    main()
