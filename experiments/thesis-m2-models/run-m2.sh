#!/usr/bin/env bash
# M2 (docs/preregistration/M2-local-models.md) in one measurement window, in a fixed order. As in R1 and R1b:
# the live aries.target is stopped for the whole window and always restarted; screen blanking is off and
# restored.   run-m2.sh [FROM]   resume: skip the first FROM-1 steps, whose outputs exist
set -u
cd "$HOME/aries-main"
T=experiments/thesis-m2-models
PY=.venv/bin/python
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> $T/run-m2.log; }
old=$(gsettings get org.gnome.desktop.session idle-delay)
finish() {
  systemctl --user start aries.target; log "aries.target start requested (exit $?)"
  gsettings set org.gnome.desktop.session idle-delay "${old#uint32 }"
  log "screen blanking restored: $(gsettings get org.gnome.desktop.session idle-delay); end"
}
trap finish EXIT
log "begin at $(git rev-parse HEAD); idle-delay was $old"
systemctl --user stop aries.target; log "aries.target stopped (exit $?)"
gsettings set org.gnome.desktop.session idle-delay 0
FROM=${1:-1}; N=0
step() {
  N=$((N+1)); if [ $N -lt $FROM ]; then log "skip $N (done) $*"; return; fi
  log "start $N $*"
  gnome-session-inhibit --inhibit idle --reason "ARIES M2 measurement" $PY $T/run_m2.py "$@" >> $T/run-m2.log 2>&1
  local rc=$?; log "exit $rc $N $*"; [ $rc -eq 0 ] || exit 1
}
for m in llama3.1:8b qwen2.5:1.5b qwen2.5:14b; do
  step frozen --model $m --set nl2bash-r1b
  step frozen-planner --model $m --set nl2bash-r1b
  step frozen --model $m --set clinc-r1b
  step aries --model $m --set nl2bash-r1b
  step aries --model $m --set clinc-r1b
  step zeroshot --model $m --set nl2bash-r1b
  step zeroshot --model $m --set clinc-r1b
done
log "all steps done"
