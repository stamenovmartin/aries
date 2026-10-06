"""Native read-only fixture adapters. Faults never patch the oracle or verifier.

Screen cases deliberately fail preflight until a known owned desktop scene is
available; no personal screenshots, session-lock bypasses or fabricated success.
"""
from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'experiments/verification-feedback/fixture.jsonl'


def cases():
    return {row['id']: row for row in (json.loads(x) for x in FIXTURE.read_text().splitlines() if x.strip())}


class PreconditionUnavailable(RuntimeError):
    pass


def facts(name, value):
    """Only task-relevant, time-stable fields; never verification_status."""
    if not isinstance(value, dict):
        return None
    if name == 'system.service':
        keys = ('unit', 'scope', 'load_state', 'active_state', 'sub_state')
        return {k: value.get(k) for k in keys}
    if name == 'network.status':
        primary = value.get('primary') or {}
        return {'link_up': value.get('link_up'), 'internet_reachable': value.get('internet_reachable'),
                'primary': {k: primary.get(k) for k in ('device', 'type', 'state', 'connection')}}
    if name == 'network.wifi_list':
        return sorted((r.get('ssid') or '', bool(r.get('in_use'))) for r in value.get('networks', []))
    # Unaffected numerical readings vary naturally; preserve observed values in the
    # artifact, compare available metric identities against an independent read.
    rows = value.get('filesystems', [])
    if name == 'system.status':
        rows = [r for p in value.get('probes', []) for r in p.get('readings', [])]
    return sorted((r.get('metric', ''), str(r.get('subject', '')))
                  for r in rows if type(r.get('value')) in (int, float))


class NativeCase:
    def __init__(self, case_id, registry, report):
        self.row = cases()[case_id]
        self.report = report
        self.target = self.row['reaches']
        self.unit = {'vf-01': 'aries-core', 'vf-02': 'aries-voice', 'vf-03': 'ollama',
                     'vf-04': 'aries-endurance.timer', 'vf-12': 'aries-core',
                     'vf-15': 'aries-core'}.get(case_id)
        names = [self.target]
        if case_id == 'vf-13':
            names.append('system.storage')
        if case_id in ('vf-14', 'vf-15'):
            names.append('system.status')
        self.original = {name: registry.get(name) for name in names}
        self.arguments = {name: ({'unit': self.unit, 'scope': 'user'} if name == 'system.service' else {})
                          for name in names}
        self.executions = []
        self.before = {}
        self.report.update(case_id=case_id, fixture_fault=self.row['fault'],
                           injection_events=[], oracle_reads=[], case_surface='native_read_only')

    @property
    def requirements(self):
        # Separate predicate below also checks the named unit; the production
        # contract matcher does not understand a unit field.
        return [{'capability': name} for name in self.original]

    async def preflight(self, db):
        if self.target.startswith('screen.'):
            raise PreconditionUnavailable('Controlled known desktop scene not supplied; no personal capture or lock bypass')
        for name, cap in self.original.items():
            try:
                self.before[name] = await cap.executor(self.arguments[name], {'db': db})
            except Exception as exc:
                raise PreconditionUnavailable(f'{name}: {type(exc).__name__}: {exc}') from exc
        if self.target == 'network.wifi_list' and not self.before[self.target].get('networks'):
            raise PreconditionUnavailable('No visible wifi networks: an injected empty list would not establish a contradiction')
        if self.row['id'] == 'vf-07' and (self.before[self.target].get('primary') or {}).get('type') != 'wifi':
            raise PreconditionUnavailable('Goal requests an active wifi connection; observed primary is not wifi')
        self.report['preflight_passed'] = True

    @contextmanager
    def inject(self):
        sys.path.insert(0, str(ROOT / 'eval/agent_suite'))
        import faults
        from aries.workspace import system_capabilities, network_capabilities
        module = system_capabilities if self.target == 'system.service' else network_capabilities
        with faults.open_fault(self.row['fault']) as description:
            patched = module._run
            def record(argv):
                reached = ('show' in argv) if self.target == 'system.service' else bool(argv and argv[0] == 'nmcli')
                if reached:
                    self.report['fault_reached'] = True
                    self.report['injection_events'].append({'tool': argv[0], 'fault': self.row['fault']})
            if self.target == 'system.service':
                async def watched(argv, timeout=12):
                    record(argv)
                    return await patched(argv, timeout)
            else:
                def watched(argv, timeout=8):
                    record(argv)
                    return patched(argv, timeout)
            module._run = watched
            try:
                yield description
            finally:
                module._run = patched
        # open_fault's finally now restores the ORIGINAL function. The agent
        # invokes the verifier only after the wrapped executor returns.

    def capabilities(self):
        result = {}
        for name, cap in self.original.items():
            async def execute(arguments, ctx, name=name, cap=cap):
                validated = cap.input_model.model_validate(self.arguments[name]).model_dump()
                if arguments != validated:
                    raise PermissionError('Fixture permits only its exact read-only target arguments')
                event = {'capability': name, 'args': arguments, 'result': None}
                self.executions.append(event)
                try:
                    if name == self.target:
                        with self.inject():
                            value = await cap.executor(arguments, ctx)
                    else:
                        value = await cap.executor(arguments, ctx)
                    event['result'] = value
                    return value
                except Exception as exc:
                    event['error'] = {'type': type(exc).__name__, 'code': getattr(exc, 'code', None)}
                    raise
            result[name] = replace(cap, executor=execute)
        return result

    async def oracle(self, current, db):
        met = True
        for name, cap in self.original.items():
            try:
                fresh = await cap.executor(self.arguments[name], {'db': db})
                observed = facts(name, fresh)
                if observed != facts(name, self.before[name]):
                    self.report['environment_drift'] = True
                candidates = [e['result'] for e in self.executions
                              if e['capability'] == name and e.get('result') is not None]
                # A verifier may itself obtain the requested reading. Recheck its
                # DATA against the external observation, never trust its met flag.
                candidates += [s.get('verification', {}).get('data') for s in current['steps']
                               if s.get('capability') == name and s.get('verification', {}).get('data')]
                valid = bool(observed) and any(facts(name, candidate) == observed for candidate in candidates)
                self.report['oracle_reads'].append({'capability': name, 'met': valid, 'facts': observed})
                met &= valid
            except Exception as exc:
                self.report['oracle_unavailable'] = f'{type(exc).__name__}: {exc}'
                return None
        return met
