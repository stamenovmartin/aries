"""Check all original case preconditions without LLM calls or injected effects."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from case_tools import cases

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    rows = []
    for case_id in cases():
        run = subprocess.run([sys.executable, str(HERE / 'run_loop.py'), '--case', case_id,
                              '--preflight-only'], cwd=ROOT, text=True, capture_output=True,
                             timeout=120, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        try:
            envelope = json.loads(run.stdout.strip().splitlines()[-1])
            saved = json.loads(Path(envelope['artifact']).read_text())
            row = {'case_id': case_id, 'outcome': saved.get('outcome', 'error'),
                   'reason': saved.get('skip_reason') or saved.get('error'),
                   'artifact': envelope['artifact'], 'llm_calls': len(saved.get('prompts', []))}
        except (ValueError, KeyError, IndexError, OSError):
            row = {'case_id': case_id, 'outcome': 'error', 'reason': run.stderr[-1000:]}
        rows.append(row)
        print(case_id, row['outcome'], flush=True)
    report = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'n': len(rows),
              'ready': sum(r['outcome'] == 'preflight_ready' for r in rows),
              'skipped': sum(r['outcome'] == 'skipped' for r in rows),
              'errors': sum(r['outcome'] == 'error' for r in rows),
              'scope': 'Preconditions only, not agent success or fault reachability', 'cases': rows}
    path = HERE / 'case_coverage.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)
    return int(bool(report['errors']))


if __name__ == '__main__':
    raise SystemExit(main())
