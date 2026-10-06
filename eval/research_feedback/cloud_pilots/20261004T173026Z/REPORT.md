# Pinned cloud development pilot

**Excluded development data, not the 600-run study or an improvement claim.**

Provider/model: `codex-cli` / `gpt-6-astra`. Completed 6/6 assignments.
Window: 2026-10-04T17:30:26.263822+00:00 — 2026-10-04T17:32:39.099314+00:00.
Sources stable within and across episodes: True. Common completion guard and terminal JSON examples enabled; no model sampling seed supplied.

| Case | Feedback | Unsupported finish proposals | Goal oracle | Model chose stop | Calls | Seconds | Confirmatory admission |
|---|---|---:|---|---|---:|---:|---|
| owned files / none | tool_only | 0 | True | False | 3 | 19.617 | True |
| owned files / none | structured | 0 | True | False | 3 | 18.72 | True |
| owned files / stale_read | tool_only | 1 | False | False | 4 | 28.264 | True |
| owned files / stale_read | structured | 0 | False | True | 4 | 27.48 | True |
| vf-09 | tool_only | 1 | False | True | 3 | 23.582 | False |
| vf-09 | structured | 0 | False | True | 2 | 14.117 | False |

Each row has n=1. The two fault families are separate diagnostic contrasts; do not pool them as independent repetitions or report a confidence interval as if this were the planned study.

Normal file controls complete under both conditions. For each fault pair, tool-only produced one unsupported finish proposal and structured feedback produced zero. Neither fault pair completed the goal. No user-visible false success was exposed in these six episodes. These observations do not establish general improvement; order is fixed and sample size is minimal.

`reroute_verified`: **unmeasurable**, not zero. No permitted independent alternative route was validated.
The controlled screen rows remain excluded from confirmatory comparison. Read `CLOUD_ADMISSION.json` for unresolved whole-study checks.

The privacy guard covers this isolated study adapter only; production private/local routing has not been demonstrated by these tests.

## Artifacts

- `eval/research_feedback/runs/20261004T173026Z-ac6eb7/result.json` — SHA256 `923bd48bc28b0571d8e2107f0b8ae2af79f40b0f14cf15d5cef2975839bbd598`
- `eval/research_feedback/runs/20261004T173046Z-c34822/result.json` — SHA256 `5ecf20286e55897ee043716befe896a6b9102c7ada20d5788c2ae11a242d2af4`
- `eval/research_feedback/runs/20261004T173105Z-5cdc8c/result.json` — SHA256 `4c2825de337b2819cf1d5d06997a1f75c4c66d1fbecf1979ecf252c6f907ac63`
- `eval/research_feedback/runs/20261004T173133Z-3d1d54/result.json` — SHA256 `d711321e6636bdd256cc9ab1f149125fee75872bf862db7577e9b17e40f96afa`
- `eval/research_feedback/runs/20261004T173201Z-8b386c/result.json` — SHA256 `3d96280d822c8b18aa77ce86d48935eecd1f88eec3f685efeaa48eb5054264d5`
- `eval/research_feedback/runs/20261004T173224Z-833ab6/result.json` — SHA256 `1f30e06d676e61ee3482226de1f806435ed9984c6e9ddaef28d5ea5acf8ba5ee`
