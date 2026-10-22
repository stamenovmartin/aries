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
# The frozen planner's 58 capabilities, descriptions verbatim (R1 Amendment 2; capabilities.json).
_CAPS = json.loads((HERE / 'capabilities.json').read_text())
CAPABILITIES = {c['name']: c['description'] for c in _CAPS['capabilities']}
ALIASES = {m: cls[0] for cls in _CAPS['alias_classes'] for m in cls}


def canonical(label):
    return ALIASES.get(label, label)


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
