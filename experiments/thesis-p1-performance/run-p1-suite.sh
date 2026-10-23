#!/usr/bin/env bash
# P1 Amendment 1: the agent suite three times against the installed service, with the sampler on.
#   run-p1-suite.sh LABEL [FLAG=VALUE ...]   flags go into ~/aries/var/flags.env for the series, then removed
set -u
cd "$HOME/aries-main"
T=experiments/thesis-p1-performance
PY=.venv/bin/python
export PYTHONPATH="$PWD/vendor/agentic-core:$PWD/vendor:$PWD"
LABEL=$1; shift
FLAGFILE="$HOME/aries/var/flags.env"
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> $T/run-p1.log; }
[ -e "$FLAGFILE" ] && { echo "REFUSED: $FLAGFILE exists; this script will not overwrite it" >&2; exit 2; }
gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver \
  --method org.gnome.ScreenSaver.SetActive false >/dev/null; sleep 2
if gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver \
     --method org.gnome.ScreenSaver.GetActive 2>/dev/null | grep -q true; then
  echo "REFUSED: the screen is blanked or locked" >&2; exit 2
fi
[ "$(gsettings get org.gnome.desktop.session idle-delay)" = "uint32 0" ] || { echo "REFUSED: idle-delay is not 0" >&2; exit 2; }
systemctl --user is-active --quiet aries.target || { echo "REFUSED: aries.target is not active" >&2; exit 2; }
mkdir -p $T/raw
python3 $T/sample.py $T/raw/resources-$(date -u +%Y%m%dT%H%M%SZ)-$LABEL.jsonl & SAMPLER=$!
finish() {
  rm -f "$FLAGFILE"; log "$LABEL: flag file removed"
  kill $SAMPLER 2>/dev/null; wait $SAMPLER 2>/dev/null; log "$LABEL: sampler stopped; end"
}
trap finish EXIT
if [ $# -gt 0 ]; then printf '%s\n' "# P1 $LABEL, written by run-p1-suite.sh; removed at the end" "$@" > "$FLAGFILE"; sleep 5; fi
log "$LABEL begin at $(git rev-parse HEAD); flags: ${*:-none}"
$PY $T/run_p1.py phase $LABEL-idle start; sleep 30; $PY $T/run_p1.py phase $LABEL-idle end
for r in 1 2 3; do
  $PY $T/run_p1.py phase $LABEL-run-$r start
  gnome-session-inhibit --inhibit idle --reason "ARIES P1 $LABEL" \
    $PY eval/agent_suite/run.py --label $LABEL-run$r --flags on --out $T/suite/$LABEL-run$r >> $T/run-p1.log 2>&1
  rc=$?; $PY $T/run_p1.py phase $LABEL-run-$r end; log "exit $rc $LABEL run $r"
done
log "$LABEL all runs done"
