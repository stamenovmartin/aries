# Conditions of this run (added after the run; the runner does not log this flag)

Command: `ARIES_VERIFY_HARDENED_EXTRA=1 .venv/bin/python experiments/thesis-followup-20261012/h8/run_mutants.py --manifest experiments/thesis-followup-20261012/h8/mutants.json --label exploratory-hardened-23plus2 --hardened`

- `ARIES_VERIFY_HARDENED=1`: set by the runner (`--hardened`, recorded in run.json).
- `ARIES_VERIFY_HARDENED_EXTRA=1`: set in the shell. `run.json` does not record it.
- The runner is the same one used for baseline-2 (`runner_sha256` in run.json).
- Exploratory condition "hardened-23+2, designed after baseline-2" (Amendment 2). It is not part of the
  confirmatory criteria or the Holm family.
