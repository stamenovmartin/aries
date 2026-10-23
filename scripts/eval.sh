#!/usr/bin/env bash
# The evaluations behind `make eval-thesis` and `make eval-iis`, listed in one place.
#
#   ./scripts/eval.sh thesis            print every thesis evaluation: name, what it needs, the command
#   ./scripts/eval.sh iis               the same for the IIS project
#   EVAL=<name> ./scripts/eval.sh thesis   run exactly that one
#
# Nothing runs unless EVAL names one entry. Several entries need the live service, the local
# model or the GPU, and most write a new run folder. Read the "needs" line first.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/vendor/agentic-core:$PWD/vendor:$PWD:${PYTHONPATH:-}"
PY=.venv/bin/python
LABEL="${LABEL:-make}"

thesis() {
  cat <<TABLE
tables|nothing; read-only|$PY experiments/thesis-followup-20261012/thesis-tables/check.py
agent-suite|aries-core and the local model; writes eval/agent_suite/<run>|$PY eval/agent_suite/run.py --label $LABEL --flags on
h5-treatment|a captured service env (run_h5.py --capture-env), the local model, aries-core stopped; writes h5-runs/<run>|$PY experiments/thesis-followup-20261012/h5-runs/run_h5.py --condition treatment --label $LABEL --go
h5-control|as h5-treatment|$PY experiments/thesis-followup-20261012/h5-runs/run_h5.py --condition control --label $LABEL --go
h4b-treatment|a captured service env (run_h4b.py --capture-env), the local model, aries-core stopped; writes h4b-runs/<run>|$PY experiments/thesis-followup-20261012/h4b-runs/run_h4b.py --condition treatment --label $LABEL --go
h4b-baseline|as h4b-treatment|$PY experiments/thesis-followup-20261012/h4b-runs/run_h4b.py --condition baseline --label $LABEL --go
r1|NL2Bash and CLINC150 in ~/data-ext (download.sh), the local model, aries.target stopped by the script; frozen R1 window, run from ~/aries|bash experiments/thesis-r1-real-data/run-r1.sh
r1b-x1|the R1b samples and labels, the H5/H4b items, the local model; stops and restarts aries.target; writes new raw files|bash experiments/thesis-improvements-20261022/run-improvements.sh
m2|the R1b samples, ollama with llama3.1:8b, qwen2.5:1.5b and qwen2.5:14b; stops and restarts aries.target|bash experiments/thesis-m2-models/run-m2.sh
m2-analysis|the M2 raw files; refuses if summary.json exists|$PY experiments/thesis-m2-models/analyze_m2.py
hal1|the H5, H4b, X1, R1 and R1b run folders; refuses if hallucination-summary.json exists|$PY experiments/thesis-improvements-20261022/hallucination_eval.py
h8-scope|nothing live: offline, no model, no GPU; writes experiments/exploratory/h8-verify-scope/runs/<run>; exploratory, designed after H8|$PY experiments/exploratory/h8-verify-scope/run.py --manifest experiments/thesis-followup-20261012/h8/mutants.json --label exploratory-verify-scope
TABLE
}

iis() {
  cat <<TABLE
memory|the local model and the e5 embedder; rewrites experiments/iis/memory/results.jsonl and summary.json|./scripts/aries-memory-eval
memory-bge-m3|Ollama with bge-m3; rewrites the same files|EMBEDDER=bge-m3-ollama ./scripts/aries-memory-eval
locomo|LoCoMo in ~/data-ext (experiments/iis/real-data/locomo/download.sh), the e5 embedder; writes a new results file|$PY experiments/iis/real-data/locomo/locomo_eval.py --variants embedding-only-e5,hybrid-similarity-e5
mind|MIND-small in ~/data-ext/mind (experiments/iis/real-data/mind/download.sh), the e5 embedder; writes a new results file|$PY experiments/iis/real-data/mind/mind_eval.py --embedding
TABLE
}

case "${1:-}" in
  thesis) table=$(thesis) ;;
  iis) table=$(iis) ;;
  *) echo "usage: [EVAL=<name>] $0 thesis|iis" >&2; exit 2 ;;
esac

if [ -z "${EVAL:-}" ]; then
  echo "Nothing runs without EVAL=<name>. Available ($1):"
  while IFS='|' read -r name needs cmd; do
    printf '\n  %s\n    needs: %s\n    runs:  %s\n' "$name" "$needs" "$cmd"
  done <<< "$table"
  exit 0
fi
line=$(grep -E "^${EVAL}\|" <<< "$table" || true)
if [ -z "$line" ]; then
  echo "unknown EVAL=$EVAL for $1" >&2
  exit 2
fi
cmd=${line#*|}
cmd=${cmd#*|}
echo "running: $cmd"
eval "$cmd"
