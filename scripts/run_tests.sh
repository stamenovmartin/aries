#!/usr/bin/env bash
# Every test in its own process with its own sqlite file and APP_ENV=test.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/agentic-core:$PWD:${PYTHONPATH:-}"
python agentic-core/tests/run_tests.py "$@"
echo "--- linux example"
python examples/linux_agent/test_linux_agent.py
