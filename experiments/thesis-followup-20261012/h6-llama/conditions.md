# H6 llama3.1:8b run conditions: notes written after the run

- **`aries_core_during: active` in `run-conditions.json` is the same race as in `../h6-run/conditions.md`.** The
  value was read in the same second as `systemctl --user stop aries.target` returned. The user journal shows
  `aries-core.service` stopped at 23:11:05.85Z and started again at 23:35:41.10Z (2026-10-18). The 1800
  decisions in `raw/` started between 23:11:05.92Z and 23:35:35.36Z, so all of them ran while it was stopped.
- **Other services:** the `aries-endurance.service` timer ran every 5 minutes, as during the qwen2.5:7b run. Each
  run lasted about 0.1 s and only reported an existing evidence folder. Nothing else was started or restarted.
- **Concurrent work:** while this run was going, code was written in the main checkout and unit tests ran at
  nice 19, one process at a time (`tests/test_h4b_runner.py` and `thesis-tables/check.py`). They used no model,
  no Ollama call and no service. They compete only for CPU, which can change latency but not the decisions:
  `errors` is 0 in both arms.
- **Model and runtime:** Ollama 0.34.0 and the llama3.1:8b digest `46e0c10c…` are the same before and after the
  run. The analysis checks all passed (`analysis.log`).
- **Run script log name:** `run-h6-llama.sh` is a copy of `run-h6.sh`, and its log is still called
  `run-h6.log`. The background wrapper that started it then tried to read a `run-h6-llama.log`, which does
  not exist, and exited with 1. The run and the analysis both exited with 0 (`run-h6.log`).
