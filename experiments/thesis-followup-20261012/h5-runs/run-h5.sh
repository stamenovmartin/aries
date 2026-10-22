#!/usr/bin/env bash
# H5 measurement (docs/preregistration/H5-completion-paraphrase.md, Procedure): 3 runs per condition in the
# order treatment, control, treatment, control, treatment, control. Like Task 6 and H6: the live aries.target
# is stopped for the whole measurement and always restarted; screen blanking is off (idle-delay 0 + an idle
# inhibitor) and restored. The live service's environment is captured once, before it is stopped.
set -u
cd "$HOME/aries"
T=experiments/thesis-followup-20261012/h5-runs
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> $T/run-h5.log; }
old=$(gsettings get org.gnome.desktop.session idle-delay)
finish() {
  systemctl --user start aries.target; log "aries.target start requested (exit $?)"
  gsettings set org.gnome.desktop.session idle-delay "${old#uint32 }"
  log "screen blanking restored: $(gsettings get org.gnome.desktop.session idle-delay); end"
}
trap finish EXIT
log "begin; idle-delay was $old"
.venv/bin/python $T/run_h5.py --capture-env >> $T/run-h5.log 2>&1 || { log "capture-env failed"; exit 1; }
systemctl --user stop aries.target; log "aries.target stopped (exit $?)"
gsettings set org.gnome.desktop.session idle-delay 0
# The screen may already be blanked (not locked) when the script starts; wake it so the runner's check passes
# (H5 Amendment 4 / H4b Amendment 3, after the first H5 pilot was refused for this).
gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver \
  --method org.gnome.ScreenSaver.SetActive false >/dev/null; sleep 2
log "screensaver active after wake: $(gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver --method org.gnome.ScreenSaver.GetActive)"
i=0
for cond in treatment control treatment control treatment control; do
  i=$((i+1))
  log "run r$i $cond start"
  gnome-session-inhibit --inhibit idle --reason "ARIES H5 measurement" \
    .venv/bin/python $T/run_h5.py --condition $cond --label r$i --go >> $T/run-h5.log 2>&1
  code=$?; log "run r$i $cond exit $code"
  [ $code -eq 0 ] || { log "stopping: a run did not complete"; exit 1; }
done
