# experiments/

Raw experimental artifacts. See [`docs/EXPERIMENTS.md`](../docs/EXPERIMENTS.md)
for the rule and the index.

Each directory holds, once its milestone runs:

| file | |
|---|---|
| `config.yaml` | variants, task set, repetitions, environment |
| `tasks.jsonl` | the dataset — versioned with the code |
| `results.jsonl` | one line per run per task, carrying the commit |
| `summary.json` | derived, regenerable from results |
| `analysis.md` | the argument, including results that did not support the hypothesis |

Empty directories were deliberate: they named the evaluations that are owed. On 2026-10-22 the four
`.gitkeep`-only folders (`orchestrator`, `dynamic_agents`, `model_router`, `evolution`) were removed,
and each owed evaluation is now a line in [`archive/INDEX.md`](archive/INDEX.md). The indexes
[`thesis/INDEX.md`](thesis/INDEX.md), [`iis/INDEX.md`](iis/INDEX.md) and
[`archive/INDEX.md`](archive/INDEX.md) map every folder by its current path.
