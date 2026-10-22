#!/usr/bin/env python3
"""R1 labels (Labels section): two independent LLM labelers in fresh, isolated sessions.

    label.py nl2bash|clinc A|B        ->  labels/<set>-<labeler>.json (ids and labels only)

A = Claude Code CLI (`claude -p`, no tools, no session persistence), B = Codex CLI (`codex exec`, ephemeral,
read-only sandbox); both run in an empty directory and get only the instruction, the 16 labels and the items.
Raw transcripts (which contain the request texts) stay in ~/data-ext/r1/transcripts/. A batch whose
transcript shows a tool call, or whose answer is not exactly one valid label per item, is discarded and
relabelled once in a new session; both events are recorded in the output."""
import json
import random
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from common import CAPABILITIES, DATA, HERE, LABELS, LOCAL, OOS, check_data, jsonl

BATCH = 50
NO_TOOLS = ['Bash', 'Read', 'Edit', 'Write', 'Glob', 'Grep', 'WebFetch', 'WebSearch', 'NotebookEdit', 'Agent',
            'Task', 'TodoWrite']
LABEL_LIST = '\n'.join(f'- {k}: {v}' for k, v in CAPABILITIES.items()) + \
    f'\n- {OOS}: the listed capabilities cannot fulfil the request completely'
INSTRUCTION = {
    'nl2bash': ('An assistant can act only through the capabilities listed. For each request, give the one '
                'capability the assistant would use as the first step to fulfil the request completely, using only '
                'listed capabilities. If the listed capabilities cannot fulfil the request completely (for example '
                'it needs to delete, modify, compress or transform files, run arbitrary commands, or change system '
                f'settings), answer {OOS}.'),
    'clinc': ('An assistant can act only through the capabilities listed. Each item is a user intent, shown as its '
              'name and three example utterances. For each intent, give the one capability the assistant would use '
              'as the first step to fulfil such requests completely, using only listed capabilities. If the listed '
              'capabilities cannot fulfil such requests completely (for example they need to delete, modify, '
              f'compress or transform files, run arbitrary commands, or change system settings), answer {OOS}.'),
}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def items(name):
    if name == 'nl2bash':
        return [{'id': r['id'], 'request': r['text']} for r in jsonl(LOCAL / 'nl2bash_sample.jsonl')]
    data = json.loads((DATA / 'clinc150/data_full.json').read_text())
    ex = {}
    for text, intent in data['train']:
        ex.setdefault(intent, [])
        if len(ex[intent]) < 3:
            ex[intent].append(text)
    return [{'id': intent, 'intent': intent, 'examples': ex[intent]} for intent in sorted(ex)]


def prompt(name, batch):
    lines = '\n'.join(json.dumps(b, ensure_ascii=False) for b in batch)
    return (f'{INSTRUCTION[name]}\n\nCapabilities:\n{LABEL_LIST}\n\nItems (one JSON object per line):\n{lines}\n\n'
            'Answer with only a JSON array, one object per item in the same order: '
            '[{"id": "<id>", "label": "<one of the labels above>"}]. Use the label names exactly as written. '
            'Do not use any tools, do not read any files, do not explain.')


def call(labeler, text, workdir):
    if labeler == 'A':
        out = subprocess.run(['claude', '-p', '--no-session-persistence', '--output-format', 'json',
                              '--disallowed-tools', *NO_TOOLS], input=text, capture_output=True, text=True,
                             cwd=workdir, timeout=900)
        raw = json.loads(out.stdout)
        tool_use = bool(raw.get('permission_denials')) or raw.get('num_turns', 1) != 1
        model = ','.join(raw.get('modelUsage', {}).keys())
        return raw.get('result', ''), tool_use, model, out.stdout
    last = Path(workdir) / 'last.txt'
    out = subprocess.run(['codex', 'exec', '--skip-git-repo-check', '--ephemeral', '--sandbox', 'read-only',
                          '-C', workdir, '--json', '-o', str(last), text], stdin=subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=900)
    events = [json.loads(l) for l in out.stdout.splitlines() if l.startswith('{')]
    kinds = {e.get('item', {}).get('type') for e in events if e.get('type', '').startswith('item.')}
    tool_use = bool(kinds - {'agent_message', 'reasoning', None})
    answer = last.read_text() if last.exists() else ''
    return answer, tool_use, 'codex-cli default model (see transcript)', out.stdout


def parse(answer, batch):
    s = answer.strip()
    s = s[s.find('['):s.rfind(']') + 1]
    got = json.loads(s)
    ids = [b['id'] for b in batch]
    if [g['id'] for g in got] != ids or any(g['label'] not in LABELS for g in got):
        raise ValueError('ids or labels do not match')
    return {g['id']: g['label'] for g in got}


def main(name, labeler):
    check_data()
    dest = HERE / 'labels' / f'{name}-{labeler}.json'
    if dest.exists():
        raise SystemExit(f'REFUSED: {dest} exists')
    pool = items(name)
    random.Random({'nl2bash': 20261025, 'clinc': 20261026}[name]).shuffle(pool)
    tdir = LOCAL / 'transcripts' / f'{name}-{labeler}'
    tdir.mkdir(parents=True, exist_ok=True)
    labels, events, models = {}, [], set()
    for bi in range(0, len(pool), BATCH):
        batch = pool[bi:bi + BATCH]
        for attempt in (1, 2):
            with tempfile.TemporaryDirectory(prefix='r1-label-') as wd:
                t0 = time.monotonic()
                try:
                    answer, tool_use, model, raw = call(labeler, prompt(name, batch), wd)
                except Exception as exc:
                    answer, tool_use, model, raw = '', False, '', repr(exc)
                (tdir / f'batch{bi // BATCH:02d}-try{attempt}.txt').write_text(raw)
                models.add(model)
                try:
                    got = None if tool_use else parse(answer, batch)
                except Exception as exc:
                    got = None
                    events.append({'batch': bi // BATCH, 'attempt': attempt, 'discarded': 'invalid answer: ' + str(exc)[:200]})
                if tool_use:
                    events.append({'batch': bi // BATCH, 'attempt': attempt, 'discarded': 'tool call in transcript'})
                if got:
                    labels.update(got)
                    print(f'{stamp()} {name}-{labeler} batch {bi // BATCH} ok ({time.monotonic() - t0:.0f}s)', flush=True)
                    break
        else:
            events.append({'batch': bi // BATCH, 'unlabelled': [b['id'] for b in batch]})
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps({'set': name, 'labeler': labeler, 'finished_at': stamp(), 'models': sorted(models),
                                'n': len(pool), 'labelled': len(labels), 'events': events,
                                'labels': dict(sorted(labels.items()))}, indent=1) + '\n')
    print(json.dumps({'labelled': len(labels), 'of': len(pool), 'events': events}))


if __name__ == '__main__':
    main(*sys.argv[1:3])
