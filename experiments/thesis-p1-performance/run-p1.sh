#!/usr/bin/env bash
# P1 (docs/preregistration/P1-performance.md) in one measurement window, in a fixed order. The resource sampler
# runs for the whole window. Part 1 uses the installed system as it runs (aries.target active): an idle
# baseline, then the 90-goal agent suite three times. Part 2 stops aries.target (as in R1, R1b and M2) and runs
# the decision workload with each of the four models. aries.target is always restarted; screen blanking is off
# and restored.
set -u
cd "$HOME/aries-main"
T=experiments/thesis-p1-performance
PY=.venv/bin/python
export PYTHONPATH="$PWD/vendor/agentic-core:$PWD/vendor:$PWD"
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> $T/run-p1.log; }
# Added after the first P1 window (2026-10-23), which ran while the session was locked: idle-delay 0 does not
# unlock a session that is already locked, and the desktop goals then measure the lock. Refuse to start instead.
if gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver \
     --method org.gnome.ScreenSaver.GetActive 2>/dev/null | grep -q true; then
  echo "REFUSED: the desktop session is locked; unlock it and run again" >&2; exit 2
fi
old=$(gsettings get org.gnome.desktop.session idle-delay)
mkdir -p $T/raw
python3 $T/sample.py $T/raw/resources-$(date -u +%Y%m%dT%H%M%SZ).jsonl & SAMPLER=$!
finish() {
  systemctl --user start aries.target; log "aries.target start requested (exit $?)"
  gsettings set org.gnome.desktop.session idle-delay "${old#uint32 }"
  kill $SAMPLER 2>/dev/null; wait $SAMPLER 2>/dev/null
  log "screen blanking restored: $(gsettings get org.gnome.desktop.session idle-delay); sampler stopped; end"
}
trap finish EXIT
log "begin at $(git rev-parse HEAD); idle-delay was $old; sampler pid $SAMPLER"
gsettings set org.gnome.desktop.session idle-delay 0
gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver \
  --method org.gnome.ScreenSaver.SetActive false >/dev/null; sleep 2
inhibit() { gnome-session-inhibit --inhibit idle --reason "ARIES P1 measurement" "$@"; }
# Part 1: the installed system
$PY $T/run_p1.py phase live-idle start; sleep 60; $PY $T/run_p1.py phase live-idle end
for r in 1 2 3; do
  log "start agent suite run $r"
  $PY $T/run_p1.py phase suite-run-$r start
  inhibit $PY eval/agent_suite/run.py --label p1-run$r --flags on --out $T/suite/p1-run$r >> $T/run-p1.log 2>&1
  rc=$?; $PY $T/run_p1.py phase suite-run-$r end; log "exit $rc agent suite run $r"
done
# Part 2: the decision pipeline with each model, the live system stopped
systemctl --user stop aries.target; log "aries.target stopped (exit $?)"; sleep 5
for m in qwen2.5:1.5b qwen2.5:7b llama3.1:8b qwen2.5:14b; do
  log "start decision $m"
  inhibit $PY $T/run_p1.py decision --model $m >> $T/run-p1.log 2>&1
  rc=$?; log "exit $rc decision $m"; [ $rc -eq 0 ] || exit 1
done
log "all steps done"
