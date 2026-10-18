#!/usr/bin/env bash
# H5 pilot on the two example items only (h5-items/example_items.jsonl, never scored): one treatment run and one
# control run, under the conditions of run-h5.sh (live aries.target stopped and always restarted, screen blanking
# off and restored, service environment captured first). Its only use is the duration estimate for the full run.
set -u
cd "$HOME/aries"
T=experiments/thesis-followup-20261012/h5-runs
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> $T/pilot-h5.log; }
old=$(gsettings get org.gnome.desktop.session idle-delay)
finish() {
  systemctl --user start aries.target; log "aries.target start requested (exit $?)"
  gsettings set org.gnome.desktop.session idle-delay "${old#uint32 }"
  log "screen blanking restored: $(gsettings get org.gnome.desktop.session idle-delay); end"
}
trap finish EXIT
log "begin; idle-delay was $old"
.venv/bin/python $T/run_h5.py --capture-env >> $T/pilot-h5.log 2>&1 || { log "capture-env failed"; exit 1; }
systemctl --user stop aries.target; log "aries.target stopped (exit $?)"
gsettings set org.gnome.desktop.session idle-delay 0
for cond in treatment control; do
  log "pilot $cond start"
  gnome-session-inhibit --inhibit idle --reason "ARIES H5 pilot" \
    .venv/bin/python $T/run_h5.py --condition $cond --label pilot --sets example --go >> $T/pilot-h5.log 2>&1
  log "pilot $cond exit $?"
done
