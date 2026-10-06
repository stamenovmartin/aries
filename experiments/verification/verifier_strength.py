"""Of the steps counted `verified`, how many met a check that COULD have failed.

A verifier whose every return path is `met: True` proves the subject is still
observable. It does not test the executor's claim, and it cannot produce a
contradiction — so counting its verdict as independent confirmation inflates
coverage with a check that has no failure mode. The registry uses that shape
deliberately in places (`verify_probe`, `verify_observe`, `verify_tabs`), so the
question is quantitative: what share of the `verified` bucket is which kind.

Classification is from the verifier's own SOURCE: a verifier is `unconditional`
when every `met` it returns is the literal True. No heuristics beyond that, and
the per-verifier verdict is printed so it can be checked by eye.
"""
from __future__ import annotations

import inspect
import re
import sys
from collections import Counter

sys.path[:0] = ["/home/stamenovmartin/aries/vendor/agentic-core",
                "/home/stamenovmartin/aries/vendor", "/home/stamenovmartin/aries",
                "/home/stamenovmartin/aries/experiments/verification"]
from aries.learning.statistics import wilson                              # noqa: E402
from aries.workspace.registry import registry                             # noqa: E402
from probe import DB, bucket, goals, steps                                # noqa: E402

# Both spellings are in use: {'met': x} and dict(met=x).
MET = re.compile(r"""(?:['"]met['"]\s*:|\bmet=)\s*(.+?)\s*[,})]""")


def strength(cap):
    try:
        src = inspect.getsource(cap.verifier)
    except (OSError, TypeError):
        return "unknown"
    values = {m.group(1).strip() for m in MET.finditer(src)}
    if not values:
        return "no_met_returned"
    return "unconditional" if values == {"True"} else "comparing"


def main():
    kinds = {n: strength(c) for n, c in registry._items.items()}
    per = Counter()
    for _gid, _created, s in steps(goals()):
        if bucket(s) != "verified":
            continue
        per[(s.get("capability"), kinds.get(s.get("capability"), "not_in_registry"))] += 1
    print("database:", DB)
    print("\nregistry verifiers by strength:", dict(Counter(kinds.values())))
    print("  unconditional (cannot return met=False):")
    for n, k in sorted(kinds.items()):
        if k == "unconditional":
            print("   ", n, "->", getattr(registry._items[n].verifier, "__name__", "<closure>"))
    print("\nthe `verified` bucket, by whether the check could have failed:")
    tot = Counter()
    for (cap, k), n in sorted(per.items(), key=lambda kv: -kv[1]):
        print(f"   {cap:22s} {k:14s} {n}")
        tot[k] += n
    print("\n  totals:", dict(tot))
    n = sum(tot.values())
    if n:
        i = wilson(tot["comparing"], n)
        print("  share of `verified` from a check with a failure mode: "
              f"{tot['comparing']}/{n} = {tot['comparing'] / n:.3f} "
              f"[{i.lower:.3f}-{i.upper:.3f}]")


if __name__ == "__main__":
    main()
