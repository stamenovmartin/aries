"""Coverage split by WHICH ENGINE wrote the step. The one table that settles it.

If the M14 verifier were broken, its steps would land in `accepted` — executor
returned, nothing checked it. If instead the traffic simply bypasses it, its
steps would all carry a verdict and the `accepted` pile would be entirely
somebody else's. Same rows as `verification_honesty`, one extra GROUP BY.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict

sys.path[:0] = ["/home/stamenovmartin/aries/vendor/agentic-core",
                "/home/stamenovmartin/aries/vendor", "/home/stamenovmartin/aries",
                "/home/stamenovmartin/aries/experiments/verification"]
from aries.learning.statistics import wilson                              # noqa: E402
from probe import DB, bucket, engine, goals, recoverable, steps           # noqa: E402

LOOKS = ("verified", "accepted", "unconfirmed")


def show(k, n):
    if not n:
        return "n=0"
    i = wilson(k, n)
    return f"{k}/{n} = {k / n:.3f} [{i.lower:.3f}-{i.upper:.3f}]"


def main():
    per = defaultdict(Counter)
    rec = defaultdict(Counter)
    for _gid, _created, s in steps(goals()):
        e = engine(s)
        b = bucket(s)
        per[e][b] += 1
        if b in ("accepted", "unconfirmed"):
            rec[e][recoverable(s) or "NO_VERDICT_RECORDED"] += 1
    print("database:", DB)
    total = Counter()
    for e, b in sorted(per.items(), key=lambda kv: -sum(kv[1].values())):
        total.update(b)
        looks = sum(b[k] for k in LOOKS)
        print(f"\n{e}  steps={sum(b.values())}")
        print("   buckets:", dict(b))
        print("   coverage (verified / looks-successful):", show(b["verified"], looks))
        if rec[e]:
            print("   verdict already in the record but not in verification_status:",
                  dict(rec[e]))
    looks = sum(total[k] for k in LOOKS)
    print("\nALL  steps=%d  looks_successful=%d" % (sum(total.values()), looks))
    print("   coverage as the dashboard reports it:", show(total["verified"], looks))
    already = sum(v[k] for v in rec.values()
                  for k in ("result.operator.verified_success", "result.verification"))
    print("   coverage if the verdicts already in the record were surfaced:",
          show(total["verified"] + already, looks))


if __name__ == "__main__":
    main()
