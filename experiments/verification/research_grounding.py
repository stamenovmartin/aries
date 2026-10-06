"""The candidate `met` clause for research, measured both ways.

The briefing is what the person reads. The honest, threshold-free question is
whether it is grounded in the sources it lists: does it share a substantive word
with any of their titles. Measured with a Latin-only word class and with a
script-agnostic one, because the spoken surface is bilingual and a check that only
works in English would flag every Macedonian briefing.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

sys.path.insert(0, "/home/stamenovmartin/aries/experiments/verification")
from probe import DB, goals                                                # noqa: E402

LATIN = re.compile(r"[A-Za-z]{6,}")
ANY = re.compile(r"[^\W\d_]{6,}", re.UNICODE)
CYR = re.compile(r"[Ѐ-ӿ]")


def main():
    res = Counter()
    for _gid, _st, _created, raw in goals():
        d = json.loads(raw or "{}")
        if not any(isinstance(s, dict) and s.get("kind") == "research"
                   for s in d.get("steps") or []):
            continue
        cards = d.get("cards") or []
        b = next((c for c in cards if c.get("source_links")), None)
        if not b:
            res["no_briefing"] += 1
            continue
        text = (b.get("text") or "") + " " + (b.get("title") or "")
        titles = " ".join(l.get("title", "") for l in b["source_links"])
        for label, rx in (("latin", LATIN), ("any_script", ANY)):
            words = set(rx.findall(titles))
            res[f"{label}:{'grounded' if any(w in text for w in words) else 'UNGROUNDED'}"] += 1
        res["cyrillic_briefing" if CYR.search(text) else "latin_briefing"] += 1
    print("database:", DB)
    for k, v in sorted(res.items()):
        print(f"  {k:26s} {v}")


if __name__ == "__main__":
    main()
