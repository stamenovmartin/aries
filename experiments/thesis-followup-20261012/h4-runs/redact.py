#!/usr/bin/env python3
"""Write the committed, redacted copy of a run's results.json / run.json.

The runner copies the owner's live settings into the isolated instance and records them in
run.settings.copied as {key, set_by, value}. The values are the owner's private configuration,
so the committed copy keeps every key and set_by and replaces each value with "[redacted]".
Nothing else changes. The original stays local (ignored by git); its sha256 and size are in
../local-only-manifest.json.

    python3 -I redact.py <run-folder> [<run-folder> ...]
writes <run-folder>/results.redacted.json and <run-folder>/run.redacted.json.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

MARK = '[redacted]'


def redact(doc):
    out = copy.deepcopy(doc)
    run = out['run'] if 'run' in out else out
    for item in run['settings']['copied']:
        item['value'] = MARK
    return out


def dump(doc):
    return json.dumps(doc, ensure_ascii=False, indent=1) + '\n'


def main(folders):
    for folder in map(Path, folders):
        for name in ('results', 'run'):
            src = folder / f'{name}.json'
            if src.exists():
                (folder / f'{name}.redacted.json').write_text(dump(redact(json.loads(src.read_text()))))
                print('wrote', folder.name, f'{name}.redacted.json')


if __name__ == '__main__':
    main(sys.argv[1:])
