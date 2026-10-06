# Macedonian, frozen 2026-10-03

English became the primary language on 2026-10-03. Macedonian is **frozen**: it keeps
working, it keeps being tested, and nothing new is built on it. Frozen is not removed
— a Macedonian request must still be heard, routed, executed and answered, and this
directory is what proves it.

## Why this is a manifest and not a pile of moved files

The plan said to move the Macedonian tests here. One file is genuinely
Macedonian-*subject* — `tests/test_goal_contracts.py`, whose own docstring is
"Macedonian goals retain the same independent proof requirements as English". The rest
of the Macedonian coverage lives **inside bilingual tests**: `test_memory.py` (54
Macedonian lines), `test_replies.py` (12), `test_spoken_requests.py` (11),
`test_voice_flow.py` (13), `test_pronoun_arguments.py` (15). Those files test one
behaviour in two languages at once. Moving them here would take the **English** half of
each out of the main suite, which is the opposite of what freezing Macedonian is for.

A second reason, specific to today: the working tree carries 186 uncommitted files from
another agent's in-flight work, and `test_goal_contracts.py` is one of them. Moving a
file somebody is editing produces a conflict for no gain.

So the freeze is enforced by **manifest plus runner**: `MANIFEST` names every test that
covers Macedonian and where it lives, and `run_frozen.py` runs them and fails if any
stops passing. The isolation the plan wanted — a named, bounded, unextended Macedonian
surface — is achieved by naming it. The files can be physically moved later at no cost;
nothing depends on their path except `scripts/test.sh`'s glob.

**Do not extend any test named in `MANIFEST`.** New language work goes to English.

## Running it

```sh
APP_ENV=test PYTHONPATH=vendor/agentic-core:vendor:. .venv/bin/python tests/frozen_mk/run_frozen.py
```

It runs each named file in its own process, the way `scripts/test.sh` does, and prints
one line per file. Exit code is non-zero if any Macedonian coverage has regressed.
