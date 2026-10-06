# ADR-0002 — Python 3.12 supplied by `uv`, in user space

**Status:** accepted · **Date:** 2026-09-12 · **Journal:** Entry 001

## Context

Ubuntu 26.04 ships Python 3.14.4 as the system interpreter, but `python3 -m venv` fails:
`ensurepip` lives in the separate `python3.14-venv` package, which is not installed and needs
`sudo`. The system interpreter is also PEP 668 "externally managed", so installing into it
is refused — correctly, since the distribution owns those files.

Separately, the engine's pinned dependencies date from late 2024. Checking published wheel
tags on PyPI:

```
pydantic-core · sqlalchemy · asyncpg  →  cp310 cp311 cp312 cp313 cp314 cp315
```

`cp314` tags exist only on *recent* releases. `pydantic-settings 2.7.0` resolves to
`pydantic ~2.10` → `pydantic-core 2.27`, which predates CPython 3.14. On Python 3.14 that set
would attempt a Rust source build and fail.

## Options

1. **`sudo apt install python3.14-venv` + bump every pin** — standard distro tooling, but runs
   the engine on dependency versions its 13 test files were never executed against, and needs
   the user's password.
2. **`uv` + a private CPython 3.12** — a Rust-based Python package and version manager that
   installs into `~/.local`, downloads standalone interpreters, and needs no root. Keeps the
   exact tested pins.

## Decision

Option 2. The engine's value *is* its tested behaviour, so anything that weakens the test
suite's authority is the wrong trade; and no `sudo` was required at all.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
uv venv --python 3.12 ~/aries/.venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Every pin resolved to a wheel; nothing was built from source. All 13 engine test files and
the Linux example passed.

## Consequences

**Positive.** Reproducible and fully user-space; nothing system-wide was touched; removal is
`rm -rf ~/aries ~/.local/share/uv ~/.local/bin/uv`. The Python version is pinned by the
project rather than by whatever the distribution ships next.

**Negative.** One third-party installer was fetched and executed from `astral.sh` over TLS —
accepted against the alternative of granting `sudo` to apt, and confined to `~/.local`. A
second Python installation exists on the machine, which is the normal state of affairs for
any serious Python project.

**Revisit when** a dependency drops 3.12 support (years away), or the project needs a
3.13+ feature. The move is then a pin bump plus a full test run, not a redesign.
