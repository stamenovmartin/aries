#!/usr/bin/env bash
# R1 runs in a fixed order (docs/preregistration/R1-real-data-benchmarks.md). Like H6: the live aries.target is
# stopped for the whole run and always restarted; screen blanking is off and restored. Run from ~/aries.
set -u
cd "$HOME/aries"
T=experiments/thesis-r1-real-data
PY=.venv/bin/python
log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> $T/run-r1.log; }
old=$(gsettings get org.gnome.desktop.session idle-delay)
finish() {
  systemctl --user start aries.target; log "aries.target start requested (exit $?)"
  gsettings set org.gnome.desktop.session idle-delay "${old#uint32 }"; log "end"
}
trap finish EXIT
log "begin at $(git rev-parse HEAD)"
systemctl --user stop aries.target; log "aries.target stopped (exit $?)"
gsettings set org.gnome.desktop.session idle-delay 0
step() { log "start $*"; $PY $T/run_r1.py "$@" >> $T/run-r1.log 2>&1; c=$?; log "exit $c $*"; [ $c -eq 0 ] || exit 1; }
step bm25 --set nl2bash
step embedding --set nl2bash
step embedding --set clinc-val
step embedding --set clinc
step router --model qwen2.5:7b --arm A1 --set nl2bash-test
step planner --model qwen2.5:7b --set nl2bash-test --router-file $T/raw/router-qwen2_5_7b-A1-nl2bash-test.jsonl
step router --model qwen2.5:7b --arm A1 --set clinc
step router --model qwen2.5:7b --arm A0 --set clinc
step zeroshot --set nl2bash-test
step zeroshot --set clinc
step router --model llama3.1:8b --arm A1 --set nl2bash-test
step planner --model llama3.1:8b --set nl2bash-test --router-file $T/raw/router-llama3_1_8b-A1-nl2bash-test.jsonl
step router --model llama3.1:8b --arm A1 --set clinc
log "all stages done"
