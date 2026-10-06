"""ARIES's eyes. The check that matters is that the frame is not a black rectangle.

Nothing here is allowed to need a particular window open, or the screen awake:
this machine blanks after 60 s of idle and a blanked screen is exactly the case
the capability has to refuse. So the live tests assert the refusal when the
screen is dark and the capture when it is not, and both are real assertions.

The window path is exercised against a synthetic window whose rectangle is a
real region of this screen. That keeps the crop arithmetic under test without
making the suite depend on the desktop bridge, or on anything being open.
"""
import os
import struct
import sys
import time
import zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-screen')
import numpy as np
from aries.operator import desktop
from aries.workspace import screen_capabilities as screen


def _png(pixels: np.ndarray) -> bytes:
    """A minimal RGBA PNG, so a frame with known content can be made on demand."""
    height, width = pixels.shape[:2]
    raw = b''.join(b'\x00' + pixels[y].tobytes() for y in range(height))

    def chunk(kind, payload):
        return (struct.pack('>I', len(payload)) + kind + payload
                + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 6)) + chunk(b'IEND', b''))


def _store(name, pixels):
    screen.CAPTURES.mkdir(parents=True, exist_ok=True)
    path = screen.CAPTURES / name
    path.write_bytes(_png(pixels))
    return path


def test_a_uniform_frame_is_a_failure_not_a_result():
    black = np.zeros((64, 64, 4), dtype=np.uint8)
    black[:, :, 3] = 255
    measured = screen.content(black)
    check('an all-black frame measures as uniform', measured['uniform'])
    check('and its deviation is reported as zero', measured['intensity_deviation'] == 0.0)
    white = np.full((64, 64, 4), 255, dtype=np.uint8)
    check('an all-white frame is uniform too — a flat frame is never an answer',
          screen.content(white)['uniform'])
    real = np.random.default_rng(7).integers(0, 256, (64, 64, 4), dtype=np.uint8)
    varied = screen.content(real)
    check('a frame with content is not uniform', not varied['uniform'])
    check('and reports more than one distinct colour', varied['distinct_colours_sampled'] > 1)


async def test_a_stored_black_frame_fails_verification():
    path = _store('screen-test-black.png', np.zeros((80, 80, 4), dtype=np.uint8))
    try:
        fresh = screen.inspect(path)
        check('a stored black frame re-reads as uniform', fresh['content']['uniform'])
        claim = {'path': str(path), 'width': 80, 'height': 80, 'bytes': fresh['bytes'],
                 'sha256': fresh['sha256'], 'scope': 'whole screen'}
        verdict = await screen.verify_capture({}, claim, {})
        check('and the verifier refuses it even though every byte matches the claim', not verdict['met'])
        claim['sha256'] = '0' * 64
        check('a changed file fails verification as well',
              not (await screen.verify_capture({}, claim, {}))['met'])
    finally:
        path.unlink(missing_ok=True)


def test_only_aries_own_captures_can_be_inspected():
    try:
        screen.inspect('/etc/hostname')
        check('reading an arbitrary path as a capture is refused', False)
    except screen.ScreenError as exc:
        check('reading an arbitrary path as a capture is refused', exc.code == 'NON_RETRYABLE')


def test_retention_is_bounded_and_private():
    original = screen.CAPTURES
    scratch = Path(os.environ.get('TMPDIR', '/tmp')) / ('aries-screen-retention-%d' % os.getpid())
    screen.CAPTURES = scratch
    try:
        scratch.mkdir(parents=True, exist_ok=True)
        for index in range(12):
            frame = scratch / ('screen-%02d.png' % index)
            frame.write_bytes(b'x')
            os.utime(frame, (time.time() - index, time.time() - index))
        stale = scratch / 'screen-stale.png'
        stale.write_bytes(b'x')
        os.utime(stale, (time.time() - 4000, time.time() - 4000))
        removed = screen.prune()
        kept = sorted(p.name for p in scratch.glob('screen-*.png'))
        check('pruning keeps at most the configured number of frames', len(kept) == screen.KEEP_FILES)
        check('it keeps the newest ones', kept == ['screen-%02d.png' % i for i in range(screen.KEEP_FILES)])
        check('an over-age frame is gone regardless of count', not stale.exists())
        check('and the count of removals is reported', removed['removed'] == 13 - screen.KEEP_FILES)
        destination = screen._destination()
        check('a new capture path is inside the ARIES-owned directory', destination.parent == scratch)
        check('that directory is private to this user', oct(scratch.stat().st_mode & 0o777) == '0o700')
    finally:
        screen.CAPTURES = original
        for frame in scratch.glob('*'):
            frame.unlink(missing_ok=True)
        scratch.rmdir()


