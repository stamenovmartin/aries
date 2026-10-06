#!/usr/bin/env bash
# Every ARIES test: the engine's suite, the Linux reference example, and ARIES's own.
# Each test file runs in its own process with its own sqlite file and APP_ENV=test.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/vendor/agentic-core:$PWD/vendor:$PWD:${PYTHONPATH:-}"
PY=.venv/bin/python
fail=0

echo "=== engine (agentic_core) ==="
$PY vendor/agentic-core/tests/run_tests.py "$@" || fail=1

echo
echo "=== engine reference example (linux_agent) ==="
$PY vendor/examples/linux_agent/test_linux_agent.py || fail=1

echo
echo "=== aries ==="
for t in tests/test_*.py; do
  # The Control Centre's own tests import `gi`, which lives on the system
  # interpreter and not in this virtual environment (ADR-0004). They run below,
  # as their own step.
  [ "$(basename "$t")" = "test_ui_client.py" ] && continue
  printf '%-44s' "$(basename "$t")"
  if out=$($PY "$t" 2>&1); then
    echo "passed  ($(grep -c '^PASS' <<<"$out") checks)"
  else
    echo "FAILED"; echo "$out" | sed 's/^/    /'; fail=1
  fi
done

echo
echo "=== shell HTTP layer (gjs, against a deliberately broken ARIES) ==="
# `lib/api.js` imports nothing from gnome-shell, so timeout, truncation,
# refusal and cancellation are testable outside a compositor — which is the
# only way to produce them on demand.
if command -v gjs >/dev/null 2>&1; then
  printf '%-44s' "test_api.js"
  if out=$(./scripts/test-shell-api.sh 2>&1); then
    echo "passed  ($(grep -c '^PASS' <<<"$out") checks)"
  else
    echo "FAILED"; echo "$out" | grep -E '^FAIL' | sed 's/^/    /'; fail=1
  fi
else
  echo "  skipped — gjs is not installed"
fi

echo
echo "=== control centre (system python: GTK bindings live there, not in .venv) ==="
# ADR-0004: the UI runs on the system interpreter and imports nothing from
# `aries`, so its tests cannot run in the venv. No window is opened.
if /usr/bin/python3 -c "import gi" 2>/dev/null; then
  printf '%-44s' "test_ui_client.py"
  if out=$(PYTHONPATH="$PWD" /usr/bin/python3 tests/test_ui_client.py 2>&1); then
    echo "passed  ($(grep -c '^PASS' <<<"$out") checks)"
  else
    echo "FAILED"; echo "$out" | grep -E '^FAIL|Error' | sed 's/^/    /'; fail=1
  fi
else
  echo "  skipped — PyGObject is not available on the system interpreter"
fi

echo
# Deliberately not run here: tests/integration/test_background_mode.py takes
# minutes of real elapsed time and changes the machine's display timeout (and
# puts it back). Run it on purpose: ./scripts/test-background-mode.sh
echo "not run here: ./scripts/test-background-mode.sh  (real elapsed time, touches the display timeout)"
echo "not run here: ./scripts/test-shell.sh              (starts a nested GNOME Shell, ~50s)"
echo "not run here: ./scripts/test-session.sh            (proves the login session, ~45s)"

echo
[ $fail -eq 0 ] && echo "ALL SUITES PASSED" || echo "SOME SUITES FAILED"
exit $fail
