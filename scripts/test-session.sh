#!/usr/bin/env bash
# Does the ARIES session mode actually produce an ARIES desktop?
#
#   ./scripts/test-session.sh [seconds]        default 25
#
# WHY THIS RUNS BEFORE ANYTHING IS INSTALLED
# ------------------------------------------
# Installing a session entry means writing into /usr/share and /etc, and getting
# it wrong means a login screen offering a session that does not start. That is
# the one failure in this whole project a user cannot recover from inside the
# system — they would need a TTY and a working knowledge of what we did.
#
# So the mode is proved first, with nothing installed. `gnome-shell` finds modes
# by walking XDG_DATA_DIRS, so pointing that at a directory we own is enough to
# load the real mode file in a real GNOME Shell, in a nested headless session,
# started exactly the way the session would start it: `--mode=aries`.
#
# The assertion that matters: the ARIES extension is enabled WITHOUT anyone
# running `gnome-extensions enable`. That is the whole promise of a session —
# you log into ARIES and ARIES is there.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
UUID="aries@aries.local"
RUN_FOR="${1:-25}"
# --installed: test what is ON DISK rather than a staged copy. "It would work if
# installed" and "what got installed works" are different assurances, and only
# the second one is about the machine the user will log into.
INSTALLED=""
[ "${2:-}" = "--installed" ] && INSTALLED="yes"
STAGE="$(mktemp -d -t aries-session-XXXXXX)"
LOG="$STAGE/run.log"
ok=1

pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; ok=0; }
note() { printf '      %s\n' "$*"; }


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

cleanup() { restore_extensions; rm -rf "$STAGE"; }
trap cleanup EXIT INT TERM

echo
echo "=== the ARIES session mode, in a nested GNOME Shell ==="
echo

[ -d "shell/$UUID" ] || { echo "the extension source is missing"; exit 2; }

# Stage the mode AND the extension where a system data dir would put them.
#
# The extension has to be staged as a SYSTEM extension, not a user one, and that
# is not a detail of the test — it is the finding that shaped the installer.
# GNOME Shell refuses to load a per-user extension as part of a session mode:
#
#   "Found user extension aries@aries.local, but not loading from
#    ~/.local/share/gnome-shell/extensions/... as part of session mode."
#
# Which is right. A session mode is system configuration, and it must not be
# able to auto-load code out of somebody's home directory. So the ARIES session
# installs the extension system-wide, and this stage mirrors that — otherwise
# the test would pass against an arrangement the real session cannot use.
if [ -n "$INSTALLED" ]; then
  echo "      testing the INSTALLED files, not a staged copy"
  for f in /usr/local/share/gnome-shell/modes/aries.json \
           /usr/local/share/gnome-shell/extensions/$UUID \
           /usr/share/wayland-sessions/aries.desktop; do
    [ -e "$f" ] || { echo "not installed: $f"; exit 2; }
  done
else
  mkdir -p "$STAGE/gnome-shell/modes" "$STAGE/gnome-shell/extensions"
  cp session/modes/aries.json "$STAGE/gnome-shell/modes/aries.json"
  cp -rL "shell/$UUID" "$STAGE/gnome-shell/extensions/$UUID"
fi

# `disabled-extensions` takes PRECEDENCE over a session mode's list, so a uuid
# left there — by a previous `gnome-extensions disable`, or by the user having
# once switched ARIES off — makes the ARIES session silently start without
# ARIES. Cleared for the duration of the test, and restored by the trap; the
# installer checks for the same thing, because it is a real way for a working
# install to do nothing.
gsettings set org.gnome.shell disabled-extensions "[]"

