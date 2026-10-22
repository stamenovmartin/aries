"""Shared constants for R1 (docs/preregistration/R1-real-data-benchmarks.md)."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path.home() / 'data-ext'
LOCAL = DATA / 'r1'            # sample texts, raw labeler transcripts: local only, never committed
SHA = {'nl2bash/all.nl': '1db0c529c350b463919624550b8f5882a97c42ad5051c7d49fbc496bc4e8b770',
       'nl2bash/all.cm': '3a72eaced7fa14a0938354cefc42b2dcafb2d47297102f1279086e18c3abe57e',
       'clinc150/data_full.json': '36923c3705a59e08fe9c3883d8bc2dd966ef93e22cb78ac41171782a698d56e0'}
# The 15 planner capabilities of the frozen registry, descriptions verbatim
# (experiments/thesis-final-20261006/frozen/aries/workspace/registry.py, SHA-256 96f32e49...).
CAPABILITIES = {
    'file.read': 'Read a regular UTF-8 text file up to 100 KB',
    'file.write': 'Create a NEW nonempty text file; never overwrite. Parent must exist.',
    'file.list': 'List at most 200 allowed directory entries',
    'file.search': 'Search filenames under a directory, optionally within an ISO modification-time range',
    'file.exists': 'Check existence only when asked about existence. For read goals use file.read directly, which '
                   'reports missing-path errors.',
    'browser.open': 'Open a public URL in a task-owned browser and observe navigation',
    'browser.read': 'Read a task-owned browser session using its observed session ID',
    'browser.search': 'Open public web or YouTube search for a literal query',
    'desktop.launch': 'Open an installed application by name; verify visible focused window',
    'desktop.focus': 'Focus an already observed installed app; never launch a replacement',
    'system.status': 'Observe current CPU, memory and disk probes',
    'system.storage': 'Measure filesystem usage; highest is computed from measured percentages',
    'system.processes': 'Observe bounded process names and IDs; no command lines',
    'task.inspect': 'Inspect a persisted task by ID',
    'notification.send': 'Create a policy-controlled notification record; approval required',
}
OOS = 'OUT_OF_SCOPE'
LABELS = list(CAPABILITIES) + [OOS]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_data():
    for rel, digest in SHA.items():
        if sha(DATA / rel) != digest:
            raise SystemExit(f'REFUSED: {rel} does not match its registered SHA-256')


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_jsonl(path, rows, mode='x'):
    with open(path, mode) as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
