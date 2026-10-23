# eval/

Reusable evaluation harnesses: code that can run again on a new version of ARIES. Dated results of a
particular measurement are in [`../experiments/`](../experiments/README.md).

| path | what |
|---|---|
| [`agent_suite/`](agent_suite/) | 90 English goals with external-state predicates and forced silent failures; each run is a dated folder |
| [`research_feedback/`](research_feedback/) | does independent verification feedback change the next step (fixture in `experiments/verification-feedback/`) |
| [`smoke/`](smoke/) | one English command through every layer except the microphone |
| [`locking/`](locking/) | SQLite `database is locked` smoke tests (diagnosis in `experiments/locking/`) |
| [`surfaces/`](surfaces/) | English voice intelligibility (TTS word error rate) |
| [`reporting/`](reporting/) | denominator corrections for the reports |
| [`triage_queue/`](triage_queue/) | failures queued for triage |

Entry points: `make eval-thesis` and `make eval-iis` (see `scripts/eval.sh`).
