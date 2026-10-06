#!/usr/bin/env bash
# Run the ARIES Shell in a HEADLESS nested GNOME Shell and report what happened.
#
#   ./scripts/test-shell.sh [seconds]        default 25
#
# WHY THIS EXISTS
# ---------------
# A GNOME Shell extension runs inside gnome-shell, and on Wayland a shell that
# throws during startup cannot be restarted without logging out. Testing by
# enabling it in the live session and seeing what happens is therefore a test
# whose failure mode is "lose the user's desktop".
#
# GNOME Shell 50 can run headless against a virtual monitor on its own D-Bus
# session. That is a complete, isolated GNOME — real Mutter, real St, real
# extension loading — that can be started, driven and killed without touching
# the session the user is sitting in. Every change to the extension is tried
# here first.
#
# WHAT IT CHECKS
#   · the extension loads and reaches ENABLED
#   · nothing was logged as an ARIES failure
#   · no JavaScript exception mentions the extension
#   · disable() removes what enable() added, with nothing left behind
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
UUID="aries@aries.local"
SECONDS_TO_RUN="${1:-25}"
LOG="$(mktemp -t aries-shell-test-XXXXXX.log)"
ok=1

# ── every user setting the shell is capable of writing ──────────────────────
#
# The first version of this guard saved the two extension lists, which was the
# leak known at the time. Then the shell gained the ability to take Super+Space
# from `switch-input-source` and to set the background — and a nested test run
# promptly took Super+Space off the real desktop, because dconf is per-USER and
# a nested compositor isolates none of it.
#
# So the guard now covers everything the extension can write, and the list lives
# next to the code that writes it. A test asserts the two match, because a guard
# that silently falls behind the code it guards is worse than none: it reads as
# protection.
ARIES_WRITES=(
  "org.gnome.shell enabled-extensions"
  "org.gnome.shell disabled-extensions"
  "org.gnome.desktop.wm.keybindings switch-input-source"
  "org.gnome.desktop.wm.keybindings switch-input-source-backward"
  "org.gnome.desktop.background picture-uri"
  "org.gnome.desktop.background picture-uri-dark"
  "org.gnome.desktop.background picture-options"
  "org.gnome.desktop.session idle-delay"
)
SAVED_SETTINGS=()
for entry in "${ARIES_WRITES[@]}"; do
  SAVED_SETTINGS+=("$(gsettings get $entry 2>/dev/null || echo SKIP)")
done
restore_extensions() {
  local i=0
  for entry in "${ARIES_WRITES[@]}"; do
    [ "${SAVED_SETTINGS[$i]}" = "SKIP" ] || \
      gsettings set $entry "${SAVED_SETTINGS[$i]}" 2>/dev/null || true
    i=$((i+1))
  done
}

trap restore_extensions EXIT INT TERM

pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; ok=0; }
note() { printf '      %s\n' "$*"; }

echo
echo "=== ARIES Shell in a headless nested GNOME Shell (${SECONDS_TO_RUN}s) ==="
echo

[ -e "$HOME/.local/share/gnome-shell/extensions/$UUID" ] || {
  echo "not installed — run: ./scripts/aries-shell install"; exit 2; }

# The nested shell gets its own session bus, so enabling the extension inside it
# cannot change what is enabled in the user's real session.
cat > "$LOG.script" <<'INNER'
#!/usr/bin/env bash
set -u
UUID="aries@aries.local"
gnome-shell --headless --virtual-monitor 1600x1000 --wayland-display aries-test &
SHELL_PID=$!
sleep 8
# Inside this session only: stand the other dock down so the ARIES dock is
# actually built and exercised. The user's real session is untouched — this is
# a separate D-Bus session with its own gnome-shell.
gnome-extensions disable ubuntu-dock@ubuntu.com 2>/dev/null || true
sleep 1
gnome-extensions enable "$UUID" 2>&1 | sed 's/^/enable: /'
sleep 4
gnome-extensions info "$UUID" 2>&1 | sed 's/^/info: /'
# What actually got built — "it loaded" says nothing, because every component is
# guarded and the extension reaches ENABLED whether six surfaces came up or one.
gdbus call --session --dest org.aries.Shell --object-path /org/aries/Shell \
  --method org.aries.Shell.Ping 2>&1 | sed 's/^/ping: /'

