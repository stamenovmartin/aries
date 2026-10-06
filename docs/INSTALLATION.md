# ARIES — Installation

Verified on Ubuntu 26.04.1 LTS. Nothing below needs `sudo` except the optional `git` step.

## 1. Runtime

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh      # → ~/.local/bin/uv
export PATH="$HOME/.local/bin:$PATH"                 # add to ~/.bashrc to persist
uv python install 3.12
```

The system Python is not used. See `decisions/ADR-0002` for why 3.12 rather than the
system's 3.14 — briefly: the engine's pinned dependencies have no CPython 3.14 wheels and
would attempt a Rust source build.

## 2. Project

```bash
cd ~/aries
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

## 3. Verify

```bash
./scripts/test.sh
```

Expected: 13 engine test files, the Linux reference example (10 assertions), and the ARIES
suites — ending in `ALL SUITES PASSED`. **Do not build on a foundation that has not been run.**

## 4. Configuration

```bash
cp .env.example .env
```

Safe defaults ship deliberately: `DRY_RUN=true`, `LIVE_TOOLS=` empty, `AI_PROVIDER=template`
(deterministic, offline, no model needed), every credential empty. Holding a credential is
not permission to use it; clearing a tool for live execution is a separate, explicit act.

For a real model, set `AI_PROVIDER=cli` — the `the reviewing agent` binary is already present at
`~/.local/bin/the reviewing agent`. `ollama` and any OpenAI-compatible endpoint are also supported.

## 5. Running

```bash
export PYTHONPATH="$PWD/vendor/agentic-core:$PWD/vendor:$PWD"
.venv/bin/python scripts/init_db.py
.venv/bin/uvicorn agentic_core.api.main:app --host 127.0.0.1 --port 8000
```

Bind to `127.0.0.1`, not `0.0.0.0`: `API_KEY` defaults to empty, which means an open API.
Interactive docs at `http://localhost:8000/docs`.

## 6. Optional — git

```bash
sudo apt install -y git
cd ~/aries && git init
```

## Layout

```
~/aries/
├── .venv/              Python 3.12.14 + pinned dependencies
├── aries/              the ARIES package  ← ARIES code goes here
├── vendor/
│   ├── agentic-core/   the engine — vendored, do not modify
│   └── examples/       marketing + linux_agent, reference only
├── docs/               journal, architecture, decisions
├── scripts/            test.sh · start.sh · init_db.py
├── tests/              ARIES test suites
└── var/                runtime data
```

## Removal

```bash
rm -rf ~/aries
rm -rf ~/.local/share/uv ~/.local/bin/uv ~/.local/bin/uvx
```
