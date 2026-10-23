# P1: latency, resource use and reliability (registered, descriptive)

**Registered:** 2026-10-23, before any P1 run. The runner, the sampler, the window script and the analysis
(`experiments/thesis-p1-performance/`) are committed with this file. Any later change goes into a dated
Amendment section in a new commit, before the computation it changes.

**Why:** the thesis title promises an evaluation of the system, and the reviewer named latency, resource use
and reliability explicitly. The earlier measurements report decision quality and verification; time per request
appears only in passing and resources were never measured. P1 measures them systematically.

**Label:** descriptive. P1 has no hypothesis test and no Holm family; nothing here changes R1, R1b, M2 or the
H-family. Rates carry Clopper-Pearson 95% intervals; latencies are quantiles over all requests.

## What is measured

**P1-A: decision latency on the full samples (already measured, not yet analysed for time).** The R1b and M2
treatment runs recorded `router_seconds` (router and capability gate) and `planner_seconds` for every request:
1,100 requests (NL2Bash r1b 500 + CLINC150 r1b 600) for each of qwen2.5:1.5b, qwen2.5:7b, llama3.1:8b and
qwen2.5:14b. Reported per model: mean, median, p90, p95 and maximum of router+gate, planner (when called) and
their sum; the share of requests with a router error or an invalid planner output.

**P1-B: cold load and resources per model (new run, live ARIES stopped).** For each model, in the order 1.5b,
7b, 8b, 14b: all models unloaded; 20 s idle; the model loaded with an empty request (cold load time, and the
VRAM Ollama reports); 20 s idle with the model loaded; then R1b's treatment pipeline (configuration C1, nothing
executed) on the first 100 items in manifest order of each R1b sample (200 requests). A sampler records every
0.5 s: GPU memory, utilisation, power and temperature (`nvidia-smi`); system CPU and RAM in use; RSS and CPU for
the Ollama processes and the ARIES processes (`/proc`). Reported per model and phase: mean and maximum of each,
GPU energy (trapezoid over power) in total and per request, and the workload latency as in P1-A.

**P1-C: the installed system end to end, three times (new run, live ARIES running).** 60 s idle baseline of the
installed system as it runs (core, local-model gateway, voice daemon). Then the 90-goal agent suite
(`eval/agent_suite/`, the fixture of the B-series, `--flags on`, defaults otherwise) three times in a row
against the running service, with the sampler on. Reported per run: pass, false success and skip over the scored
goals; latency per goal (quantiles, overall and by category); resources during the run. Reliability across the
three runs: goals with the same outcome in all three, goals that pass in all three, and the goals that pass in
some but not all. B8 (2026-10-04, 88/90) is shown beside them as a reference, not as a comparison.

## Procedure

`experiments/thesis-p1-performance/run-p1.sh`: sampler on; P1-C (idle, suite ×3); `aries.target` stopped;
P1-B for the four models; `aries.target` restarted, screen blanking restored, sampler stopped. Then
`analyze_p1.py` writes `summary.json`.

## Limitations stated in advance

- One machine (RTX 3060 12 GB, 12 CPU threads); absolute numbers are specific to it.
- The agent suite is the author's fixture (B-series); the installed service runs the code in `~/aries`, whose
  source hashes the suite records. Its API goals run with the service's own flag state.
- P1-B runs the decision pipeline only (nothing executed). Its 200 requests are a subset of the 1,100 in P1-A
  and are used for resources; P1-A carries the latency claim.
- Ollama keeps a model loaded for its `keep_alive`; the first request after a cold start is not in P1-A's
  quantiles as a separate category, so P1-B reports cold load on its own.
- Power is the GPU board's reported draw, not wall power; CPU and RAM are not converted to energy.
