#!/usr/bin/env python3
"""Generate docs/CONFIG_REFERENCE.md from the code: every flag and every setting.

    PYTHONPATH=vendor/agentic-core:vendor:. .venv/bin/python scripts/gen_config_reference.py
    ... --check     exit 1 if the committed file differs from what the code says

Flags come from `aries.flags.FLAGS`, a plain dict, so it is imported. The module that owns a
flag is every file outside `aries/flags.py` that names it (`git grep -l`).

Settings are registered by `define(SettingDef(...))` at import time. The registry is read by
importing every module that contains a `SettingDef(` call. Importing starts nothing: the
environment is pointed at a throw-away SQLite path and a missing flag file first, as the test
bootstrap does, and no engine connection is opened. The module that owns a setting comes from
the source (`ast`): the file of the `SettingDef("<key>", ...)` call, or, for keys built in a loop,
the one file whose `SettingDef(` has a computed key. If the import fails, the settings table is
built from `ast` alone, from literal arguments, and the file says so.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/CONFIG_REFERENCE.md'
FIELDS = ('key', 'type', 'default', 'title', 'description', 'section')


def _isolate():
    scratch = tempfile.mkdtemp(prefix='aries-config-ref-')
    import atexit
    import shutil
    atexit.register(shutil.rmtree, scratch, True)
    os.environ.update(APP_ENV='test', DATABASE_URL=f'sqlite+aiosqlite:///{scratch}/ref.db', DATA_DIR=scratch,
                      RUNTIME_STORE=f'{scratch}/runtime.json', CONTEXT_DIR=f'{scratch}/context',
                      ARIES_FLAG_FILE='/nonexistent/aries-flags.env')
    for name in [k for k in os.environ if k.startswith('ARIES_') and k != 'ARIES_FLAG_FILE']:
        os.environ.pop(name)       # the generated defaults must not depend on who runs this
    for p in (ROOT / 'vendor/agentic-core', ROOT / 'vendor', ROOT):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def _git_files(*args):
    out = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    return [line for line in out.stdout.splitlines() if line]


def setting_sites():
    """{key: 'path:line'} for literal keys, plus the files with computed keys."""
    literal, computed = {}, []
    for rel in _git_files('grep', '-l', '-F', 'SettingDef(', '--', 'aries'):
        tree = ast.parse((ROOT / rel).read_text(), rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, 'id', getattr(node.func, 'attr', None)) == 'SettingDef':
                if rel == 'aries/settings/schema.py':
                    continue
                first = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == 'key'), None)
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    literal[first.value] = (f'{rel}:{node.lineno}', node)
                else:
                    computed.append(f'{rel}:{node.lineno}')
    return literal, computed


def flag_rows():
    from aries import flags
    rows = []
    for name, (default, governs) in sorted(flags.FLAGS.items()):
        owners = [f for f in _git_files('grep', '-l', '-F', name, '--', 'aries', 'aries_ui', 'shell', 'scripts', 'systemd')
                  if f != 'aries/flags.py']
        rows.append({'name': name, 'default': 'on' if default else 'off', 'governs': governs, 'owners': owners})
    return rows


_CALLERS: dict[str, str] = {}


def _capture_define():
    """Load aries/settings/schema.py before the package, and record who calls define().

    `aries/__init__.py` imports every feature package, and each binds `define` with
    `from aries.settings.schema import define` as it is imported. Putting the module in
    sys.modules first, with define wrapped, is the only way to see the caller of a key that
    is built in a loop. schema.py imports nothing from ARIES, so loading it alone is safe.
    """
    import importlib.util
    if 'aries' in sys.modules:
        return False
    spec = importlib.util.spec_from_file_location('aries.settings.schema', ROOT / 'aries/settings/schema.py')
    schema = importlib.util.module_from_spec(spec)
    sys.modules['aries.settings.schema'] = schema
    spec.loader.exec_module(schema)
    original = schema.define

    def define(d, *a, **k):
        frame = sys._getframe(1)
        _CALLERS[d.key] = f"{Path(frame.f_code.co_filename).resolve().relative_to(ROOT)}:{frame.f_lineno}"
        return original(d, *a, **k)
    schema.define = define
    return True


def setting_rows(literal, computed):
    try:
        import importlib
        captured = _capture_define()
        modules = sorted({site.split(':')[0] for site, _ in literal.values()} | {c.split(':')[0] for c in computed})
        import aries  # noqa: F401  registers the core settings in the documented order
        for rel in modules:
            importlib.import_module(rel[:-3].replace('/', '.').removesuffix('.__init__'))
        from aries.settings.schema import _REGISTRY
        rows = []
        for key, d in sorted(_REGISTRY.items()):
            if key in literal:
                site = literal[key][0]
            elif captured and key in _CALLERS:
                site = _CALLERS[key] + ' (key computed)'
            else:
                site = ', '.join(computed) + ' (key computed)'
            rows.append({'key': key, 'type': d.type.__name__, 'default': d.default, 'title': d.title,
                         'description': d.description, 'section': d.section, 'module': site})
        return rows, 'imported (the live registry)'
    except Exception as exc:                                        # noqa: BLE001
        rows = []
        for key, (site, node) in sorted(literal.items()):
            args = list(node.args) + [None] * 6

            def lit(n):
                try:
                    return ast.literal_eval(n) if n is not None else None
                except ValueError:
                    return ast.unparse(n)
            rows.append({'key': key, 'type': ast.unparse(args[1]) if args[1] is not None else '?',
                         'default': lit(args[2]), 'title': lit(args[3]), 'description': lit(args[4]),
                         'section': lit(args[5]), 'module': site})
        return rows, f'parsed with ast (import failed: {type(exc).__name__}: {exc}); computed keys not listed: {computed}'


def cell(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text.replace('|', '\\|').replace('\n', ' ')


def render():
    _isolate()
    literal, computed = setting_sites()
    settings, how = setting_rows(literal, computed)      # first: it must load schema.py before `aries`
    flags = flag_rows()
    off = [f['name'] for f in flags if f['default'] == 'off']
    lines = [
        '# Configuration reference',
        '',
        '**Generated, do not edit.** `scripts/gen_config_reference.py` writes this file from the code;',
        '`--check` fails when the two disagree.',
        '',
        f'- {len(flags)} flags in `aries/flags.py`, {len(off)} of them off by default. A flag is read',
        '  with `aries.flags.enabled(name)`. The environment wins over the override file',
        '  (`ARIES_FLAG_FILE`, default `var/flags.env`), and the file wins over the default.',
        f'- {len(settings)} settings registered with `SettingDef`; the registry was {how}. A setting',
        '  is changed through the Settings service, the API or the Control Centre, never by editing',
        '  code.',
        '',
        '## Flags',
        '',
        'Owner = every file outside `aries/flags.py` that names the flag (`git grep -l`).',
        '',
        '| flag | default | what it governs | owner |',
        '|---|:-:|---|---|',
    ]
    for f in flags:
        owners = ', '.join(f'`{o}`' for o in f['owners']) or '**none** (read nowhere)'
        lines.append(f"| `{f['name']}` | {f['default']} | {cell(f['governs'])} | {owners} |")
    lines += ['', '## Settings', '',
              'Module = the file and line of the `SettingDef` call.', '',
              '| key | type | default | section | title — description | module |',
              '|---|---|---|---|---|---|']
    for s in settings:
        lines.append(f"| `{s['key']}` | {s['type']} | `{cell(s['default'])}` | {cell(s['section'])} | "
                     f"**{cell(s['title'])}** — {cell(s['description'])} | `{s['module']}` |")
    return '\n'.join(lines) + '\n'


def main():
    text = render()
    if '--check' in sys.argv:
        same = OUT.exists() and OUT.read_text() == text
        print('docs/CONFIG_REFERENCE.md is ' + ('current' if same else 'STALE: rerun scripts/gen_config_reference.py'))
        raise SystemExit(0 if same else 1)
    OUT.write_text(text)
    print(f'wrote {OUT.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