def test_the_screenshot_door_that_opens_here():
    state = screen.available()
    check('the desktop screenshot portal answers: ' + str(state['portal']),
          state['portal'] == 'org.freedesktop.portal.Screenshot')
    check('a captured frame can be decoded and measured: ' + str(state['decoder']),
          state['decoder'] == 'gdk-pixbuf')
    check('the display layout is readable, which is what a window crop needs',
          bool(screen.monitors()['monitors']))
    # OCR is optional to the capture and reported either way; what is forbidden
    # is a screen.read that quietly answers nothing.
    if str(state['ocr']).startswith('unavailable'):
        try:
            screen.read()
            check('screen.read refuses rather than returning empty text', False)
        except screen.ScreenError as exc:
            check('screen.read refuses with the command that fixes it',
                  exc.code == 'CAPABILITY_UNAVAILABLE' and 'traineddata' in str(exc))
    else:
        check('local OCR is present: ' + str(state['ocr']), 'tesseract' in str(state['ocr']))
        try:
            screen.read(language='deu')
            check('an unsupported OCR language is refused, not passed to the C API', False)
        except screen.ScreenError as exc:
            check('an unsupported OCR language is refused, not passed to the C API',
                  exc.code == 'NON_RETRYABLE')


async def test_capture_and_read_this_screen():
    monitors = screen.monitors()['monitors']
    expected = (max(m['x'] + m['logical_width'] for m in monitors),
                max(m['y'] + m['logical_height'] for m in monitors))
    try:
        shot = screen.capture()
    except screen.ScreenError as exc:
        # Not a pass by omission: the refusal is the behaviour under test here.
        check('skipped — the screen is blanked, and capture refused instead of storing a black frame: '
              + exc.code, exc.code == 'TRANSIENT' and 'blanked' in str(exc))
        return
    try:
        check('the capture is stored under ARIES\'s own directory',
              Path(shot['path']).parent == screen.CAPTURES)
        check('only this user can read it', oct(Path(shot['path']).stat().st_mode & 0o777) == '0o600')
        check('it has real dimensions, matching this display layout: %dx%d' % (shot['width'], shot['height']),
              (shot['width'], shot['height']) == expected)
        check('it has real bytes on disk: %d' % shot['bytes'],
              shot['bytes'] > 1000 and shot['bytes'] == Path(shot['path']).stat().st_size)
        check('it is not a uniform rectangle (deviation %.2f over %d sampled colours)'
              % (shot['content']['intensity_deviation'], shot['content']['distinct_colours_sampled']),
              not shot['content']['uniform'])
        check('the portal is named as the source, not guessed at', 'portal' in shot['source'])
        verdict = await screen.verify_capture({}, shot, {})
        check('an independent re-read of the file verifies it', verdict['met'])
        if str(screen.available()['ocr']).startswith('unavailable'):
            check('skipped — no local OCR, so no text to check', True)
            return
        out = screen.read()
        try:
            check('OCR recovered text from the screen: %d characters, %d words, confidence %d'
                  % (out['characters'], out['words'], out['mean_confidence']),
                  out['characters'] > 0 and out['mean_confidence'] > 0)
            check('the text belongs to the frame the result points at',
                  Path(out['capture']['path']).is_file() and not out['capture']['content']['uniform'])
            read_verdict = await screen.verify_read({}, out, {})
            check('and it verifies against a re-read of that frame', read_verdict['met'])
            titles = read_verdict['data']['window_titles']
            check('window titles cross-check: ' + str(titles),
                  titles['checked'] is False or titles['found'] >= 0)
        finally:
            Path(out['capture']['path']).unlink(missing_ok=True)
    finally:
        # A test leaves no pictures of the person's screen behind.
        Path(shot['path']).unlink(missing_ok=True)


