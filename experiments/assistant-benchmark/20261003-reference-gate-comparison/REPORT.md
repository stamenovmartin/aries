# Frozen live goal benchmark

Before: 2026-10-03T13:10:01.740059+00:00; after: 2026-10-03T13:54:50.870803+00:00.
Complete, stable, same-day pair: True.

Comparable environment: True.

| Group | Before (n) | After (n) |
|---|---:|---:|
| all | 54/60 | 54/60 |
| category:ambiguous | 8/8 | 8/8 |
| category:desktop | 0/4 | 0/4 |
| category:directory | 4/4 | 4/4 |
| category:multi_step | 16/16 | 16/16 |
| category:package | 8/8 | 8/8 |
| category:refusal | 6/8 | 6/8 |
| category:single_read | 12/12 | 12/12 |
| language:en | 27/30 | 27/30 |
| language:mk | 27/30 | 27/30 |

60 scoped trials, not overall assistant maturity.
Generic HTTP refusal and unstructured clarification are not credited.
File and package cases do not test adaptive planning or ASR.
Runtime stability covers the recorded core invocation and source hashes only; other clients are not isolated. No causal latency claim.
No 48-hour stability or acoustic playback acceptance claim.
Reference submit path measured separately1/8 to8/8. Router candidate was incidentally deployed by the reviewing agent and remains rejected/pending coordinated rollback. All60 retain locked desktop and two missing-file refusal failures.
