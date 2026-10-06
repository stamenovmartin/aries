"""Противнички тест на `aries.workspace.scopes`: само извршување, без читање на код.

Изолиран: не допира база, не стартува сервис, не пишува надвор од tmp.
"""
import os, sys, tempfile, time, json, pathlib
sys.path[:0] = [os.path.abspath(p) for p in ('vendor/agentic-core', 'vendor', '.')]
from aries.workspace.scopes import Grant, use, enforce, current
from aries.workspace.registry import registry

R = []
def case(name, fn, expect):
    """expect: 'refuse' ако мора да фрли PermissionError, 'allow' ако мора да помине."""
    try:
        fn(); got = 'allow'; detail = ''
    except PermissionError as e:
        got = 'refuse'; detail = str(e)[:90]
    except Exception as e:
        got = f'{type(e).__name__}'; detail = str(e)[:90]
    R.append({'case': name, 'expected': expect, 'observed': got,
              'verdict': 'PASS' if got == expect else 'FAIL', 'detail': detail})

tmp = pathlib.Path(tempfile.mkdtemp(prefix='aries-scope-'))
(tmp / 'allowed.txt').write_text('x')
(tmp / 'secret.txt').write_text('y')
(tmp / 'link.txt').symlink_to(tmp / 'secret.txt')
soon = time.time() + 300

def grant(**kw):
    base = dict(root_id='r1', capabilities=['file.read'], paths=[str(tmp / 'allowed.txt')],
                task_ids=['t1'], expires_at=soon, read_only=True)
    base.update(kw)
    return Grant.model_validate(base).validate_registry()

cap = registry.get('file.read')

# 1 — без грант нема ограничување (документирано однесување, не дефект)
case('no grant: enforce is inert', lambda: enforce(cap, {'path': str(tmp / 'secret.txt')}), 'allow')

# 2 — дозволената патека поминува
def ok():
    with use(grant()):
        enforce(cap, {'path': str(tmp / 'allowed.txt'), 'task_id': 't1'})
case('granted path allowed', ok, 'allow')

# 3 — друга патека во истиот директориум
def other():
    with use(grant()):
        enforce(cap, {'path': str(tmp / 'secret.txt'), 'task_id': 't1'})
case('sibling path refused', other, 'refuse')

# 4 — симболична врска која покажува кон недозволена цел
def via_link():
    with use(grant(paths=[str(tmp / 'link.txt')])):
        enforce(cap, {'path': str(tmp / 'link.txt'), 'task_id': 't1'})
case('symlink to ungranted target refused', via_link, 'refuse')

# 5 — обид за враќање низ ..
def dotdot():
    with use(grant()):
        enforce(cap, {'path': str(tmp / 'sub' / '..' / 'secret.txt'), 'task_id': 't1'})
case('.. traversal refused', dotdot, 'refuse')

# 6 — истечен грант
def expired():
    with use(grant(expires_at=time.time() - 1)):
        enforce(cap, {'path': str(tmp / 'allowed.txt'), 'task_id': 't1'})
case('expired grant refused', expired, 'refuse')

# 7 — празна листа патеки наспроти барање со патека
def nopaths():
    with use(grant(paths=[])):
        enforce(cap, {'path': str(tmp / 'allowed.txt'), 'task_id': 't1'})
case('empty paths is fail-closed', nopaths, 'refuse')

# 8 — туѓ task_id
def othertask():
    with use(grant()):
        enforce(cap, {'path': str(tmp / 'allowed.txt'), 'task_id': 't2'})
case('foreign task_id refused', othertask, 'refuse')

# 9 — проширување на наследен грант
def widen():
    with use(grant()):
        with use(grant(capabilities=['file.read', 'file.list'])):
            pass
case('child cannot widen capabilities', widen, 'refuse')

# 10 — продолжување на рокот
def longer():
    with use(grant()):
        with use(grant(expires_at=soon + 600)):
            pass
case('child cannot extend expiry', longer, 'refuse')

# 11 — од read-only кон запишување
def writable():
    with use(grant()):
        with use(grant(read_only=False)):
            pass
case('child cannot drop read_only', writable, 'refuse')

# 12 — read-only грант не смее да прими способност што менува
def mutating():
    Grant.model_validate(dict(root_id='r1', capabilities=['file.write'], paths=[],
                              task_ids=['t1'], expires_at=soon, read_only=True)).validate_registry()
case('read-only grant rejects file.write', mutating, 'refuse')

# 13 — URL под грант за датотеки
def url():
    with use(grant()):
        enforce(registry.get('browser.open'), {'url': 'https://example.com'})
case('url under file grant refused', url, 'refuse')

# 14 — контекстот се враќа по излез од блокот
def restored():
    with use(grant()):
        pass
    assert current() is None, 'grant leaked past its block'
case('grant does not leak past its block', restored, 'allow')

out = pathlib.Path('experiments/product/independent-acceptance/raw/scopes_adversarial.json')
out.parent.mkdir(parents=True, exist_ok=True)
fails = [r for r in R if r['verdict'] == 'FAIL']
out.write_text(json.dumps({'n': len(R), 'passed': len(R) - len(fails), 'failed': len(fails),
                           'results': R}, ensure_ascii=False, indent=2))
for r in R:
    print(f"{r['verdict']:4s} {r['case']:44s} очекувано={r['expected']:6s} добиено={r['observed']}")
print(f"\n{len(R) - len(fails)}/{len(R)} поминаа")
