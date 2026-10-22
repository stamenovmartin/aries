"""ARIES_ROUTER_CAPABILITY_GATE: after the router decides to act, one call names the capability or OUT_OF_SCOPE.

Motivation (experiments/thesis-r1-real-data, R1 on NL2Bash): the router acted on 449 of 500 requests although
the gold label was OUT_OF_SCOPE for 307. Its vocabulary is fourteen coarse intents, and its prompt says that
whatever the catalogue lists "is never OUT_OF_SCOPE", so a request that only resembles a capability (delete,
compress, rename files) is classed FILE_ACTION and sent on. A zero-shot model shown the capabilities themselves,
with no ARIES structure, was right on 321 of 500. The gate puts that question inside ARIES: shown each
registered capability with its description, does one of them fulfil the request completely as the first step?

- The instruction is R1's zero-shot instruction word for word (thesis-r1-real-data/run_r1.py, ZEROSHOT_SYSTEM),
  with the descriptions read from the registry, so the gate asks exactly the question that scored 321 of 500.
- One grammar-constrained call; the answer is a bare enum, never prose. The enum is the capability names plus
  OUT_OF_SCOPE (aries-choice-routing-measurement: a bare enum is about 11x faster than a JSON Decision).
- It runs only on a local model decision that would act. Rule, cache and contract routes are unchanged, and the
  gate can only turn an action into OUT_OF_SCOPE; it never turns an abstention into an action.
- A failed call leaves the router's decision unchanged and is recorded.
- The chosen capability is kept on the route (gate_capability). The planner sees it only with
  ARIES_PLANNER_GATE_HINT, a separate flag, so the two effects can be measured apart.

Off, this module is never imported.
"""
from __future__ import annotations

import json
import time

OOS = 'OUT_OF_SCOPE'
ACTING_EXCLUDED = {'ASK', 'OUT_OF_SCOPE', 'UNKNOWN'}


def capabilities():
    """(name, description) for every capability the planner may use, from the registry."""
    from aries.workspace.agent_planner import scoped_capabilities
    return [(c['name'], ' '.join(str(c.get('description') or c.get('title') or '').split()))
            for c in scoped_capabilities()]


def instruction(caps):
    return ('You choose which capability an assistant should call first. The assistant can act only through the '
            'capabilities below. Choose the one capability the assistant would use as the first step to fulfil '
            'the request completely, using only listed capabilities. If the listed capabilities cannot fulfil the '
            f'request completely, choose {OOS}. Answer with JSON {{"label": "<label>"}}.\n\nCapabilities:\n'
            + '\n'.join(f'- {n}: {d}' for n, d in caps)
            + f'\n- {OOS}: the listed capabilities cannot fulfil the request completely')


def schema(caps):
    return {'type': 'object', 'additionalProperties': False, 'required': ['label'],
            'properties': {'label': {'type': 'string', 'enum': [n for n, _ in caps] + [OOS]}}}


def applies(decision, source):
    return source == 'local' and decision.intent not in ACTING_EXCLUDED


async def gate(db, text):
    """{'label', 'seconds', ...}; 'label' is None when the call failed."""
    from . import local_structured
    caps = capabilities()
    record = {'capabilities': len(caps)}
    t0 = time.monotonic()
    try:
        raw, usage = await local_structured(db, [{'role': 'system', 'content': instruction(caps)},
                                                 {'role': 'user', 'content': text}],
                                            schema(caps), purpose='intelligence.capability-gate', max_tokens=40)
        label = json.loads(raw)['label']
        record.update(label=label if label in {n for n, _ in caps} | {OOS} else None,
                      input_tokens=usage.get('prompt_eval_count'), output_tokens=usage.get('eval_count'))
    except Exception as exc:                                       # noqa: BLE001
        record.update(label=None, error=f'{type(exc).__name__}: {exc}'[:300])
    record['seconds'] = round(time.monotonic() - t0, 4)
    return record


def apply(decision, record):
    """The router decision after the gate: OUT_OF_SCOPE when the gate says so, otherwise unchanged."""
    if record.get('label') == OOS:
        return decision.model_copy(update={
            'intent': OOS, 'tool': 'none',
            'reason': ('Capability gate: no registered capability fulfils this request completely. '
                       'Router said: ' + decision.reason)[:600]})
    return decision
