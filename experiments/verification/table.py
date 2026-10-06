"""The per-capability table, as markdown. Static surface x measured traffic.

Columns, and what each one is read from:
  verifier exists   does a verifier exist for this effect ANYWHERE — the M14
                    registry twin counts, because it is the same effect and the
                    same underlying module
  invoked           does the spoken path actually call one (source of
                    `capabilities.execute()`)
  records it        does the step as SAVED carry a verdict (measured)
  bucket            what `aries.analytics.core.STEP_BUCKET` made of it (measured)
"""
from __future__ import annotations

import json
import sys

S = sys.argv[1] if len(sys.argv) > 1 else "surface.json"
P = sys.argv[2] if len(sys.argv) > 2 else "probe.json"
surface, probe = json.load(open(S)), json.load(open(P))
rec = probe.get("recoverable_on_unverified", {})

print("| spoken capability | verifier exists | invoked by the spoken path | verdict recorded on the step | steps | buckets measured |")
print("|---|---|---|---|---|---|")
for r in sorted(surface["rows"], key=lambda r: (-r["steps"], r["capability"])):
    cap = r["capability"]
    twin = r["m14_twin"]
    d = r["delegate"]
    if r["returns_verification"]:
        exists, invoked = "yes · in execute()", "yes"
    elif "operator.run" in d:
        exists, invoked = "yes · operator.run", "yes, verdict discarded"
    elif "workspace.agent" in d:
        exists, invoked = "yes · M14 agent", "yes, outer step left blank"
    elif twin:
        exists, invoked = "yes · " + twin, "no"
    else:
        exists, invoked = "NO", "no"
    if cap == "research":
        exists, invoked = "NO — anywhere", "no · never reaches execute()"
    where = rec.get(cap, {})
    if r["recorded_verification"]:
        got = "`result.verification` (%d) — not read by any metric" % r["recorded_verification"]
    elif where.get("result.operator.verified_success"):
        got = ("`result.operator.verified_success` (%d) — not read by any metric"
               % where["result.operator.verified_success"])
    elif r["recorded_verification_status"]:
        got = "`verification_status` (%d)" % r["recorded_verification_status"]
    else:
        got = "none"
    b = ", ".join(f"{k} {v}" for k, v in sorted(r["buckets"].items(), key=lambda kv: -kv[1]))
    print(f"| `{cap}` | {exists} | {invoked} | {got} | {r['steps'] or ''} | {b} |")