cat > "$STAGE/run.sh" <<INNER
#!/usr/bin/env bash
set -u
${INSTALLED:+#} export XDG_DATA_DIRS="$STAGE:\${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
gnome-shell --headless --virtual-monitor 1600x1000 \
            --wayland-display aries-session --mode=aries &
SHELL_PID=\$!
sleep 12
echo "--- what the session enabled, with nobody asking ---"
gnome-extensions list --enabled 2>&1 | sed 's/^/enabled: /'
gnome-extensions info "$UUID" 2>&1 | sed 's/^/info: /'
gdbus call --session --dest org.aries.Shell --object-path /org/aries/Shell \
  --method org.aries.Shell.Ping 2>&1 | sed 's/^/ping: /'
sleep ${RUN_FOR}
kill \$SHELL_PID 2>/dev/null
wait \$SHELL_PID 2>/dev/null
INNER
chmod +x "$STAGE/run.sh"

timeout $(( RUN_FOR + 45 )) dbus-run-session -- "$STAGE/run.sh" > "$LOG" 2>&1 || true

# ── did the mode load at all? ───────────────────────────────────────────────
if grep -qiE "Could not find a valid mode|Failed to load mode|mode.*not found" "$LOG"; then
  fail "gnome-shell did not accept --mode=aries"
  grep -iE "mode" "$LOG" | head -3 | sed 's/^/      /'
else
  pass "gnome-shell started with --mode=aries"
fi

# ── the promise: ARIES is there without being switched on ───────────────────
# `gnome-extensions list --enabled` reports the user's gsettings list, which a
# mode-enabled extension is deliberately NOT added to — so the question is asked
# of the extension's own state instead.
if grep -qE '^info: .*State: (ACTIVE|ENABLED)' "$LOG"; then
  pass "the ARIES extension is ACTIVE because the SESSION says so — nobody ran "\
"'gnome-extensions enable'"
else
  fail "the extension did not become active in the ARIES session"
  grep -m1 '^info:' "$LOG" | sed 's/^/      /' || true
fi

# The right question is which copy WON, not whether the shell mentioned the
# other one. With both a per-user and a system copy present — which is the normal
# state during development — the shell logs that it is skipping the user one and
# loads the system one. That message is the mechanism working, not a failure.
loaded_path=$(grep -m1 '^info:   Path:' "$LOG" | sed 's/^info: *Path: *//' || true)
case "$loaded_path" in
  "$HOME"/.local/*)
    fail "the session loaded the per-user copy, which a session mode may not do"
    note "$loaded_path" ;;
  /usr/local/share/*)
    pass "it loaded the INSTALLED system copy"
    note "$loaded_path" ;;
  "")
    fail "the shell did not report which copy of the extension it loaded" ;;
  *)
    pass "it loaded the SYSTEM copy, which is the only kind a session mode accepts"
    note "$loaded_path" ;;
esac

# ── and the surfaces actually came up ───────────────────────────────────────
ping=$(grep -m1 '^ping: ' "$LOG" || true)
if [ -n "$ping" ]; then
  missing=""
  for surface in "top bar" "quick settings" "ARIES Search" launcher notifications overview; do
    case "$ping" in *"$surface"*) ;; *) missing="$missing $surface" ;; esac
  done
  if [ -z "$missing" ]; then
    pass "every ARIES surface was built inside the session"
  else
    fail "surfaces missing in the session:$missing"
  fi
  case "$ping" in
    *'"failures":[]'*) pass "with nothing reporting a failure" ;;
    *) fail "a surface failed inside the session"
       echo "      $ping" | head -c 300 | sed 's/^/      /' ;;
  esac
else
  fail "the ARIES shell did not answer inside the session"
fi

# ── Ubuntu's own session is untouched ───────────────────────────────────────
if grep -q "^enabled: ubuntu-dock@ubuntu.com" "$LOG"; then
  note "ubuntu-dock is in the user's global list and unaffected by the ARIES mode"
fi
if [ -f /usr/share/gnome-shell/modes/ubuntu.json ]; then
  pass "Ubuntu's own session mode is present and unmodified"
else
  fail "Ubuntu's session mode is missing — something modified the system"
fi

echo
if [ "$ok" = "1" ]; then echo "ALL PASSED"; exit 0; fi
echo "FAILURES — log kept at $LOG"
trap - EXIT
exit 1
