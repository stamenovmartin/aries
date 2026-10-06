"""Could `research` be verified from what it already produces? Measured, read-only.

`service.research()` records `state: "done"` when it produced at least one card.
It never checks that the cards are ABOUT the query: the Google-News branch
(service.py 265-270) appends every parsed item with no relevance filter at all,
while the stored-news branch does filter. So "done" can mean "25 cards about
something else", and 4 briefings in the last week say so in their own words.

This measures the candidate verifier: the share of a goal's source cards whose
title or excerpt contains a query word, using the SAME word list that
`service.research()` builds. No network, no writes.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

sys.path.insert(0, "/home/stamenovmartin/aries/experiments/verification")
from probe import goals                                                  # noqa: E402

STOP = {"me", "to", "my", "of", "on", "in", "za", "mi", "se", "da", "research", "dashboard",
        "about", "news", "find", "for", "the", "and", "istrazi", "vesti", "najdi",
        "истражи", "вести", "најди"}


def words(request):
    return [w.casefold() for w in re.findall(r"\w+", request)
            if len(w) > 1 and w.casefold() not in STOP]


def main():
    buckets, rows_out = Counter(), []
    for gid, gstate, created, raw in goals():
        data = json.loads(raw or "{}")
        rs = [s for s in data.get("steps") or []
              if isinstance(s, dict) and s.get("kind") == "research"]
        if not rs:
            continue
        query = rs[0].get("args", {}).get("query") or rs[0].get("request", "")
        ws = words(query)
        cards = [c for c in (data.get("cards") or []) if c.get("url")]
        if not cards:
            buckets["no_cards"] += 1
            continue
        hits = sum(1 for c in cards
                   if ws and any(w in (c.get("title", "") + " " + c.get("text", "")).casefold()
                                 for w in ws))
        share = hits / len(cards)
        buckets["all_on_topic" if share == 1 else
                "majority_on_topic" if share >= 0.5 else
                "minority_on_topic" if share > 0 else "NONE_on_topic"] += 1
        rows_out.append({"goal": gid, "state": gstate, "query": query,
                         "cards": len(cards), "on_topic": hits, "share": round(share, 3)})
    rows_out.sort(key=lambda r: r["share"])
    print("research goals measured:", len(rows_out))
    print("relevance of source cards to the query:", dict(buckets))
    shares = sorted(r["share"] for r in rows_out)
    if shares:
        print("share on-topic: min %.3f  p25 %.3f  median %.3f  p75 %.3f  max %.3f"
              % (shares[0], shares[len(shares) // 4], shares[len(shares) // 2],
                 shares[3 * len(shares) // 4], shares[-1]))
    print("\nworst 12 (all recorded state=done):")
    for r in rows_out[:12]:
        print("  %-34s %-22s %2d/%2d on-topic  goal=%s"
              % (r["query"][:34], r["state"], r["on_topic"], r["cards"], r["goal"][:12]))


if __name__ == "__main__":
    main()
