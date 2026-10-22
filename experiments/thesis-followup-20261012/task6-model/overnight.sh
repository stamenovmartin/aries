#!/usr/bin/env bash
# Task 6 overnight run: live ARIES stopped for the whole measurement, always restarted.
set -u
cd "$HOME/aries"
T=experiments/thesis-followup-20261012/task6-model
C=$T/run-conditions.json
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> $T/overnight.log; }
restart() { systemctl --user start aries.target; log "aries.target start requested (exit $?)"; \
            python3 -I - "$C" "$(systemctl --user is-active aries-core.service)" <<'PY'
import json,sys,datetime
p=sys.argv[1]; d=json.load(open(p)); d['live_restarted_at']=datetime.datetime.now(datetime.timezone.utc).isoformat(); d['aries_core_after']=sys.argv[2]
json.dump(d,open(p,'w'),indent=1)
PY
}
trap restart EXIT
log "begin"
before=$(systemctl --user is-active aries-core.service)
systemctl --user stop aries.target; log "aries.target stopped (exit $?)"
curl -s -o /dev/null http://127.0.0.1:11434/api/generate -d '{"model":"qwen2.5:7b","keep_alive":0}'
sleep 5
python3 -I - "$C" "$before" "$(systemctl --user is-active aries-core.service)" "$(curl -s http://127.0.0.1:11434/api/ps)" <<'PY'
import json,sys,datetime
json.dump({'live_service':'aries.target stopped for the whole measurement (author instruction 2026-10-12)',
           'aries_core_before':sys.argv[2],'aries_core_during':sys.argv[3],'ollama_loaded_models_at_start':json.loads(sys.argv[4] or '{}'),
           'live_stopped_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},open(sys.argv[1],'w'),indent=1)
PY
.venv/bin/python $T/run_router_second_model.py --run > $T/run.log 2>&1; log "run exit $?"
.venv/bin/python $T/analyze_second_model.py > $T/analysis.log 2>&1; log "analysis exit $?"
log "end"
