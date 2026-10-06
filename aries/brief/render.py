"""Turning sections into something a person reads.

`briefing.length` is not a truncation setting. Each length answers a different
question, so each keeps different things:

    headlines  What needs me, and is anything on fire?
               Decisions and anything above `notice`. Nothing else.
    standard   What should I know this morning?
               Every section, a few items each, no explanatory detail.
    detailed   Everything, with the reasoning attached.

Truncating a standard brief would drop the decisions queue as readily as the
weather; choosing per length is what makes `headlines` genuinely useful rather
than merely shorter.

Rendered as plain text, with ANSI only when writing to a terminal. A brief is
also stored, read back over the API and will one day be shown in a UI, so the
renderer must not assume a terminal.
"""
from __future__ import annotations

from aries.brief.sections import Section, _rank

LENGTHS = ("headlines", "standard", "detailed")

# Items shown per section, by length. 0 means the section is title-only.
_PER_SECTION = {"headlines": 3, "standard": 5, "detailed": 20}
# Minimum severity a section must reach to appear at all, by length.
_MIN_SEVERITY = {"headlines": 1, "standard": 0, "detailed": 0}


def _paint(text: str, code: str, colour: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if colour else text


def _severity_mark(severity: str, colour: bool) -> str:
    return {"critical": _paint("!!", "31", colour), "warning": _paint(" !", "33", colour),
            "notice": _paint(" ·", "36", colour), "info": "  "}.get(severity, "  ")


def headline(sections: list[Section]) -> str:
    """One sentence: the thing to say if only one thing can be said."""
    decisions = next((s for s in sections if s.name == "decisions" and s.items), None)
    if decisions:
        return f"{len(decisions.items)} decision(s) waiting for you"
    worst = max((_rank(i.severity) for s in sections for i in s.items), default=0)
    if worst >= 3:
        crit = next(i for s in sections for i in s.items if _rank(i.severity) >= 3)
        return crit.text
    # Nothing is wrong and nothing is blocked: say that first, then what there is
    # to read. "6 news" as a headline reads like a fragment; "nothing needs you"
    # is the actual message, and the count is the detail.
    counts = [f"{len(s.items)} {s.title.lower()}" for s in sections if s.items]
    if not counts:
        return "nothing needs you"
    return "nothing needs you — " + ", ".join(counts)


def render(sections: list[Section], *, length: str = "standard", colour: bool = False,
           when: str = "") -> str:
    """The brief as text."""
    length = length if length in LENGTHS else "standard"
    per = _PER_SECTION[length]
    floor = _MIN_SEVERITY[length]
    bold = ("\033[1m", "\033[0m") if colour else ("", "")
    dim = ("\033[2m", "\033[0m") if colour else ("", "")

    out = [f"{bold[0]}Morning brief{bold[1]}" + (f"{dim[0]}  {when}{dim[1]}" if when else "")]
    out.append(f"{dim[0]}{headline(sections)}{dim[1]}")

    shown_any = False
    for s in sections:
        interesting = [i for i in s.items if _rank(i.severity) >= floor]
        if length == "headlines" and s.name != "decisions" and not interesting:
            continue
        if not interesting and not s.unavailable and length == "headlines":
            continue

        out.append("")
        # An empty section is ONE line, not a heading with "— nothing" beneath it.
        # Its summary already carries the whole message ("everything healthy",
        # "nothing needs a decision"), and repeating it makes a quiet morning read
        # as though something were wrong with the brief.
        if s.unavailable:
            # Still said out loud: an absent section and an empty one are
            # different facts, and the user must be able to tell which they have.
            out.append(f"{bold[0]}{s.title}{bold[1]}  {dim[0]}— {s.unavailable}{dim[1]}")
            continue
        if not interesting:
            out.append(f"{bold[0]}{s.title}{bold[1]}"
                       + (f"  {dim[0]}{s.summary}{dim[1]}" if s.summary else
                          f"  {dim[0]}nothing{dim[1]}"))
            continue

        out.append(f"{bold[0]}{s.title}{bold[1]}"
                   + (f"{dim[0]}  {s.summary}{dim[1]}" if s.summary and length != "headlines" else ""))

        shown_any = True
        for item in interesting[:per]:
            out.append(f"{_severity_mark(item.severity, colour)} {item.text}")
            # An urgent item carries its explanation at EVERY length. Detail is a
            # luxury for a news headline and a necessity for something the user is
            # being asked to act on — a warning they cannot interpret is a warning
            # they will learn to ignore.
            urgent = _rank(item.severity) >= 2
            if item.detail and (length == "detailed" or urgent or item.meta.get("summary_status") in {"generated", "original_macedonian"}):
                out.append(f"     {dim[0]}{item.detail}{dim[1]}")
            if item.link and (length == "detailed" or item.meta.get("summary_status") in {"generated", "original_macedonian"}):
                out.append(f"     {dim[0]}{item.link}{dim[1]}")
        if len(interesting) > per:
            out.append(f"  {dim[0]}… and {len(interesting) - per} more{dim[1]}")

    if not shown_any:
        out.append("")
        out.append(f"  {dim[0]}Nothing to report.{dim[1]}")
    return "\n".join(out)
