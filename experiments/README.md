# experiments/

Dated measurements. Each folder is one measurement or one series: its registration (if any), the scripts
that ran it, the scripts that analysed it, and the files the numbers are read from. A run writes new files
and never overwrites old ones. Reusable evaluation harnesses are in [`../eval/`](../eval/), not here.

## Layout

| path | what |
|---|---|
| [`thesis/`](thesis/INDEX.md) | **thesis** (the agent): the index, and the precursor series moved into it |
| [`iis/`](iis/INDEX.md) | **IIS project** (the information layer): the index, public-data evaluations and the earlier series |
| [`analysis/`](analysis/README.md) | every comparison as a figure, regenerated from the result files |
| [`archive/`](archive/INDEX.md) | superseded or one-off series, kept as evidence |
| `thesis-final-20261006/`, `thesis-followup-20261012/`, `thesis-r1-real-data/`, `thesis-r1b/`, `thesis-m2-models/`, `thesis-improvements-20261022/` | the thesis measurements. **Frozen in place**: other frozen files, the thesis tables and the thesis build name them by exact path and hash |
| `router-ood/`, `router-en/`, `product/` | fixtures and acceptance runs that the frozen measurements read by exact path or hash |
| `verification-feedback/` | the fixture that `eval/research_feedback/` reads; its path is recorded with a hash in every run |
| `exploratory/` | analyses designed after a confirmatory result |
| `assistant-benchmark/`, `demo/`, `speech/`, `locking/` | product benchmarks and diagnoses that scripts still write to |
| `endurance/`, `voice/` | written or run by the installed system (`scripts/aries-endurance`, `scripts/aries-voice`); they stay where the systemd units find them |
| `learning/` | one lesson per finished batch (`problem`, `change`, `validation`, `limitations`), and the learning-layer JSONs |

## Rules

- A frozen folder is never edited; a correction is a new file or a dated amendment.
- A registered measurement has its registration in `docs/preregistration/`, committed before the run.
- Raw outputs that contain dataset texts or personal data are not committed (`.gitignore`); manifests of
  item ids, labels, summaries and per-item correctness are.
- Every number in the README, the thesis and the reviewer guide is read from a file here.
