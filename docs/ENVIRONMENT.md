# Environment

This is the machine and software that the current results come from. It was recorded on
2026-10-22 with read-only commands only: version flags and `ollama list`. No model was loaded and
no service was started or stopped.

## Platform

| item | value | source |
|---|---|---|
| OS | Ubuntu 26.04.1 LTS | `/etc/os-release` |
| kernel | Linux 7.0.0-38-generic x86_64 | `uname -srm` |
| desktop | GNOME Shell 50.1 | `gnome-shell --version` |
| CPU threads | 12 | `nproc` |
| memory | 14 GiB | `free -g` |
| GPU | NVIDIA GeForce RTX 3060, 12288 MiB, driver 595.91.07 | `nvidia-smi --query-gpu=...` |

## Python

| item | value |
|---|---|
| project interpreter | Python 3.12.14 (`.venv/bin/python`, a uv-managed CPython: `~/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu`) |
| package manager | uv 0.12.13 |
| direct dependencies | `requirements.txt` (hand-maintained, with the reason for each) |
| exact installed set | `requirements.lock`, 89 packages, from `uv pip freeze --python .venv/bin/python`. The venv has no `pip` module, so `python -m pip freeze` cannot run there; uv reads the same installed metadata |
| system interpreter | Python 3.14.4 (`/usr/bin/python3`). The Control Centre runs on it, because PyGObject lives there (ADR-0004) |

To reproduce the environment: `make setup` creates `.venv` with Python 3.12 and installs
`requirements.lock`.

## Local models (Ollama)

| item | value |
|---|---|
| Ollama | 0.34.0 (`ollama --version`) |

`ollama list` reports the ID, which is the first 12 hex digits of the manifest digest:

| model | ID | size | used for |
|---|---|---|---|
| qwen2.5:7b | 845dbda0ea48 | 4.7 GB | router, planner and every confirmatory run. The full digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e` is recorded in `experiments/thesis-followup-20261012/inputs/final-evaluation.json` |
| llama3.1:8b | 46e0c10c039e | 4.9 GB | the second-model router run and the H6 secondary run (exploratory); M2 (confirmatory) |
| qwen2.5:1.5b | 65ec06548149 | 986 MB | M2 (confirmatory): the smaller model of the same family |
| qwen2.5:14b | 7cdf5a0187d5 | 9.0 GB | M2 (confirmatory): the largest model of the family that fits the 12 GB GPU |
| bge-m3:latest | 790764642607 | 1.2 GB | the alternative memory embedder (exploratory) |

The default memory embedder, `intfloat/multilingual-e5-base` as int8 ONNX, is not an Ollama model.
`scripts/aries-fetch-embedder` fetches it into `var/models/`. The Whisper builds are in
`var/models/` too (`aries/flags.py`, `WHISPER_MODELS`).

## Flags

Every behaviour flag, with its default, is in `docs/CONFIG_REFERENCE.md`, which
`scripts/gen_config_reference.py` generates. The live service runs every flag at its code default
(`docs/AUDIT.md` §5).
