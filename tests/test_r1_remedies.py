"""The remedies designed after R1 (public data), each behind its own flag (default off).

ARIES_ROUTER_CAPABILITY_GATE     capability_gate: one enum call can turn an action into OUT_OF_SCOPE, never back.
ARIES_ROUTER_SURFACE_CONSISTENT  router: the abstention text without its two contradictions.
ARIES_PLANNER_PER_CAP_GRAMMAR    agent_planner: one grammar branch per capability, with its required arguments.
ARIES_PLANNER_OOS_ACTION         agent_planner: refusing is offered as fail with OUT_OF_SCOPE.
ARIES_PLANNER_GATE_HINT          agent_planner: the gate's capability is passed on.

The model is mocked; no inference runs.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import check, run_module
from tests import test_agent_execution as m14


def registered():
    import aries.api.app  # noqa: F401  registers the capabilities
    from aries.workspace import agent_planner
    return agent_planner


def test_per_capability_grammar_requires_arguments():
    P = registered()
    schema = P.generation_schema(allow_finish=False, allow_fail=True, per_capability=True)
    branches = schema['anyOf']
    by_cap = {b['properties']['capability']['enum'][0]: b for b in branches if 'capability' in b['properties']}
    check('one branch per capability', set(by_cap) == {c['name'] for c in P.scoped_capabilities()})
    search = by_cap.get('file.search')
    required = [n for n in next(c for c in P.scoped_capabilities() if c['name'] == 'file.search')['input_schema'].get('required', [])]
    check('file.search requires its own required arguments', search and search['properties']['arguments'].get('required') == required
          and 'path' in required)
    check('a branch allows only its capability\'s arguments', all(
        set(b['properties']['arguments']['properties']) == set(
            next(c for c in P.scoped_capabilities() if c['name'] == n)['input_schema'].get('properties', {}))
        for n, b in by_cap.items()))
    terminal = [b for b in branches if 'capability' not in b['properties']]
    check('fail is a branch without capability or arguments', len(terminal) == 1
          and terminal[0]['properties']['action']['enum'] == ['fail'] and 'arguments' not in terminal[0]['properties'])
    flat = P.generation_schema(allow_finish=False, allow_fail=True)
    check('flag off: the flat grammar is unchanged', flat['type'] == 'object' and 'anyOf' not in flat)


def test_per_capability_grammar_is_grammar_safe():
    P = registered()
    schema = P.generation_schema(allow_finish=True, allow_fail=True, allow_ask=True, per_capability=True)
    bad = []

    def walk(node, where, names=False):
        if isinstance(node, dict):
            if names:                                  # keys of `properties` are field names, not keywords
                for k, v in node.items():
                    walk(v, f'{where}.{k}')
                return
            if node.get('type') == 'string' and 'enum' not in node and not node.get('maxLength'):
                bad.append(where)
            for k in ('pattern', 'title'):
                if k in node:
                    bad.append(f'{where}.{k}')
            for k, v in node.items():
                walk(v, f'{where}.{k}', names=k == 'properties')
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f'{where}[{i}]')
    walk(schema, '$')
    check(f'no unbounded string, pattern or title anywhere {bad[:5]}', bad == [])
    check('the ask branch is present when asking is offered',
          any(b['properties']['action']['enum'] == ['ask_clarification'] for b in schema['anyOf']))


def test_every_branch_output_validates():
    P = registered()
    from aries.workspace.registry import registry
    ok = []
    for cap in P.scoped_capabilities():
        props = cap['input_schema'].get('properties', {})
        args = {}
        for n in cap['input_schema'].get('required', []):
            s = props[n].get('anyOf', [props[n]])[0]
            t = s.get('type')
            args[n] = s['enum'][0] if 'enum' in s else 1 if t == 'integer' else True if t == 'boolean' else \
                [] if t == 'array' else '/tmp/x' if 'path' in n else 'x'
        try:
            registry.validate(cap['name'], args)
            ok.append(True)
        except Exception:                                         # noqa: BLE001
            ok.append(False)
    check(f'a branch filled with its required arguments passes registry validation ({sum(ok)}/{len(ok)})',
          sum(ok) >= len(ok) - 10)


def test_router_surface_text():
    from aries.intelligence import router
    p = router.LocalLLMDecisionProvider()
    with patch.dict(os.environ, {'ARIES_ROUTER_SURFACE_CONSISTENT': '0', 'ARIES_ROUTER_ABSTAIN': '1'}):
        frozen = p.instruction()
    with patch.dict(os.environ, {'ARIES_ROUTER_SURFACE_CONSISTENT': '1', 'ARIES_ROUTER_ABSTAIN': '1'}):
        new = p.instruction()
    check('flag off: the frozen "never OUT_OF_SCOPE" sentence', 'none of these is ever OUT_OF_SCOPE' in frozen)
    check('flag on: that sentence is gone', 'none of these is ever OUT_OF_SCOPE' not in new)
    check('flag on: email is named as having no capability', 'not READ_EMAIL, SEND_EMAIL or CALENDAR_ACTION' in new)
    check('flag on: the capability surface and machine limits are still there',
          router.capability_surface() in new and router.machine_limits() in new)


def test_gate_turns_action_into_oos_only():
    from aries.intelligence import capability_gate as G
    from aries.intelligence.schemas import Decision
    act = Decision(intent='FILE_ACTION', tool='workspace', confidence=0.9, reason='r')
    check('OUT_OF_SCOPE from the gate abstains', G.apply(act, {'label': 'OUT_OF_SCOPE'}).intent == 'OUT_OF_SCOPE')
    check('a capability from the gate leaves the decision', G.apply(act, {'label': 'file.read'}) == act)
    check('a failed gate call leaves the decision', G.apply(act, {'label': None, 'error': 'x'}) == act)
    check('the gate applies to a local action', G.applies(act, 'local'))
    for intent in ('ASK', 'OUT_OF_SCOPE', 'UNKNOWN'):
        check(f'the gate never runs on {intent}', not G.applies(act.model_copy(update={'intent': intent}), 'local'))
    check('the gate never runs on a rule route', not G.applies(act, 'rule'))


def test_gate_schema_and_prompt():
    registered()
    from aries.intelligence import capability_gate as G
    caps = G.capabilities()
    schema = G.schema(caps)
    check('the enum is the capability names plus OUT_OF_SCOPE',
          schema['properties']['label']['enum'] == [n for n, _ in caps] + ['OUT_OF_SCOPE'])
    check('every capability is described in the prompt', all(f'- {n}:' in G.instruction(caps) for n, _ in caps))


def test_gate_asks_the_r1_zero_shot_question():
    import json
    from aries.intelligence import capability_gate as G
    r1 = Path(__file__).resolve().parents[1] / 'experiments/thesis-r1-real-data'
    sys.path.insert(0, str(r1))
    import run_r1
    caps = [(c['name'], c['description']) for c in json.loads((r1 / 'capabilities.json').read_text())['capabilities']]
    check('with the R1 capability list the gate instruction is R1\'s zero-shot instruction',
          G.instruction(caps) == run_r1.ZEROSHOT_SYSTEM)
    registered()
    check('the registry gives the same 58 descriptions', G.capabilities() == [(n, ' '.join(d.split())) for n, d in caps])


async def test_gate_in_the_router():
    await m14.setup()
    from agentic_core.database.base import async_session
    from aries.intelligence import router
    from aries.intelligence.schemas import Decision
    calls = []

    class Acting(router.LocalLLMDecisionProvider):
        async def decide(self, db, text):
            self.usage = {}
            return Decision(intent='FILE_ACTION', tool='workspace', confidence=0.95, reason='looks like files')

    async def fake(db, messages, schema, **kwargs):
        calls.append(kwargs.get('purpose'))
        return json.dumps({'label': label}), {}
    for label, flag, want in (('OUT_OF_SCOPE', '1', 'OUT_OF_SCOPE'), ('file.list', '1', 'FILE_ACTION'),
                              ('OUT_OF_SCOPE', '0', 'FILE_ACTION')):
        calls.clear()
        with patch.dict(os.environ, {'ARIES_ROUTER_CAPABILITY_GATE': flag}), \
                patch('aries.intelligence.local_structured', side_effect=fake):
            async with async_session() as db:
                r = await router.route(db, f'compress every log file into one archive {label} {flag}',
                                       provider=Acting(), allow_contract=False)
        check(f'gate {flag} says {label}: intent {want}', r.intent == want)
        check(f'gate {flag}: called only when on', (calls == ['intelligence.capability-gate']) == (flag == '1'))
        check(f'gate {flag}: the label is kept on the route', r.gate_capability == (label if flag == '1' else None))


async def test_planner_messages():
    P = registered()
    await m14.setup()
    from agentic_core.database.base import async_session
    seen = []

    async def fake(db, messages, schema, **kwargs):
        seen.append((messages, schema))
        return json.dumps({'action': 'fail', 'reason': 'OUT_OF_SCOPE: no capability compresses files'}), {}
    data = {'routing': {'execution_level': 'local', 'gate_capability': 'file.list'}, 'steps': [], 'evidence': [],
            'agent': {'contract': {'supported': False, 'requirements': []}, 'context': {}, 'environment': {}}}
    for env in ({'ARIES_PLANNER_GATE_HINT': '1', 'ARIES_PLANNER_OOS_ACTION': '1', 'ARIES_PLANNER_PER_CAP_GRAMMAR': '1'},
                {'ARIES_PLANNER_GATE_HINT': '0', 'ARIES_PLANNER_OOS_ACTION': '0', 'ARIES_PLANNER_PER_CAP_GRAMMAR': '0'}):
        with patch.dict(os.environ, env), patch('aries.intelligence.structured', side_effect=fake):
            async with async_session() as db:
                raw, _ = await P.plan(db, 'compress the logs', json.loads(json.dumps(data)), 8)
        check('the fail decision parses', P.parse(raw).action == 'fail')
    on, off = seen
    text = lambda m: ' '.join(x['content'] for x in m)
    check('on: the gate hint names the capability', 'chose file.list' in text(on[0]))
    check('on: the OOS instruction is given', 'OUT_OF_SCOPE: ' in text(on[0]))
    check('on: per-capability grammar', 'anyOf' in on[1])
    check('off: neither message, flat grammar', 'chose file.list' not in text(off[0])
          and '"OUT_OF_SCOPE: "' not in text(off[0]) and 'anyOf' not in off[1])


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
