#!/usr/bin/env python3
"""Record the SHA-256 and size of every measurement file that is kept local and never committed.

Writes local-only-manifest.json next to this file. Paths are relative to the repository root.
Three groups:
- untracked_after_push: files that were committed and pushed on thesis-followup before the author's
  rule of 2026-10-13 (databases, flag files, a server log, runtime state); they are removed from
  the index from the next commit on, stay in the pushed history, and are kept on disk.
- h4_runs_local: the databases, flag files, server logs, runtime folders and the unredacted
  results.json / run.json of the H4 smoke and development runs (committed as *.redacted.json).
- thesis_final_local: every file of experiments/thesis-final-20261006 except the files committed
  for reproducibility (router raw files, scorer, semantic labels, frozen planner run) and Python
  caches. This includes the thesis documents, which are never committed.
Reads files only; changes nothing else.

    python3 -I experiments/thesis-followup-20261012/build_local_manifest.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FROZEN = ROOT / 'experiments/thesis-final-20261006'
FROZEN_PLANNER = FROZEN / 'planner/runs/20261006T173518.677345Z'


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def ignored(paths):
    out = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin'], cwd=ROOT, input='\n'.join(paths),
                         capture_output=True, text=True).stdout
    return set(out.splitlines())


def entry(rel, **extra):
    data = (ROOT / rel).read_bytes()
    return {'path': rel, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), **extra}


def rels(folder):
    return sorted(str(p.relative_to(ROOT)) for p in folder.rglob('*') if p.is_file())


def committed_frozen(rel):
    p = ROOT / rel
    if p.parent == FROZEN / 'raw' and p.suffix == '.jsonl':
        return True
    if p in (FROZEN / 'analyze_router.py', FROZEN / 'semantic_labels.json'):
        return True
    return FROZEN_PLANNER in p.parents


def main(untracked_now):
    followup = rels(HERE)
    tracked = set(git('ls-files', '--', str(HERE.relative_to(ROOT))).splitlines())
    skip = ignored(followup)
    first = {}
    for rel in untracked_now:
        first[rel] = git('log', '--diff-filter=A', '--format=%h', '--', rel).split()[-1]
    out = {
        'note': 'SHA-256 and size of measurement files kept local (author rule, 2026-10-13). '
                'Paths are relative to the repository root.',
        'untracked_after_push': [entry(r, first_commit=first[r]) for r in sorted(untracked_now)],
        'h4_runs_local': [entry(r) for r in followup if '/h4-runs/' in r and '__pycache__' not in r and r in skip and r not in tracked
                          and r not in untracked_now],
        'thesis_final_local': [entry(r) for r in rels(FROZEN)
                               if not committed_frozen(r) and '__pycache__' not in r and '.pytest_cache' not in r],
    }
    frozen_skipped = [r for r in rels(FROZEN) if committed_frozen(r) and r in ignored([r])]
    out['thesis_final_local'] += [entry(r) for r in frozen_skipped]
    out['counts'] = {k: len(v) for k, v in out.items() if isinstance(v, list)}
    (HERE / 'local-only-manifest.json').write_text(json.dumps(out, indent=1) + '\n')
    print(out['counts'])


if __name__ == '__main__':
    # The files to untrack are passed on stdin (one path per line), as listed before `git rm --cached`.
    main([l for l in sys.stdin.read().splitlines() if l.strip()])
