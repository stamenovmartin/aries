# Unresolved references ask before planning

Live before: 2026-10-03T13:41:20.336997+00:00; after: 2026-10-03T13:49:40.551657+00:00.

| Measurement | Before (n) | After (n) |
|---|---:|---:|
| Live API response: structured question and zero queued steps | 1/8 | 8/8 |
| Isolated submit: ambiguous requests clarified | 4/55 | 14/55 |
| Isolated submit: actionable requests wrongly questioned | 0/100 | 0/100 |

Live trials use eight read-only utterances; only owned queued probes cancelled. This measures immediate clarification, not completed actions or acoustic speech.
Supplemental225 calls execute the actual submit function against an isolated ledger without a worker; memory observation disabled. Baseline submit source reconstructed by removing the exact insertion and checked against the saved live-baseline hash. No model or action acceptance claim.
41/55 wider ambiguous cases remain uncovered. No generic OOD, unsafe-request or short-answer conversation resolution claim. Declining a recognizer match alone is not clarification.
