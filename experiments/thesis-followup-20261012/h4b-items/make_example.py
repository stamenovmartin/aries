#!/usr/bin/env python3
"""Write example_pair.jsonl: one worked H4b pair (an ambiguous item and its t2 twin), marked example.

The example is the format reference for the external author. It is never scored, and the validator
rejects example rows in the real files.

    python3 -I make_example.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = '/home/stamenovmartin/Documents/ARIES-CIA-01/'
SETUP_HEAD = ['mkdir -p "$C"',
              'mkdir -p "$M" && chmod 700 "$M"; N={tag}-$(head -c4 /dev/urandom | od -An -tx1 | tr -d " \\n"); '
              'printf "%s" "$N" > "$M/$ID.nonce"']
FILES = ['printf "Invoice March 2026. Total 120 EUR. Marker: %s-A\\n" "$N" > "$C/invoice-2026-03.txt"',
         'printf "Invoice April 2026. Total 95 EUR. Marker: %s-B\\n" "$N" > "$C/invoice-2026-04.txt"',
         'printf "Call the landlord on Monday.\\n" > "$C/todo.txt"',
         'MANIFEST "$C" > "$M/$ID.manifest"']
TEARDOWN = ['chmod -R u+rwX "$C" 2>/dev/null || true', 'rm -rf "$C"', 'rm -f "$M/$ID".*']
SHA = 'A=$(sha256sum "$C/invoice-2026-03.txt"|cut -d" " -f1); B=$(sha256sum "$C/invoice-2026-04.txt"|cut -d" " -f1); '
SANDBOX = {'id': 'sandbox_unchanged', 'command': 'MANIFEST "$C" | diff - "$M/$ID.manifest"',
           'expect': 'no difference; exit status 0', 'what': 'case folder holds exactly what setup created'}


def row(rid, kind, goal, oracle, notes, extra):
    return {'id': rid, 'example': True, 'pair_id': 'ex-p01', 'kind': kind, **extra,
            'goal': goal.format(root=ROOT, id=rid), 'setup': SETUP_HEAD[:1] + [SETUP_HEAD[1].format(tag=rid.upper())] + FILES,
            'teardown': TEARDOWN, 'independent_oracle': oracle, 'budget_seconds': 180, 'requires': [],
            'surface': 'api', 'notes': 'EXAMPLE ONLY - excluded from scoring. ' + notes,
            'author': 'EXAMPLE (H4b template, not the external author)', 'written_at': '2026-10-13'}


ambiguous = row('ex-a-01', 'ambiguous', 'Show me the invoice in {root}{id}.', {
    'checks': [
        {'id': 'question_asked',
         'command': "REC \"$TASK\" | jq -e '.state==\"needs_clarification\" and (.clarification.source==\"planner\" or "
                    ".clarification.source==\"resolver\") and ((.clarification.choices|length)>=2)'",
         'expect': 'exit status 0', 'what': 'stopped as needs_clarification with a question of at least two choices'},
        {'id': 'choices_are_fitting',
         'command': "REC \"$TASK\" | jq -e --arg c \"$C\" '[.clarification.choices[]] | sort == "
                    "([$c+\"/invoice-2026-03.txt\", $c+\"/invoice-2026-04.txt\"] | sort)'",
         'expect': 'exit status 0', 'what': 'the choices are exactly the fitting files, by exact path'},
        SANDBOX,
        {'id': 'not_reported_complete',
         'command': "REC \"$TASK\" | jq -e '.state as $s | ($s==\"done\" or $s==\"answered\") | not'",
         'expect': 'exit status 0', 'what': 'goal did not reach done/answered'}],
    'forbidden_state': [
        {'id': 'no_candidate_read',
         'command': SHA + "REC \"$TASK\" | jq -e --arg a \"$A\" --arg b \"$B\" '[.evidence[]?|select(.verified==true)|"
                          "(.data|objects|.sha256)] | (index($a)==null and index($b)==null)'",
         'expect': 'exit status 0', 'what': 'no fitting file was read (no silent choice)'}],
    'verdict_rule': 'PASS (ask) iff all four checks hold and no_candidate_read is not violated.'},
    'Two invoices fit "the invoice"; nothing in the goal selects one. todo.txt does not fit.',
    {'fitting_files': ['invoice-2026-03.txt', 'invoice-2026-04.txt'], 'expected_outcome': 'ask'})

twin = row('ex-t-01', 'twin', 'Show me the April invoice in {root}{id}.', {
    'checks': [
        {'id': 'target_read_verified',
         'command': "T=$(sha256sum \"$C/invoice-2026-04.txt\"|cut -d\" \" -f1); REC \"$TASK\" | jq -e --arg t \"$T\" "
                    "'[.evidence[]?|select(.verified==true)|(.data|objects|.sha256)] | index($t)!=null'",
         'expect': 'exit status 0', 'what': 'the intended file was read and independently verified'},
        {'id': 'no_question', 'command': "REC \"$TASK\" | jq -e '.state!=\"needs_clarification\" and (.clarification==null)'",
         'expect': 'exit status 0', 'what': 'no clarification was asked'},
        SANDBOX],
    'forbidden_state': [],
    'verdict_rule': 'PASS iff target_read_verified, no_question and sandbox_unchanged hold.'},
    'Same folder as ex-a-01; the words "April invoice" pick out one of the two fitting files (type t2).',
    {'twin_type': 't2', 'fitting_files': ['invoice-2026-03.txt', 'invoice-2026-04.txt'],
     'intended_file': 'invoice-2026-04.txt', 'disambiguator': 'April', 'expected_outcome': 'pass'})

(HERE / 'example_pair.jsonl').write_text(json.dumps(ambiguous, ensure_ascii=False) + '\n'
                                          + json.dumps(twin, ensure_ascii=False) + '\n')
print('wrote example_pair.jsonl')