async def test_a_window_capture_needs_an_observed_id():
    real = desktop.read_windows
    found = screen.monitors()['monitors']
    rect = next((m for m in found if m['primary']), found[0])
    # A quarter inset on the monitor it belongs to, so the rectangle is genuinely
    # on screen whatever this machine's layout turns out to be.
    inside = {'x': rect['x'] + rect['logical_width'] // 4, 'y': rect['y'] + rect['logical_height'] // 4,
              'width': rect['logical_width'] // 2, 'height': rect['logical_height'] // 2}

    def window(**changed):
        return desktop.Window(**{'id': 'aries-synthetic', 'title': 'ARIES synthetic target', 'wm_class': 'test',
                                 'app_id': 'test.desktop', 'pid': os.getpid(), 'focused': True, 'workspace': 0,
                                 'minimised': False, 'maximized': False, 'geometry': inside, 'monitor': 0,
                                 **changed})
    try:
        desktop.read_windows = lambda: (None, 'the desktop bridge is not answering', None)
        try:
            screen.capture('aries-synthetic')
            check('without a window list, a window capture is refused', False)
        except screen.ScreenError as exc:
            check('without a window list, a window capture is refused and says why',
                  exc.code == 'CAPABILITY_UNAVAILABLE' and 'bridge' in str(exc))

        desktop.read_windows = lambda: ([window()], '', None)
        try:
            screen.capture('not-an-observed-id')
            check('an unobserved window ID is refused', False)
        except screen.ScreenError as exc:
            check('an unobserved window ID is refused', exc.code == 'TARGET_NOT_FOUND')

        for label, changed, reason in (
                ('a minimised window occupies no pixels', {'minimised': True}, 'minimised'),
                ('a window with no reported geometry cannot be located', {'geometry': None}, 'geometry'),
                ('an off-screen window is refused rather than clamped to nothing',
                 {'geometry': {'x': 30000, 'y': 30000, 'width': 100, 'height': 100}}, 'outside')):
            desktop.read_windows = lambda c=changed: ([window(**c)], '', None)
            try:
                screen.capture('aries-synthetic')
                check(label, False)
            except screen.ScreenError as exc:
                check(label, reason in str(exc))

        desktop.read_windows = lambda: ([window()], '', None)
        try:
            shot = screen.capture('aries-synthetic')
        except screen.ScreenError as exc:
            check('skipped — the screen is blanked, so there is no region to cut: ' + exc.code,
                  exc.code == 'TRANSIENT')
            return
        try:
            check('the crop is exactly the window rectangle in device pixels: %dx%d'
                  % (shot['width'], shot['height']),
                  (shot['width'], shot['height']) == (inside['width'], inside['height']))
            check('the region it cut is reported, in both coordinate systems',
                  shot['region']['logical'] == inside and shot['region']['scale'] == rect['scale'])
            check('it says what a screen-area crop can and cannot claim', 'occupied' in shot['region']['covers'])
            check('the cropped frame has real content, not a blank rectangle',
                  not shot['content']['uniform'])
            check('a window capture keeps no copy of the whole screen', shot['scope'] == 'window'
                  and shot['bytes'] == Path(shot['path']).stat().st_size)
            check('and it verifies against a re-read of the stored crop',
                  (await screen.verify_capture({}, shot, {}))['met'])
        finally:
            Path(shot['path']).unlink(missing_ok=True)
    finally:
        desktop.read_windows = real


def test_the_capability_surface():
    class Recorder:
        def __init__(self):
            self.items = {}

        def register(self, capability):
            if capability.name in self.items:
                raise ValueError('Duplicate capability: ' + capability.name)
            self.items[capability.name] = capability

    recorder = Recorder()
    screen.register(recorder)
    check('screen.capture, screen.screenshot and screen.read are registered',
          set(recorder.items) == {'screen.capture', 'screen.screenshot', 'screen.read'})
    for name, capability in recorder.items.items():
        check(name + ' is an observation, so it needs no operator approval',
              capability.effect == 'read' and not capability.requires_approval)
        check(name + ' is marked as more than low risk, because a frame can hold anything',
              capability.risk_level == 'medium')
        described = capability.describe()['input_schema']['properties']
        check(name + ' targets a window by observed ID only', 'window_id' in described)
    read = recorder.items['screen.read'].input_model
    check('OCR reads Macedonian and English by default', read.model_validate({}).language == 'eng+mkd')
    try:
        read.model_validate({'language': 'deu'})
        check('an unlisted OCR language is rejected by the schema', False)
    except Exception:
        check('an unlisted OCR language is rejected by the schema', True)
    try:
        read.model_validate({'window_id': ''})
        check('an empty window ID is rejected by the schema', False)
    except Exception:
        check('an empty window ID is rejected by the schema', True)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
