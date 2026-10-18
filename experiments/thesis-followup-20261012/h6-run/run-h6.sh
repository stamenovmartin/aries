#!/usr/bin/env bash
# H6 measurement (docs/preregistration/H6-abstention-replication.md, Procedure), modelled on Task 6's run-now.sh
# and overnight.sh: live ARIES stopped for the whole run and always restarted; screen blanking off
# (idle-delay 0 + idle inhibitor) and restored; Ollama version and qwen2.5:7b digest recorded before and after.
set -u
cd "$HOME/aries"
T=experiments/thesis-followup-20261012/h6-run
C=$T/run-conditions.json
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> $T/run-h6.log; }
ident() { curl -s http://127.0.0.1:11434/api/version | python3 -I -c "import json,sys;print(json.load(sys.stdin)['version'])"; }
digest() { curl -s http://127.0.0.1:11434/api/tags | python3 -I -c "import json,sys;print(next(m['digest'] for m in json.load(sys.stdin)['models'] if m['name']=='qwen2.5:7b'))"; }
cond() { python3 -I - "$C" "$@" <<'PY'
import json,sys,os
p=sys.argv[1]; d=json.load(open(p)) if os.path.exists(p) else {}
for kv in sys.argv[2:]:
    k,v=kv.split('=',1); d[k]=v
json.dump(d,open(p,'w'),indent=1)
PY
}
old=$(gsettings get org.gnome.desktop.session idle-delay)
finish() {
  systemctl --user start aries.target; log "aries.target start requested (exit $?)"
  gsettings set org.gnome.desktop.session idle-delay "${old#uint32 }"
  cond "live_restarted_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" "aries_core_after=$(systemctl --user is-active aries-core.service)" \
       "idle_delay_restored=$(gsettings get org.gnome.desktop.session idle-delay)"
  log "screen blanking restored: $(gsettings get org.gnome.desktop.session idle-delay); end"
}
trap finish EXIT
log "begin"
cond "aries_core_before=$(systemctl --user is-active aries-core.service)" "idle_delay_before=$old" \
     "ollama_version_before=$(ident)" "model_digest_before=$(digest)"
systemctl --user stop aries.target; log "aries.target stopped (exit $?)"
gsettings set org.gnome.desktop.session idle-delay 0
cond "live_service=aries.target stopped for the whole measurement" "aries_core_during=$(systemctl --user is-active aries-core.service)" \
     "live_stopped_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" "idle_delay_during=$(gsettings get org.gnome.desktop.session idle-delay)" \
     "ollama_loaded_at_start=$(curl -s http://127.0.0.1:11434/api/ps | tr -d '\n')"
gnome-session-inhibit --inhibit idle --reason "ARIES H6 measurement" \
  .venv/bin/python $T/run_router_h6.py --run > $T/run.log 2>&1; log "run exit $?"
cond "ollama_version_after=$(ident)" "model_digest_after=$(digest)" "run_finished_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
.venv/bin/python $T/analyze_h6.py > $T/analysis.log 2>&1; log "analysis exit $?"