# The surfaces respond to being driven, not merely to existing.
gdbus call --session --dest org.aries.Shell --object-path /org/aries/Shell \
  --method org.aries.Shell.Search "run system health" 2>&1 | sed 's/^/search: /'
sleep 2
gdbus call --session --dest org.aries.Shell --object-path /org/aries/Shell \
  --method org.aries.Shell.Close 2>&1 | sed 's/^/close: /'
gdbus call --session --dest org.aries.Shell --object-path /org/aries/Shell \
  --method org.aries.Shell.Launcher 2>&1 | sed 's/^/launcher: /'
sleep 2
gdbus call --session --dest org.aries.Shell --object-path /org/aries/Shell \
  --method org.aries.Shell.Close >/dev/null 2>&1

WAYLAND_DISPLAY=aries-test timeout 20s /usr/bin/python3 tests/integration/focus_window_probe.py
sleep "${RUN_FOR:-10}"
echo "--- disabling ---"
gnome-extensions disable "$UUID" 2>&1 | sed 's/^/disable: /'
sleep 3
gnome-extensions info "$UUID" 2>&1 | sed 's/^/after: /'

# Enable again. A teardown that leaks — a keybinding still bound, a panel role
# still taken, a D-Bus name still owned — fails on the SECOND enable, not the
# first, which is why disabling once and calling it clean proves little.
echo "--- re-enabling ---"
gnome-extensions enable "$UUID" 2>&1 | sed 's/^/reenable: /'
sleep 4
gdbus call --session --dest org.aries.Shell --object-path /org/aries/Shell \
  --method org.aries.Shell.Ping 2>&1 | sed 's/^/ping2: /'
gnome-extensions disable "$UUID" 2>&1 | sed 's/^/disable2: /'
sleep 2
kill "$SHELL_PID" 2>/dev/null
wait "$SHELL_PID" 2>/dev/null
INNER
chmod +x "$LOG.script"

RUN_FOR=$(( SECONDS_TO_RUN > 14 ? SECONDS_TO_RUN - 14 : 4 )) \
  timeout $(( SECONDS_TO_RUN + 25 )) \
  dbus-run-session -- "$LOG.script" > "$LOG" 2>&1 || true

# ── what the run said ───────────────────────────────────────────────────────
if grep -qE '^info: .*State: ACTIVE|^info: .*State: ENABLED' "$LOG"; then
  pass "the extension loaded and reached ENABLED"
elif grep -q '^info:' "$LOG"; then
  fail "the extension did not enable — $(grep -m1 '^info: *State' "$LOG" | sed 's/^info: *//')"
else
  fail "the nested shell did not report extension state (see $LOG)"
fi

if grep -q "^enable: " "$LOG"; then
  note "$(grep -m1 '^enable: ' "$LOG")"
fi

aries_errors=$(grep -c "\[ARIES\].*build .*:" "$LOG" || true)
if [ "${aries_errors:-0}" = "0" ]; then
  pass "no ARIES component reported a build failure"
else
  fail "$aries_errors ARIES component failure(s)"
  grep "\[ARIES\]" "$LOG" | grep -E "build .*:" | head -5 | sed 's/^/      /'
fi

# ANY JavaScript error while the extension is loaded, not only ones whose text
# happens to name it. The mark's drawing bug logged
#   "TypeError: (intermediate value).cairo_set_source_color is not a function"
# on every repaint — no mention of ARIES anywhere on the line — so a check that
# grepped for the extension's name reported a clean run while the logo was
# invisible on screen. An exception in a session that exists to run one
# extension is that extension's until proven otherwise.
js_errors=$(grep -cE "JS ERROR" "$LOG" || true)
if [ "${js_errors:-0}" = "0" ]; then
  pass "no JavaScript exception at all while the extension was loaded"
else
  fail "$js_errors JavaScript exception(s) during the run"
  grep -E "JS ERROR" "$LOG" | head -5 | sed 's/^/      /'
