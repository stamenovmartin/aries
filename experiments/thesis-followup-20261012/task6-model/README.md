# Task 6: ARIES-FINAL-20261006 router protocol with a second local model (llama3.1:8b)

**qwen2.5:7b remains the primary result.** This run changes only the model: `intelligence.local_model` becomes
`llama3.1:8b`, digest `46e0c10c039e019119339687c3c1757cc81b9da49709a3b3924863ba87ca666e`.

The following are reused from ARIES-FINAL-20261006 and hash-checked before every cell (`protocol.json` →
`input_checks`):
- frozen source;
- prompts A0–A3, written for qwen2.5:7b and not re-tuned;
- fixture and semantic labels;
- settings;
- the randomised run order.

## Measurement conditions (author's instruction, 2026-10-12)

**The measurement is run with the live ARIES service stopped** (`systemctl --user stop aries.target`), so that Ollama
never swaps between llama3.1:8b and the live service's qwen2.5:7b. Such swaps add latency, which can turn into
technical errors that look like bad decisions.

- Before the run, `qwen2.5:7b` is unloaded from Ollama (`keep_alive: 0`).
- The service is restarted afterwards in all cases: `overnight.sh` restarts it through an EXIT trap.
- Timestamps, service states and the models loaded in Ollama at start are recorded in `run-conditions.json`.
- Ollama itself is a separate user service and keeps running.

It was first scheduled as the transient user timer `aries-task6-overnight.timer` for 2026-10-13 01:00 CEST. **On
the author's instruction it was started early instead**: the timer was cancelled and the job started at
2026-10-12 19:35 UTC as the transient unit `aries-task6-now.service` running `run-now.sh`. The procedure is the same
because `run-now.sh` calls `overnight.sh` unchanged. The only addition is that screen blanking is off for the
duration: GNOME `idle-delay` is set to 0 (it was 60 s) and an idle inhibitor is held, and both are restored on exit.
This is logged in `overnight.log`. The machine's suspend settings were checked (GNOME on AC: never; ARIES
`power.allow_suspend`: false).

## Files

| File | What it is |
|---|---|
| `run_router_second_model.py` | runner, a copy of the frozen `run_router.py` with the model changed |
| `analyze_second_model.py` | scores with the frozen `analyze_router.py` functions; writes `summary.json`, with the same metrics as `final-evaluation.json` |
| `protocol.json` | written before any inference |
| `smoke/` | a 10-utterance check of the setup; not part of any result |
| `aborted/` | a first run started 2026-10-12 17:04Z while the live service was running; stopped, **not scored, excluded** |
| `raw/`, `run-status.json`, `run.log`, `summary.json`, `run-conditions.json`, `overnight.log` | the valid run, filled in by the overnight job |
