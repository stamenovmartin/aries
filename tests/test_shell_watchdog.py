import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-shell-watchdog')
from aries.shell import watchdog as w


async def test_repairs_only_the_stuck_state():
    check('INACTIVE with the screen unlocked is repaired', w.needs_repair(True, 'INACTIVE', False))
    check('while the shield is up GNOME is right to disable it', not w.needs_repair(True, 'INACTIVE', True))
    check('unknown lock state is left alone', not w.needs_repair(True, 'INACTIVE', None))
    check('a user who disabled ARIES is respected', not w.needs_repair(False, 'INACTIVE', False))
    check('an active shell is left alone', not w.needs_repair(True, 'ACTIVE', False))


async def test_never_touches_the_desktop_in_tests():
    check('the watchdog is off under APP_ENV=test', not w._enabled())
    calls = []
    with patch.object(w, '_run', lambda *a, **k: calls.append(a) or 'Enabled: Yes\nState: INACTIVE'), \
         patch('aries.operator.desktop.session_locked', lambda: False):
        out = w.repair()
    check('a stuck shell is disabled then enabled', [c[1] for c in calls if c[0] == 'gnome-extensions'][1:3] == ['disable', 'enable'])
    check('and the outcome is reported', out.get('was') == 'INACTIVE')


if __name__ == '__main__':
    run_module(sys.modules[__name__])
