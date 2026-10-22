# One entry point. Every target calls a script that already exists; this file adds no behaviour.
#
#   make setup        create .venv and install the pinned dependencies (docs/INSTALLATION.md)
#   make test         the whole suite (scripts/test.sh)
#   make lint         pyflakes and syntax errors only (ruff --select F,E9); RUFF=<path> if not on PATH
#   make check        the frozen thesis tables and the figures still match their sources (read-only)
#   make figures      redraw the comparison figures (experiments/analysis/figures/)
#   make smoke        "can I use ARIES right now?" against the running service (scripts/aries-smoke)
#   make eval-thesis  print the thesis evaluations; EVAL=<name> runs exactly one of them
#   make eval-iis     print the IIS evaluations;    EVAL=<name> runs exactly one of them
#
# The eval-* targets run nothing unless EVAL names one entry (scripts/eval.sh). Several of them
# need the live service, the local model or the GPU, and most write a new run folder.

PY ?= .venv/bin/python
RUFF ?= ruff

.PHONY: setup test lint check figures smoke eval-thesis eval-iis

setup:
	uv venv --python 3.12 .venv
	uv pip install --python $(PY) -r requirements.lock
	./scripts/install-hooks.sh

test:
	./scripts/test.sh

lint:
	$(RUFF) check --isolated --select F,E9 aries aries_ui tests

check:
	PYTHONPATH=$(CURDIR)/vendor/agentic-core:$(CURDIR)/vendor:$(CURDIR) $(PY) experiments/thesis-followup-20261012/thesis-tables/check.py
	$(PY) experiments/analysis/make_figures.py --check

figures:
	$(PY) experiments/analysis/make_figures.py

smoke:
	./scripts/aries-smoke

eval-thesis:
	EVAL=$(EVAL) ./scripts/eval.sh thesis

eval-iis:
	EVAL=$(EVAL) ./scripts/eval.sh iis
