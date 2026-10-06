"""Which stage actually stops an underspecified request, in the live order?

`recognizer.py` measures one stage. The live path has two gates in front of it,
and crediting or blaming the wrong one is how a fixed benchmark starts lying. This
replicates `aries/workspace/service.py` lines 74-95 exactly:

    1. clarification.question(request)          four hardcoded phrasings
    2. working_context.resolve(db, request)     open/read + a bare pronoun only
    3. capabilities.recognize(request)          whatever this matches, ARIES does

and reports, per utterance, which of the three decided. A fresh database means no
recent context, which is the honest worst case: a pronoun with nothing to point at.

Nothing is executed and no model is called. Stage 3 is reported, never run.
"""
import asyncio, importlib.util, json, os, pathlib, sys, tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
ORIGINAL = sys.argv[1] if len(sys.argv) > 1 else None   # a pre-change capabilities.py


async def main():
    import aries  # noqa: F401
    from agentic_core.database import models  # noqa: F401
    from agentic_core.database.base import Base, async_session, engine
    from aries.workspace import capabilities, working_context
    from aries.workspace.clarification import question

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    recognizers = {'shipped': capabilities.recognize}
    if ORIGINAL:
        spec = importlib.util.spec_from_file_location('capabilities_before', ORIGINAL)
        before = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(before)
        recognizers['before'] = before.recognize

    rows = [json.loads(line) for line in (HERE / 'fixture.jsonl').open() if line.strip()]
    report = {}
    for name, recognize in recognizers.items():
        stages, acted = {}, []
        for row in rows:
            text = row['utterance']
            stage = None
            if question(text) is not None:
                stage = '1-clarification'
            else:
                async with async_session() as db:
                    try:
                        await working_context.resolve(db, text)
                    except ValueError as exc:
                        stage = '2-unresolved-reference' if str(exc).startswith('AMBIGUOUS:') else '2-error'
            if stage is None:
                match = recognize(text)
                stage = '3-recognised-acts' if match else '4-reaches-planner'
                if match and row['klass'] != 'actionable':
                    acted.append((row['klass'], text, match['capability'], match.get('args')))
            stages.setdefault((row['klass'], stage), 0)
            stages[(row['klass'], stage)] += 1
        report[name] = {'stages': {f'{k[0]}|{k[1]}': v for k, v in sorted(stages.items())},
                        'acts_on_non_actionable': acted}

    order = ('1-clarification', '2-unresolved-reference', '3-recognised-acts', '4-reaches-planner')
    for name, data in report.items():
        print(f'\n=== {name} ===')
        print(f'{"class":14s} ' + ' '.join(f'{s:>22s}' for s in order))
        for klass in ('actionable', 'ambiguous', 'out_of_scope', 'unsafe'):
            cells = [data['stages'].get(f'{klass}|{s}', 0) for s in order]
            print(f'{klass:14s} ' + ' '.join(f'{c:>22d}' for c in cells))
        hold = sum(v for k, v in data['stages'].items()
                   if not k.startswith('actionable|') and k.endswith('3-recognised-acts'))
        print(f'  acts without asking, on something it should not: {hold}')
    if 'before' in report:
        b = sum(v for k, v in report['before']['stages'].items()
                if not k.startswith('actionable|') and k.endswith('3-recognised-acts'))
        a = sum(v for k, v in report['shipped']['stages'].items()
                if not k.startswith('actionable|') and k.endswith('3-recognised-acts'))
        ab = report['before']['stages'].get('actionable|3-recognised-acts', 0)
        aa = report['shipped']['stages'].get('actionable|3-recognised-acts', 0)
        print(f'\nlive, past both gates: acts on should-hold {b} -> {a};  '
              f'acts on actionable {ab} -> {aa}')
        closed = {t for _, t, _, _ in report['before']['acts_on_non_actionable']} - \
                 {t for _, t, _, _ in report['shipped']['acts_on_non_actionable']}
        print(f'closed by the change ({len(closed)}):')
        for klass, text, capability, args in report['before']['acts_on_non_actionable']:
            if text in closed:
                print(f'  [{klass:12s}] {text!r} -> {capability}({args})')
        print('still acting:')
        for klass, text, capability, args in report['shipped']['acts_on_non_actionable']:
            print(f'  [{klass:12s}] {text!r} -> {capability}({args})')
    (HERE / 'gate.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    tmp = tempfile.mkdtemp(prefix='gate-')
    os.environ['APP_ENV'] = 'test'
    os.environ['DATABASE_URL'] = f'sqlite+aiosqlite:///{tmp}/gate.db'
    for p in (ROOT / 'vendor' / 'agentic-core', ROOT / 'vendor', ROOT):
        sys.path.insert(0, str(p))
    asyncio.run(main())