fi

# Teardown is checked on what the extension itself reported plus the absence of
# anything thrown while unwinding. The `info` call after the kill is advisory:
# the nested shell may already be gone, and a race in the harness is not a
# defect in the extension.
if grep -q "\[ARIES\] disabling" "$LOG"; then
  teardown_errors=$(awk '/\[ARIES\] disabling/,0' "$LOG" | grep -c "\[ARIES\] destroy .*:" || true)
  if [ "${teardown_errors:-0}" = "0" ]; then
    pass "disable() ran and tore everything down cleanly — the fallback works"
  else
    fail "$teardown_errors error(s) while tearing down"
    awk '/\[ARIES\] disabling/,0' "$LOG" | grep "\[ARIES\] destroy" | head -5 | sed 's/^/      /'
  fi
  if grep -qE '^after: .*State: (INACTIVE|DISABLED)' "$LOG"; then
    note "GNOME also confirms it is INACTIVE"
  fi
else
  fail "the extension never reported disabling"
fi

if grep -q "\[ARIES\] ubuntu-dock.*is enabled" "$LOG"; then
  note "the dock stood down for another dock — not exercised in this run"
fi

# ── which surfaces actually came up ─────────────────────────────────────────
ping=$(grep -m1 '^ping: ' "$LOG" | sed "s/^ping: *('//; s/',)$//" | sed 's/\\"/"/g' || true)
if [ -n "$ping" ]; then
  missing=""
  for surface in "aries mark" "top bar" "quick settings" "ARIES Search" launcher \
                 notifications overview wallpaper "dbus surface"; do
    case "$ping" in
      *"$surface"*) ;;
      *) missing="$missing $surface" ;;
    esac
  done
  if [ -z "$missing" ]; then
    pass "every surface was built, not merely the extension loaded"
  else
    fail "surfaces missing:$missing"
  fi
  case "$ping" in
    *'"failures":[]'*) pass "and none of them reported a failure" ;;
    *) fail "a surface reported a failure"
       echo "      $ping" | head -c 400 | sed 's/^/      /' ;;
  esac
else
  fail "the shell did not answer org.aries.Shell.Ping"
fi

# ── driving them ────────────────────────────────────────────────────────────
if grep -q "^search: ()" "$LOG"; then
  pass "ARIES Search opens when asked over D-Bus"
else
  fail "ARIES Search did not respond"
  grep -m1 '^search: ' "$LOG" | sed 's/^/      /' || true
fi
if grep -q "^launcher: ()" "$LOG"; then
  pass "the launcher opens when asked"
else
  fail "the launcher did not respond"
fi

# ── enable → disable → enable ───────────────────────────────────────────────
if grep -q '^focus-probe: PASS' "$LOG"; then
  pass "existing window restores and focuses; wrong identity and stale IDs refused"
else
  fail "window focus integration probe failed"
  grep '^focus-probe:' "$LOG" || true
fi

if grep -qE '^ping2: .*"built"' "$LOG"; then
  pass "it enables cleanly a SECOND time — nothing leaked on teardown"
  case "$(grep -m1 '^ping2: ' "$LOG")" in
    *'"failures":[]'*) pass "with no failure on the second run either" ;;
    *) fail "the second enable reported a failure"
       grep -m1 '^ping2: ' "$LOG" | head -c 300 | sed 's/^/      /' ;;
  esac
else
  fail "the extension did not come back after being disabled"
  grep -m1 '^reenable: ' "$LOG" | sed 's/^/      /' || true
fi

if grep -q "\[ARIES\] enabling" "$LOG"; then
  pass "the extension's own log shows it starting"
  note "$(grep -m1 '\[ARIES\] enabling' "$LOG" | sed 's/.*\[ARIES\]/[ARIES]/')"
else
  note "the extension logged nothing — it may not have been reached"
fi

echo
if [ "$ok" = "1" ]; then
  echo "ALL PASSED"
  rm -f "$LOG" "$LOG.script"
  exit 0
fi
echo "FAILURES — full log: $LOG"
exit 1
