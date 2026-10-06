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

Empty directories are deliberate: they name the evaluations that are owed.
