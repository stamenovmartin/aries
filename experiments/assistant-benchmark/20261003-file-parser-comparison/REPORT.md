# Frozen live goal benchmark

Before: 2026-10-03T11:26:25.915304+00:00; after: 2026-10-03T11:30:52.457712+00:00.
Complete, stable, same-day pair: True.

| Group | Before (n) | After (n) |
|---|---:|---:|
| all | 29/60 | 44/60 |
| category:ambiguous | 0/8 | 0/8 |
| category:desktop | 3/4 | 4/4 |
| category:directory | 4/4 | 4/4 |
| category:multi_step | 8/16 | 16/16 |
| category:package | 8/8 | 8/8 |
| category:refusal | 0/8 | 0/8 |
| category:single_read | 6/12 | 12/12 |
| language:en | 21/30 | 22/30 |
| language:mk | 8/30 | 22/30 |

60 scoped trials, not overall assistant maturity.
Generic HTTP refusal and unstructured clarification are not credited.
File and package cases do not test adaptive planning or ASR.
Runtime stability covers the recorded core invocation and source hashes only; other clients are not isolated. No causal latency claim.
No 48-hour stability or acoustic playback acceptance claim.
