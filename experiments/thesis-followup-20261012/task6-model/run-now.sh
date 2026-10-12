#!/usr/bin/env bash
# Task 6 started early (author instruction 2026-10-12, instead of the 01:00 timer). Same procedure:
# overnight.sh unchanged (stops aries.target, unloads qwen2.5:7b, measures, always restarts ARIES).
# Added only: no screen blanking for the duration (idle-delay 0 + idle inhibitor), restored on exit.
set -u
T="$HOME/aries/experiments/thesis-followup-20261012/task6-model"
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$T/overnight.log"; }
old=$(gsettings get org.gnome.desktop.session idle-delay)
restore() { gsettings set org.gnome.desktop.session idle-delay "${old#uint32 }"; log "screen blanking restored: idle-delay $(gsettings get org.gnome.desktop.session idle-delay)"; }
trap restore EXIT
gsettings set org.gnome.desktop.session idle-delay 0
log "started early (not by timer); screen blanking off: idle-delay was $old, now $(gsettings get org.gnome.desktop.session idle-delay); idle inhibitor held"
gnome-session-inhibit --inhibit idle --reason "ARIES Task 6 measurement" /bin/bash "$T/overnight.sh"
log "overnight.sh exit $?"
