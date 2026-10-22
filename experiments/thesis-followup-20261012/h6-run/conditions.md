# H6 run conditions: notes written after the run

- **`aries_core_during: active` in `run-conditions.json` is a race, not the state during the run.** The
  value was read in the same second as `systemctl --user stop aries.target` returned. The user journal
  shows that `aries-core.service` was stopped at 17:40:58Z and started again at 18:04:29Z. The 1800
  decisions in `raw/` started between 17:40:58.33Z and 18:04:24.93Z, so all of them ran while it was
  stopped.
- **Concurrent work:** while this run was going, unit tests ran in the separate worktree `~/aries-prep`
  (branch `h4b-h5-prep`), at nice 19, one process at a time. They used no model, no Ollama call and no
  service, and nothing was restarted. They compete only for CPU. That can change latency, not the
  decisions: `errors` is 0 in both arms.
- **Model and runtime:** the Ollama version (0.34.0) and the qwen2.5:7b digest (`845dbda0…`) are the same
  before and after the run, and equal the frozen protocol's.
