# H8 rerun with ARIES_VERIFY_SCOPE (exploratory, designed after H8)

**Status: prepared, not run.** Nothing in this folder is a result yet.

## What and why

H8 (`docs/preregistration/H8-verifier-fault-injection.md`) found that 0 of 14
`side_effect_outside_scope` mutants were killed in every run
(`experiments/thesis-followup-20261012/h8/RESULTS.md`; `docs/AUDIT.md` section 4e). All 14 target
INDEPENDENT verifiers, which re-read the target and nothing next to it.

`ARIES_VERIFY_SCOPE` (`aries/workspace/scope_verifiers.py`, default off) adds a differential check
to exactly those 14 capabilities: the declared scope is snapshotted before the executor runs and
compared after the frozen verifier ran. This check was **designed after seeing the H8 result**, so
any number produced here is exploratory. It is not part of the confirmatory H8 test, and the H8
results are not changed by it.

## The rule, fixed before running

| class | scope | declared target |
|---|---|---|
| file.write, browser.download, file.edit | parent folder of `path`, one level | `path` |
| file.copy | parent folders of `path` and `destination` | `destination` only |
| file.move, file.rename | parent folders of `path` and `destination` | `path` and `destination` |
| desktop.close/maximize/minimize/move/resize/tile/unmaximize | every other window: geometry, minimised, maximised, workspace, monitor, existence | the target window |
| notification.send | the notification table | the one returned row |

## Prediction, written before running

The H8 side effect writes `docs/outside.txt` in the case sandbox
(`run_mutants.py`, `build_cases`).
- `file.edit`, `file.copy`, `file.move`, `file.rename`: the target or source is in `docs/`, so the
  stray file is inside the scope. Expected **killed**.
- `file.write` and `browser.download`: the target is in `out/`, so `docs/` is a sibling folder outside
  the one-level scope. Expected **survived**. This is a stated limit of the rule, and the rule is not
  widened to fit the harness.
- The 7 desktop mutants move window 102 by 37 px. Expected **killed**.
- `notification.send` adds a second row. Expected **killed**.

So the prediction is 12 of 14 killed. Clean replays of the 14 capabilities should stay `met`, with
0 false alarms. Any other capability is unaffected, because nothing else is wrapped.

## How to run it (not run here)

It is offline by construction. The harness's own tripwires refuse network access, D-Bus, systemctl,
browsers and the other live tools. It loads no model, so it needs **no GPU, no Ollama and no ARIES
service**. It uses a scratch SQLite database (`APP_ENV=test`) and a temporary sandbox under `$HOME`,
and caps its own address space at 3 GiB. The `system.*` probes read the real machine read-only, as
in H8.

```
cd /home/stamenovmartin/aries-cons
nice -n 19 .venv/bin/python experiments/exploratory/h8-verify-scope/run.py \
    --manifest experiments/thesis-followup-20261012/h8/mutants.json --label exploratory-verify-scope
python3 -I experiments/thesis-followup-20261012/h8/analyze.py \
    experiments/exploratory/h8-verify-scope/runs/<run-folder> \
    experiments/thesis-followup-20261012/h8/runs/20261018T153000Z-baseline2
```

`run.py` loads the frozen `run_mutants.py` unchanged. It only redirects the output folder from
`h8/runs/` to `experiments/exploratory/h8-verify-scope/runs/`, and it writes `exploratory.json`
(harness SHA-256, wrapper SHA-256, `flags.describe()`) into the run folder. It refuses `--hardened`
and `--sealed`. `analyze.py` writes its `summary.json` into the run folder given, which here is the
exploratory one.
