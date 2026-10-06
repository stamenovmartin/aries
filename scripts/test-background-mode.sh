#!/usr/bin/env bash
# The elapsed-time Background Mode test. Takes minutes and touches the real
# display timeout (and restores it). ARIES must already be running.
#
#   ./scripts/test-background-mode.sh [minutes]      default 4
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/vendor/agentic-core:$PWD/vendor:$PWD:${PYTHONPATH:-}"
exec .venv/bin/python tests/integration/test_background_mode.py "${1:-4}"
