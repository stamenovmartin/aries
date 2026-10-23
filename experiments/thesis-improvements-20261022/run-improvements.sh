#!/usr/bin/env bash
# R1b (confirmatory) and X1 (exploratory) in one measurement window, in a fixed order
# (docs/preregistration/R1b-improved-router-planner.md, X1-remedy-reruns.md). Like R1, H5 and H4b: the live
# aries.target is stopped for the whole window and always restarted; screen blanking is off (idle-delay 0 + an
# idle inhibitor) and restored. The service environment is captured for the H5/H4b runners before the stop.
#   run-improvements.sh [FROM]   resume: skip the first FROM-1 steps, whose outputs exist
set -u
cd "$HOME/aries-main"
T=experiments/thesis-improvements-20261022
B=experiments/thesis-r1b
PY=.venv/bin/python
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> $T/run-improvements.log; }
old=$(gsettings get org.gnome.desktop.session idle-delay)
finish() {
  systemctl --user start aries.target; log "aries.target start requested (exit $?)"
  gsettings set org.gnome.desktop.session idle-delay "${old#uint32 }"
  log "screen blanking restored: $(gsettings get org.gnome.desktop.session idle-delay); end"
}
trap finish EXIT
log "begin at $(git rev-parse HEAD); idle-delay was $old"
$PY $T/run_followup_rerun.py h5 --capture-env >> $T/run-improvements.log 2>&1 || { log "h5 capture-env failed"; exit 1; }
$PY $T/run_followup_rerun.py h4b --capture-env >> $T/run-improvements.log 2>&1 || { log "h4b capture-env failed"; exit 1; }
systemctl --user stop aries.target; log "aries.target stopped (exit $?)"
gsettings set org.gnome.desktop.session idle-delay 0
gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver \
  --method org.gnome.ScreenSaver.SetActive false >/dev/null; sleep 2
FROM=${1:-1}; N=0
step() {
  N=$((N+1)); if [ $N -lt $FROM ]; then log "skip $N (done) $*"; return; fi
  log "start $N $*"
  gnome-session-inhibit --inhibit idle --reason "ARIES R1b/X1 measurement" $PY "$@" >> $T/run-improvements.log 2>&1
  local rc=$?; log "exit $rc $N $*"; [ $rc -eq 0 ] || exit 1
}
# R1b, confirmatory
step $B/run_r1b.py frozen --set nl2bash-r1b
step $B/run_r1b.py frozen-planner --set nl2bash-r1b
step $B/run_r1b.py frozen --set clinc-r1b
step $B/run_r1b.py aries --config C1 --set nl2bash-r1b
step $B/run_r1b.py aries --config C1 --set clinc-r1b
step $B/run_r1b.py zeroshot --set nl2bash-r1b
step $B/run_r1b.py zeroshot --set clinc-r1b
step $B/run_r1b.py embedding --set nl2bash-r1b
step $B/run_r1b.py embedding --set clinc-r1b
step $B/run_r1b.py bm25 --set nl2bash-r1b
# X1, exploratory
for i in 1 2 3; do step $T/run_followup_rerun.py h4b --condition code-select --label r$i --go; done
for i in 1 2 3; do step $T/run_followup_rerun.py h5 --condition remedies --label r$i --go; done
step $T/run_followup_rerun.py h5 --condition consolidated --label r1 --go
# R1b, exploratory configurations
for c in C0 G S C3; do
  step $B/run_r1b.py aries --config $c --set nl2bash-r1b
  step $B/run_r1b.py aries --config $c --set clinc-r1b
done
log "all steps done"
