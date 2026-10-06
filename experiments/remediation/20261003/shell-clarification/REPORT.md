# Clarification reaches the voice API envelope

Before: 2026-10-03T13:07:32.050337+00:00; after: 2026-10-03T13:10:01.146942+00:00.

| Measurement | Before (n) | After (n) |
|---|---:|---:|
| API message is the actual clarification question, with zero steps | 0/2 | 2/2 |

The spoken-reply formatter also returns the question in scoped tests. No acoustic speech playback or ASR quality is measured here.
An earlier batch received429; no result is credited for that interrupted batch. The600-second pause expired naturally before both paired requests; no reset or source switch.
