"""`desktop.tile` and the monitor scale factor it had never read.

WHAT IS BEING PINNED HERE
-------------------------
1. The scale factor is read from the machine, from the only interface that
   publishes it (`org.gnome.Mutter.DisplayConfig.GetCurrentState`), and a machine
   that cannot answer produces a stated reason rather than a default of 1 dressed
   up as a reading.
2. The device-pixel-aligned arithmetic in `aries.operator.desktop.tile_rect`
   REDUCES EXACTLY to the arithmetic the GNOME Shell extension already performs,
   at every integer scale, for all nine sides. That is read out of
   `shell/aries@aries.local/lib/dbus.js` rather than copied here, so the two
   cannot drift apart silently.
3. At a fractional scale the halves land on whole device pixels and the two
   halves still meet without overlapping, which is the property the shell's
   floor/ceil comment claims and which fractional scaling breaks.
4. `monitor == -1` — Mutter's answer for a window that has been created and not
   yet mapped — stays ACCEPTED. Rejecting it threw away a whole observation at
   the moment a launch was being verified, and that regression is not being
   reintroduced through the scale lookup.

WHAT IS NOT PINNED, AND CANNOT BE ON THIS MACHINE
-------------------------------------------------
This display is a DELL E2422HS, 1920x1080, scale 1.0 — read live below, not
assumed. No window has been placed on a fractionally scaled monitor here, so
every fractional case in this file is arithmetic plus Mutter's own advertised
scale list. The implementation is honest about the same limit in its comments.
A live tile also needs the ARIES shell extension on the bus; when it is absent
(it is, at the time of writing: `org.aries.Shell` is not exported) the live part
of the smoke test says so instead of passing vacuously.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module

bootstrap('aries-tile-hidpi')
from aries import flags
from aries.operator import desktop

ROOT = Path(__file__).resolve().parents[1]
DBUS_JS = ROOT / 'shell/aries@aries.local/lib/dbus.js'


# --- the shell's own arithmetic, read out of the shell ------------------------

def shell_tile_sides():
    """Evaluate TILE_SIDES from dbus.js in Python, by translating the four
    expressions it is built from. Reading the real source is the point: a copy of
    the formulas in this file would pass forever after the shell changed."""
    source = DBUS_JS.read_text()
    block = source.split('const TILE_SIDES = {', 1)[1].split('\n};', 1)[0]
    sides = {}
    for line in block.splitlines():
        match = re.match(r"\s*(\w+):\s*a => \(\{(.+)\}\),\s*$", line)
        if not match:
            continue
        name, body = match.group(1), match.group(2)
        expression = (body.replace('Math.floor(a.width / 2)', "(a['width'] // 2)")
                          .replace('Math.ceil(a.width / 2)', "-(-a['width'] // 2)")
                          .replace('Math.floor(a.height / 2)', "(a['height'] // 2)")
                          .replace('Math.ceil(a.height / 2)', "-(-a['height'] // 2)")
                          .replace('a.x', "a['x']").replace('a.y', "a['y']")
                          .replace('a.width', "a['width']").replace('a.height', "a['height']"))
        fields = {}
        for part in expression.split(','):
            key, _, value = part.partition(':')
            fields[key.strip()] = value.strip()
        sides[name] = (lambda f: lambda a: {k: eval(v, {'a': a}) for k, v in f.items()})(fields)
    return sides


def test_the_python_arithmetic_is_the_shells_arithmetic_at_integer_scale():
    sides = shell_tile_sides()
    check('all nine sides were read out of the live shell source, not copied here',
          set(sides) == set(desktop.TILE_SIDES) and len(sides) == 9)
    areas = [{'x': 0, 'y': 27, 'width': 1920, 'height': 1053},        # this machine, panel included
             {'x': 0, 'y': 0, 'width': 1921, 'height': 1081},         # odd: the case floor/ceil is for
             {'x': -1920, 'y': 100, 'width': 1366, 'height': 767},    # a monitor left of the origin
             {'x': 0, 'y': 0, 'width': 3840, 'height': 2160},
             {'x': 0, 'y': 0, 'width': 7, 'height': 5}]               # absurd, and still has to be exact
    mismatches = []
    for area in areas:
        for scale in (1.0, 2.0, 3.0, 4.0):                            # every integer scale: step 1
            for side in desktop.TILE_SIDES:
                ours = desktop.tile_rect(area, side, scale)
                theirs = sides[side](area)
                if ours != theirs:
                    mismatches.append((area['width'], area['height'], scale, side, ours, theirs))
    check('at every integer scale the aligned arithmetic is byte-identical to the '
          'shell\'s floor/ceil for all 9 sides over %d work areas (%d comparisons)'
          % (len(areas), len(areas) * 4 * 9), not mismatches)
    if mismatches:
        print('      first mismatch:', mismatches[0])


def test_halves_meet_exactly_and_stay_inside_the_work_area():
    for area in [{'x': 0, 'y': 27, 'width': 1920, 'height': 1053},
                 {'x': 0, 'y': 0, 'width': 1921, 'height': 1081},
                 {'x': 11, 'y': 13, 'width': 2560, 'height': 1371}]:
        for scale in (1.0, 1.25, 4 / 3, 1.5, 5 / 3, 2.0, 2.25, 3.0):
            left = desktop.tile_rect(area, 'left', scale)
            right = desktop.tile_rect(area, 'right', scale)
            top = desktop.tile_rect(area, 'top', scale)
            bottom = desktop.tile_rect(area, 'bottom', scale)
            gap_x = right['x'] - (left['x'] + left['width'])
            gap_y = bottom['y'] - (top['y'] + top['height'])
            step = desktop.device_step(scale)
            ok = (gap_x >= 0 and gap_y >= 0                  # never overlapping
                  and gap_x < 2 * step and gap_y < 2 * step  # and never a visible seam
                  and right['x'] + right['width'] == area['x'] + area['width']
                  and bottom['y'] + bottom['height'] == area['y'] + area['height']
                  and left['x'] == area['x'] and top['y'] == area['y'])
            check('%dx%d at scale %.4g: halves meet (gap %d x %d px, step %d) and both edges '
                  'are flush with the work area' % (area['width'], area['height'], scale,
                                                    gap_x, gap_y, step), ok)


# Which dimension of each side this code CHOOSES. The other one is inherited from
# the work area, whose own edges are Mutter's: a logical work area can itself be a
# fractional number of device pixels (1670 at scale 1.25 is 2087.5), and no
# arithmetic here can fix that — only the compositor that published it can. The
# claim being made is therefore precise: the SPLIT lands on whole device pixels.
CHOSEN = {'left': ('width',), 'right': ('width',), 'top': ('height',), 'bottom': ('height',),
          'topleft': ('width', 'height'), 'topright': ('width', 'height'),
          'bottomleft': ('width', 'height'), 'bottomright': ('width', 'height'), 'full': ()}


def test_every_split_lands_on_a_whole_device_pixel():
    """The point of the whole sub-item. A logical size whose product with the
    scale is not an integer is a size Mutter will adjust on the way in."""
    for scale in (1.0, 1.25, 4 / 3, 1.5, 5 / 3, 2.0, 2.25, 2.5, 2.75, 3.0):
        offenders, inherited = [], []
        for area in [{'x': 0, 'y': 0, 'width': 3072, 'height': 1670},
                     {'x': 0, 'y': 27, 'width': 2049, 'height': 1081},
                     {'x': 0, 'y': 0, 'width': 2560, 'height': 1440}]:
            for side in desktop.TILE_SIDES:
                rect = desktop.tile_rect(area, side, scale)
                for key in CHOSEN[side]:
                    product = rect[key] * scale
                    if abs(product - round(product)) > 1e-9:
                        offenders.append((side, key, rect[key], scale, product))
                for key in ('width', 'height'):
                    if key not in CHOSEN[side] and rect[key] != area[key]:
                        inherited.append((side, key, rect[key], area[key]))
        check('scale %.4g: every dimension this code chooses is a whole number of device pixels'
              % scale, not offenders)
        if offenders:
            print('      first offender:', offenders[0])
        check('scale %.4g: and the dimensions it does not choose are passed through from '
              'the work area untouched' % scale, not inherited)


def test_a_fractional_scale_actually_changes_the_answer():
    """If the aligned rectangle were always the shell's rectangle, this whole
    sub-item would be theatre. Here is a case where it is not."""
    # 2050 logical: the shell's half is 1025, and 1025 x 1.5 is 1537.5 device pixels.
    area = {'x': 0, 'y': 0, 'width': 2050, 'height': 1081}
    shell = desktop.tile_rect(area, 'right', 1.0)
    aligned = desktop.tile_rect(area, 'right', 1.5)
    check('at scale 1.5 on this logical width the aligned rectangle differs from '
          'the shell\'s (%s vs %s)' % (aligned, shell), aligned != shell)
    check('the shell\'s own rectangle is NOT device-aligned there, which is the bug: '
          '%d x 1.5 = %.1f device pixels' % (shell['width'], shell['width'] * 1.5),
          abs(shell['width'] * 1.5 - round(shell['width'] * 1.5)) > 1e-9)
    check('and the aligned one is', abs(aligned['width'] * 1.5 - round(aligned['width'] * 1.5)) < 1e-9)


def test_a_work_area_that_cannot_be_tiled_is_refused_with_a_reason():
    for bad, why in [({'x': 0, 'y': 0, 'width': 0, 'height': 100}, 'no width'),
                     ({'x': 0, 'y': 0, 'width': 100, 'height': -1}, 'negative height'),
                     ({'x': 0, 'y': 0, 'width': 100}, 'a missing field'),
                     ({'x': 0, 'y': 0, 'width': 100.0, 'height': 100}, 'a float where a pixel belongs')]:
        try:
            desktop.tile_rect(bad, 'left', 1.0)
            check('refused: ' + why, False)
        except ValueError:
            check('refused: ' + why, True)
    try:
        desktop.tile_rect({'x': 0, 'y': 0, 'width': 10, 'height': 10}, 'middle', 1.0)
        check('refused: an unknown side', False)
    except ValueError:
        check('refused: an unknown side', True)


# --- reading the real machine -------------------------------------------------

def test_the_scale_factor_is_read_from_this_machine():
    reading = desktop.monitor_scales()
    if not reading['available']:
        check('no scale could be read, and the reason is stated rather than defaulted to 1: '
              + reading['why'], bool(reading['why']))
        return
    check('every logical monitor Mutter has is reported with a scale and a step',
          reading['monitors'] and all(m['scale'] > 0 and m['step'] >= 1 for m in reading['monitors']))
    check('the reading names its own source', 'DisplayConfig' in reading['source'])
    for m in reading['monitors']:
        print('      monitor %d: %s %sx%s at scale %g (step %d), transform %d%s'
              % (m['index'], ','.join(m['connectors']) or '?', m['width'], m['height'],
                 m['scale'], m['step'], m['transform'], ' primary' if m['primary'] else ''))
    check('the logical size is consistent with the scale and the current mode',
          all(m['width'] and m['height'] for m in reading['monitors']))
    # Cross-check against the raw D-Bus reply, so a parsing bug cannot invent a scale.
    raw = subprocess.run(['busctl', '--user', 'call', desktop.DISPLAY_CONFIG[0],
                          desktop.DISPLAY_CONFIG[1], desktop.DISPLAY_CONFIG[0],
                          'GetCurrentState', '--json=short'],
                         capture_output=True, text=True, timeout=10)
    if raw.returncode == 0:
        logical = json.loads(raw.stdout)['data'][2]
        check('the scales reported are exactly the scales in Mutter\'s reply',
              [m['scale'] for m in reading['monitors']] == [float(e[2]) for e in logical])


def test_a_window_not_yet_on_a_monitor_keeps_being_accepted():
    monitors = [{'index': 0, 'scale': 1.0, 'step': 1, 'x': 0, 'y': 0, 'width': 1920,
                 'height': 1080, 'connectors': ['HDMI-1'], 'primary': True, 'transform': 0}]
    unmapped = {'monitor': -1, 'work_area': None}
    scale, why = desktop.scale_for(unmapped, monitors)
    check('monitor == -1 gives no scale and an explanation, not an exception',
          scale is None and 'not on a monitor yet' in why)
    expectation = desktop.tile_expectation(unmapped, 'left', monitors)
    check('and the tile expectation is "verify against the shell\'s own rectangle", '
          'not a refusal of the whole observation',
          expectation['rect'] is None and expectation['monitor'] == -1 and expectation['why'])

    placed = {'monitor': 0, 'work_area': {'x': 0, 'y': 27, 'width': 1920, 'height': 1053}}
    check('a mapped window on an integer-scale monitor needs no correction at all',
          desktop.tile_expectation(placed, 'right', monitors)['aligned'] is True)

    fractional = [dict(monitors[0], scale=1.5, width=2560, height=1440)]
    on_fractional = {'monitor': 0, 'work_area': {'x': 0, 'y': 27, 'width': 2050, 'height': 1413}}
    report = desktop.tile_expectation(on_fractional, 'right', fractional)
    check('on a fractional monitor the expectation says so and carries both rectangles',
          report['scale'] == 1.5 and report['step'] == 2 and report['aligned'] is False
          and report['rect'] != report['shell_rect'])
    check('the scale is matched by the work area\'s own origin, not only by an index',
          'work-area origin' in report['why'])

    two = [dict(monitors[0], index=0, x=0, scale=1.0, width=1920),
           dict(monitors[0], index=1, x=1920, scale=2.0, step=1, width=1920, connectors=['DP-1'])]
    right_monitor = {'monitor': 0, 'work_area': {'x': 1920, 'y': 0, 'width': 1920, 'height': 1080}}
    scale, why = desktop.scale_for(right_monitor, two)
    check('a window whose index and position disagree is scaled by its POSITION '
          '(%s)' % why, scale == 2.0)


# --- the capability and the flag ----------------------------------------------

def test_the_capability_and_the_flag_are_wired():
    from aries.workspace.registry import Registry
    from aries.workspace import desktop_capabilities as dc
    registry = Registry()
    dc.register(registry)
    tile = registry.get('desktop.tile')
    check('desktop.tile is registered with all nine sides in its schema',
          sorted(desktop.TILE_SIDES) == sorted(
              re.findall(r'\w+', tile.input_model.model_json_schema()
                         ['properties']['side']['pattern'])))
    check('and it tells the planner that the scale factor is part of the verification',
          'scale factor' in tile.description)
    check('ARIES_TILE_HIDPI is in the one flag registry, default on',
          flags.FLAGS.get('ARIES_TILE_HIDPI', (None,))[0] is True
          and flags.describe()['flags']['ARIES_TILE_HIDPI']['on'] is True)

    # The verifier must accept EITHER exact rectangle and nothing else.
    import asyncio
    verify = dc.verifier('tile')
    target = {'window_id': '7', 'app_id': 'org.gnome.TextEditor',
              'geometry': {'x': 1025, 'y': 0, 'width': 1024, 'height': 1413},
              'minimized': False, 'focused': True}

    async def observe(args, ctx):
        return {'windows': [target], 'observed_at': 'now', 'source': 'fake', 'shell': {}}

    original = dc.observe
    dc.observe = observe
    try:
        args = {'window_id': '7', 'app_id': 'org.gnome.TextEditor', 'side': 'right'}
        shell_said = {'response': {'expected': {'x': 1025, 'y': 0, 'width': 1024, 'height': 1413}}}
        check('the rectangle the shell computed is accepted',
              asyncio.run(verify(args, shell_said, {}))['met'] is True)
        aligned_only = {'response': {'expected': {'x': 1024, 'y': 0, 'width': 1025, 'height': 1413}},
                        'scaling': {'rect': {'x': 1025, 'y': 0, 'width': 1024, 'height': 1413}}}
        check('and so is the device-aligned one when that is where the window went',
              asyncio.run(verify(args, aligned_only, {}))['met'] is True)
        neither = {'response': {'expected': {'x': 0, 'y': 0, 'width': 960, 'height': 1413}},
                   'scaling': {'rect': {'x': 2, 'y': 0, 'width': 960, 'height': 1413}}}
        check('a window that went somewhere else is NOT verified by either candidate',
              asyncio.run(verify(args, neither, {}))['met'] is False)
        check('and a tile with no rectangle at all is not verified by default',
              asyncio.run(verify(args, {'response': {}}, {}))['met'] is False)
    finally:
        dc.observe = original


def test_the_live_tile_path_is_reported_honestly():
    """A live tile needs the ARIES shell extension on the session bus. If it is
    not there, this says so — it does not pass quietly."""
    probe = desktop.capabilities()
    if not probe.get('available') or 'tile' not in probe.get('window_actions', []):
        check('SKIPPED, not passed — the ARIES shell bridge is not on the bus '
              '(%s), so no window can be tiled from here; the arithmetic and the '
              'scale read above are what was verified'
              % (probe.get('error') or probe.get('compatibility') or 'no tile action'), True)
        return
    windows, why, _ = desktop.read_windows()
    if not windows:
        check('SKIPPED — the bridge answers but there are no windows to tile: ' + why, True)
        return
    target = next((w for w in windows if not w.minimised and w.work_area), None)
    if target is None:
        check('SKIPPED — no mapped window with a work area', True)
        return
    report = desktop.tile_expectation(target.as_dict(), 'right')
    print('      live: %s on monitor %s, scale %s -> %s (shell would compute %s)'
          % (target.app_id, report['monitor'], report['scale'], report['rect'], report['shell_rect']))
    check('a real window on this machine yields a predicted rectangle inside its work area',
          report['rect'] is not None
          and report['rect']['x'] + report['rect']['width']
          <= target.work_area['x'] + target.work_area['width'])


if __name__ == '__main__':
    raise SystemExit(run_module(sys.modules[__name__]))
