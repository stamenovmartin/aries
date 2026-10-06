"""Извршен доказ за F-05: чуварот против повторување нема услов за ефект.

Предикатот од `agent.py:367-368` се оценува изолирано, со синтетички чекори.
Не стартува агент, не допира база, не повикува модел, не извршува ниедна способност.
"""
import json, os, pathlib, sys
sys.path[:0] = [os.path.abspath(p) for p in ('vendor/agentic-core', 'vendor', '.')]
from aries.workspace.agent import error
from aries.workspace.registry import registry

def refused(prior, candidate):
    """Точната копија на предикатот од agent.py:367-368.
    Враќа True ако чуварот би го одбил повторувањето."""
    steps = [prior, candidate]
    step = candidate
    return any(s is not step and s['capability'] == step['capability'] and s['args'] == step['args']
               and (s.get('verification_status') == 'verified'
                    or not (s.get('error') or {}).get('retryable', False))
               for s in steps)

def step(cap, args, *, status, err=None):
    return {'capability': cap, 'args': args, 'verification_status': status, 'error': err}

# 1 — како се класифицира истек на време, по способност
timeout_err = error(TimeoutError('capability timed out'))
print(f"error(TimeoutError) -> code={timeout_err['code']}  retryable={timeout_err['retryable']}")
assert timeout_err['retryable'] is True

caps = sorted(registry._items.values(), key=lambda c: c.name)
mutating_unapproved = [c for c in caps if c.effect != 'read' and not c.requires_approval]
mutating_approved = [c for c in caps if c.effect != 'read' and c.requires_approval]

rows = []
for c in mutating_unapproved + mutating_approved:
    args = {'probe': 'x'}
    prior_timeout = step(c.name, args, status='failed', err=timeout_err)
    prior_hard = step(c.name, args, status='failed',
                      err=error(ValueError('NON_RETRYABLE: refused')))
    prior_ok = step(c.name, args, status='verified')
    cand = step(c.name, args, status='pending')
    rows.append({
        'capability': c.name, 'effect': c.effect, 'requires_approval': c.requires_approval,
        'repeat_after_timeout_refused': refused(prior_timeout, cand),
        'repeat_after_nonretryable_refused': refused(prior_hard, cand),
        'repeat_after_verified_refused': refused(prior_ok, cand),
    })

allowed = [r for r in rows if not r['repeat_after_timeout_refused']]
print(f"\nмутирачки способности испитани : {len(rows)}")
print(f"повторување по истек е ДОЗВОЛЕНО: {len(allowed)}")
print(f"повторување по тврда грешка е одбиено за: "
      f"{sum(r['repeat_after_nonretryable_refused'] for r in rows)}/{len(rows)}")
print(f"повторување по верификација е одбиено за: "
      f"{sum(r['repeat_after_verified_refused'] for r in rows)}/{len(rows)}")
print("\nдозволени за повторување по истек, без одобрување:")
for r in allowed:
    if not r['requires_approval']:
        print(f"   {r['capability']:26s} ефект={r['effect']}")

out = pathlib.Path('experiments/product/independent-acceptance/raw/replay_guard.json')
out.write_text(json.dumps({
    'claim': 'F-05 — the replay guard has no cap.effect term, so a mutating step that timed out '
             'may be repeated while its effects are uncertain',
    'method': 'executed: the predicate from agent.py:367-368 copied verbatim and evaluated against '
              'synthetic steps. No agent run, no database, no capability executed.',
    'timeout_classification': timeout_err,
    'mutating_capabilities_examined': len(rows),
    'repeat_after_timeout_allowed': len(allowed),
    'repeat_after_timeout_allowed_without_approval':
        sum(1 for r in allowed if not r['requires_approval']),
    'guard_does_work_for': {
        'non_retryable_errors': sum(r['repeat_after_nonretryable_refused'] for r in rows),
        'already_verified_steps': sum(r['repeat_after_verified_refused'] for r in rows)},
    'rows': rows}, ensure_ascii=False, indent=2))
print(f"\nзапишано {out}")
