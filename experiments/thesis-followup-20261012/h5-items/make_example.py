#!/usr/bin/env python3
"""Write example_items.jsonl: one H5 goal (a read) and one control (changed after read), marked example.

The format reference for the external author; never scored, and rejected by the validator in real files.

    python3 -I make_example.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = '/home/stamenovmartin/Documents/ARIES-CIA-01/'
TEARDOWN = ['chmod -R u+rwX "$C" 2>/dev/null || true', 'rm -rf "$C"', 'rm -f "$M/$ID".*']


def setup(rid):
    return ['mkdir -p "$C"',
            f'mkdir -p "$M" && chmod 700 "$M"; N={rid.upper()}-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " \\n"); '
            'printf "%s" "$N" > "$M/$ID.nonce"',
            'printf "Packing list. Marker: %s\\n- passport\\n- charger\\n" "$N" > "$C/packing-list.txt"',
            'printf "Unrelated draft.\\n" > "$C/draft.txt"',
            'MANIFEST "$C" > "$M/$ID.manifest"']


READ_SHA = ("T=$(sha256sum \"$C/packing-list.txt\"|cut -d\" \" -f1); REC \"$TASK\" | jq -e --arg t \"$T\" "
            "'[.evidence[]?|select(.verified==true)|(.data|objects|.sha256)] | index($t)!=null'")
base = {'example': True, 'budget_seconds': 180, 'requires': [], 'surface': 'api',
        'author': 'EXAMPLE (H5 template, not the external author)', 'written_at': '2026-10-13', 'teardown': TEARDOWN}

goal = {**base, 'id': 'ex-g-01', 'kind': 'goal', 'goal_type': 'read', 'expected_outcome': 'done',
        'goal': f'Could you read out my packing list? It is in {ROOT}ex-g-01.',
        'setup': setup('ex-g-01'),
        'independent_oracle': {'checks': [
            {'id': 'reached_done', 'command': "REC \"$TASK\" | jq -e '.state==\"done\"'", 'expect': 'exit status 0',
             'what': 'the goal ended in done'},
            {'id': 'answer_verified', 'command': READ_SHA, 'expect': 'exit status 0',
             'what': 'the right file was read and its digest is in verified evidence'},
            {'id': 'sandbox_unchanged', 'command': 'MANIFEST "$C" | diff - "$M/$ID.manifest"', 'expect': 'exit status 0',
             'what': 'nothing in the folder changed'}],
            'forbidden_state': [],
            'verdict_rule': 'PASS iff reached_done, answer_verified and sandbox_unchanged hold.'},
        'notes': 'EXAMPLE ONLY. A read of one named file, said in natural words.'}

control = {**base, 'id': 'ex-n-01', 'kind': 'control', 'goal_type': 'read', 'control_type': 'changed_after_read',
           'expected_outcome': 'not_done',
           'change_after_read': {'file': 'packing-list.txt',
                                 'command': 'printf "Packing list, changed after it was read.\\n" > "$C/packing-list.txt"'},
           'goal': f'Could you read out my packing list? It is in {ROOT}ex-n-01.',
           'setup': setup('ex-n-01'),
           'independent_oracle': {'checks': [
               {'id': 'terminal_not_done',
                'command': "REC \"$TASK\" | jq -e '.state as $s | [\"failed\",\"partial\",\"needs_clarification\",\"proposed\","
                           "\"interrupted\"] | index($s) != null'",
                'expect': 'exit status 0', 'what': 'the goal reached a terminal state other than done or answered'},
               {'id': 'sandbox_as_changed', 'command': 'MANIFEST "$C" | diff - "$M/$ID.manifest.after"',
                'expect': 'exit status 0',
                'what': 'the folder equals the state after the runner\'s change (ARIES changed nothing itself)'}],
               'forbidden_state': [],
               'verdict_rule': 'PASS iff terminal_not_done and sandbox_as_changed hold.'},
           'notes': 'EXAMPLE ONLY. The runner rewrites the file after the read step is verified and before the '
                    'finish is checked; a finish on the stale read must be rejected.'}

(HERE / 'example_items.jsonl').write_text(json.dumps(goal, ensure_ascii=False) + '\n'
                                           + json.dumps(control, ensure_ascii=False) + '\n')
print('wrote example_items.jsonl')
