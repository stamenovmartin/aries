"""Opt-in synthetic screen environment; never opens a portal or reads windows.

Faults enter AFTER the capture executor's own defensive checks. This is a
different intervention from the native portal shim and must be analysed apart.
The native PNG verifier is exercised, but this is not a live capture benchmark.
"""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path
import subprocess

from case_tools import NativeCase, PreconditionUnavailable


class ControlledScreenCase(NativeCase):
    def __init__(self, case_id, registry, report, scratch):
        super().__init__(case_id, registry, report)
        if not self.target.startswith('screen.'):
            raise ValueError('--controlled-screen requires a screen case')
        self.directory = Path(scratch) / 'controlled-screen'
        self.directory.mkdir()
        self.frames = ['fixture-frame-1', 'fixture-frame-2'] if case_id == 'vf-11' else ['fixture-frame-1']
        self.allowed = [{'window_id': frame, **({'language': 'eng'} if self.target == 'screen.read' else {})}
                        for frame in self.frames]
        self.arguments[self.target] = self.allowed if len(self.allowed) > 1 else self.allowed[0]
        report.update(case_surface='controlled_screen_fixture', production_capture_path=False,
                      fault_layer='returned_artifact_after_capture_defences',
                      comparison_admission=False,
                      limitation='Artifact validity is checked; final visual-description correctness is not scored. '
                                 'Do not pool with native portal intervention or launch the study from preflight alone.')

    @contextmanager
    def scope(self):
        from aries.workspace import screen_capabilities as screen
        previous = screen.CAPTURES
        screen.CAPTURES = self.directory
        try:
            yield screen
        finally:
            screen.CAPTURES = previous

    def artifact(self, frame, corrupt):
        with self.scope() as screen:
            path = self.directory / (('bad-' if corrupt else '') + frame + '.png')
            capture = screen.inspect(path)
            capture.update(scope='owned_synthetic_scene', method='controlled fixture; no desktop capture')
            if self.target != 'screen.read':
                return capture
            handle = screen._load(path)
            try:
                pixels, buffer, stride = screen._view(handle)
                return {**screen._text(pixels, buffer, stride, 'eng'), 'capture': capture}
            finally:
                screen._release(handle)

    async def verify(self, arguments, result, ctx):
        with self.scope() as screen:
            if self.target != 'screen.read':
                return await screen.verify_capture(arguments, result, ctx)
            # The live OCR verifier reads window titles. Never inspect personal
            # windows here: perform a fresh OCR read of the owned artifact instead.
            fresh = self.artifact(arguments['window_id'], corrupt=result['capture']['content']['uniform'])
            met = bool(not fresh['capture']['content']['uniform'] and fresh['characters']
                       and fresh['mean_confidence'] > 0 and fresh['text'] == result['text'])
            return {'met': met, 'type': 'controlled_screen_text', 'data': fresh}

    async def preflight(self, db):
        # Pillow belongs to system Python, not the application venv. No install.
        script = '''import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
root = Path(sys.argv[1])
font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 42)
for i in (1, 2):
    image = Image.new('RGB', (960, 540), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 940, 100), fill=(30, 60, 130))
    draw.text((50, 160), 'ARIES TEST FRAME ' + str(i), fill='black', font=font)
    draw.text((50, 260), 'VALUE ' + str(17 if i == 1 else 29), fill='black', font=font)
    image.save(root / ('fixture-frame-' + str(i) + '.png'))
    Image.new('RGB', (960, 540), (int(sys.argv[2]),)*3).save(root / ('bad-fixture-frame-' + str(i) + '.png'))
'''
        try:
            subprocess.run(['/usr/bin/python3', '-c', script, str(self.directory),
                            '127' if self.row['id'] == 'vf-10' else '0'], check=True,
                           capture_output=True, timeout=20)
            checks = []
            self.expected_hashes = {}
            for args in self.allowed:
                frame = args['window_id']
                path = self.directory / (frame + '.png')
                self.expected_hashes[frame] = hashlib.sha256(path.read_bytes()).hexdigest()
                good, bad = self.artifact(frame, False), self.artifact(frame, True)
                good_check = await self.verify(args, good, {})
                bad_check = await self.verify(args, bad, {})
                if not good_check['met'] or bad_check['met']:
                    raise ValueError('Known valid/invalid image discrimination failed')
                if self.target == 'screen.read' and 'VALUE 17' not in good['text']:
                    raise ValueError('Known English scene text was not recovered')
                checks.append({'frame': frame, 'valid_accepted': True, 'corrupt_rejected': True,
                               'expected_sha256': self.expected_hashes[frame]})
            for name, cap in self.original.items():
                if name != self.target:
                    self.before[name] = await cap.executor(self.arguments[name], {'db': db})
            self.report.update(preflight_passed=True, controlled_scene_checks=checks,
                               preflight_scope='Image decoding, OCR where applicable, and verifier discrimination; no planner')
        except Exception as exc:
            raise PreconditionUnavailable(f'Controlled screen: {type(exc).__name__}: {exc}') from exc

    @property
    def requirements(self):
        return ([{'capability': self.target, 'window_id': frame} for frame in self.frames]
                + [{'capability': name} for name in self.original if name != self.target])

    def capabilities(self):
        caps = super().capabilities()

        async def execute(arguments, ctx):
            if arguments not in self.allowed:
                raise PermissionError('Only explicitly named synthetic frames are accessible')
            value = self.artifact(arguments['window_id'], True)
            self.executions.append({'capability': self.target, 'args': arguments, 'result': value})
            self.report['fault_reached'] = True
            self.report['injection_events'].append({'tool': 'controlled_image_return',
                                                   'frame': arguments['window_id'], 'fault': self.row['fault']})
            return value

        caps[self.target] = replace(self.original[self.target], executor=execute, verifier=self.verify,
                                    description='Observe an explicitly named frame in the owned synthetic screen scene. '
                                                'This experimental capability never accesses the physical desktop.')
        return caps

    async def smoke(self, db):
        cap = self.capabilities()[self.target]
        checks = []
        for arguments in self.allowed:
            validated = cap.input_model.model_validate(arguments).model_dump()
            result = await cap.executor(validated, {'db': db})
            verdict = await cap.verifier(validated, result, {'db': db})
            oracle = await self.oracle({'steps': []}, db)
            if verdict['met'] is not False or oracle is not False:
                raise AssertionError('Injected fixture must fail verifier and independent oracle')
            checks.append({'frame': arguments['window_id'], 'verifier_met': verdict['met'],
                           'oracle_met': oracle, 'executor_returned': True})
        self.report['controlled_executor_checks'] = checks

    async def oracle(self, current, db):
        # Independent authored-file hash, not the verifier's met bit. A bad
        # observation cannot establish the requested scene, even if a model guesses.
        for frame in self.frames:
            values = [e['result'] for e in self.executions if e['capability'] == self.target
                      and e['args']['window_id'] == frame]
            captures = [v['capture'] if self.target == 'screen.read' else v for v in values]
            valid = any(hashlib.sha256(Path(v['path']).read_bytes()).hexdigest()
                        == self.expected_hashes[frame] for v in captures)
            self.report['oracle_reads'].append({'frame': frame, 'met': valid,
                                               'predicate': 'obtained authored scene image'})
            if not valid:
                return False
        # Valid pixels alone do not prove a correct natural-language description.
        return None

    def answer_oracle(self, answer):
        from answer_oracle import screen_answer
        result = screen_answer(answer, frames=[int(frame.rsplit('-', 1)[1]) for frame in self.frames])
        result['scope'] = 'screen answer content only; not observation provenance or auxiliary subgoals'
        return result
