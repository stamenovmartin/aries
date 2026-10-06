"""Run every test that covers Macedonian, and fail if any of it has regressed.

Macedonian is frozen, not removed. A freeze that is not checked is a deletion with a
delay, so this exists to be run — by hand, and by `scripts/test.sh`.

Each file runs in its own process with its own sqlite file, which is what the main
suite does and for the same reason: a test that reads the live switches is a test run
against production state.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = pathlib.Path(__file__).with_name('MANIFEST')


def entries():
    for line in MANIFEST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        path, kind, holds = (part.strip() for part in line.split('·', 2))
        yield path, kind, holds


def main():
    env = {'APP_ENV': 'test',
           'PYTHONPATH': f'{ROOT}/vendor/agentic-core:{ROOT}/vendor:{ROOT}',
           'PATH': '/usr/bin:/bin', 'HOME': str(pathlib.Path.home())}
    python = str(ROOT / '.venv/bin/python')
    failed, missing = [], []
    print('Macedonian, frozen 2026-10-03 — coverage check\n')
    for path, kind, holds in entries():
        target = ROOT / path
        if not target.is_file():
            missing.append(path)
            print(f'{path:44s} MISSING   {holds}')
            continue
        out = subprocess.run([python, str(target)], capture_output=True, text=True,
                             cwd=str(ROOT), env=env)
        checks = out.stdout.count('\nPASS') + out.stdout.startswith('PASS')
        if out.returncode == 0:
            print(f'{path:44s} passed ({checks:3d})  [{kind}] {holds}')
        else:
            failed.append(path)
            print(f'{path:44s} FAILED    [{kind}] {holds}')
            for line in out.stdout.splitlines():
                if line.startswith('FAIL'):
                    print(f'    {line}')
    print()
    if missing:
        print(f'{len(missing)} file(s) named in MANIFEST no longer exist — the freeze has holes:')
        for path in missing:
            print(f'  {path}')
    if failed:
        print(f'{len(failed)} file(s) regressed. Macedonian is frozen, which means it must keep working.')
        return 1
    if missing:
        return 1
    print('All frozen Macedonian coverage still passes.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
