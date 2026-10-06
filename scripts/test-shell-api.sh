#!/usr/bin/env bash
# The shell's HTTP layer, in plain gjs, against a deliberately broken ARIES.
#
# `lib/api.js` imports nothing from gnome-shell, so it runs outside a compositor.
# That is what makes timeout, truncation, refusal and cancellation testable at
# all — none of them can be produced on demand by pointing at the real ARIES.
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${1:-8099}"

python3 tests/shell/fake_aries.py "$PORT" &
FAKE=$!
trap 'kill $FAKE 2>/dev/null || true' EXIT

for _ in $(seq 1 40); do
  curl -sf -m 1 "http://127.0.0.1:$PORT/ok" >/dev/null 2>&1 && break
  sleep 0.1
done

gjs -m tests/shell/test_api.js "$PORT"
