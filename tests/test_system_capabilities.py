"""System administration capabilities: real parsing, real refusals, no root.

The interesting assertions are the negative ones. A unit action that systemd
ACCEPTED and that changed nothing must not be reported as success, and a unit
that is not on the allowlist must be refused by name rather than attempted and
explained afterwards. Both are exercised against captured `systemctl show`
output so they hold whatever this machine happens to be running.

Restarting a real unit is a side effect, so the one live control test is opt-in:
ARIES_SYSTEM_CONTROL_TEST=1. Everything else here is read-only.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-system-capabilities')
from aries.workspace import system_capabilities as sc
from aries.workspace.registry import registry

# Captured verbatim from `systemctl --user show -p ... --timestamp=unix` on this
# machine: a running service, a oneshot that has run and exited (no
# ActiveEnterTimestamp at all), a timer (no Type, no main PID) and a name systemd
# has never heard of, which it answers with exit 0 and LoadState=not-found.
SHOW = """Id=aries-core.service
Description=ARIES core — API, scheduler, automations dispatcher
LoadState=loaded
ActiveState=active
SubState=running
UnitFileState=enabled
Type=exec
RemainAfterExit=no
InvocationID=ca56a91dc3f64829bb71f5919655f962
Result=success
ExecMainPID=2014
ExecMainStatus=0
NRestarts=0
ActiveEnterTimestamp=@1790702951
ActiveExitTimestamp=
StateChangeTimestamp=@1790702951
FragmentPath=/home/u/.config/systemd/user/aries-core.service
CanStart=yes
CanStop=yes

Id=aries-endurance.service
Description=ARIES bounded 24-hour evidence sample
LoadState=loaded
ActiveState=inactive
SubState=dead
UnitFileState=static
Type=oneshot
RemainAfterExit=no
InvocationID=e8a196947d104771bb9d5dab17b921df
Result=success
ExecMainPID=152737
ExecMainStatus=0
NRestarts=0
ActiveEnterTimestamp=
ActiveExitTimestamp=@1790709306
StateChangeTimestamp=@1790709306
FragmentPath=/home/u/.config/systemd/user/aries-endurance.service
CanStart=yes
CanStop=yes

Id=aries-endurance.timer
Description=ARIES availability sample every five minutes
LoadState=loaded
ActiveState=active
SubState=waiting
UnitFileState=enabled
InvocationID=664384880f5a4e0e8b6c0ad1e52d9a77
Result=success
ActiveEnterTimestamp=@1790702950
CanStart=yes
CanStop=yes

Id=no-such-unit-xyz.service
Description=no-such-unit-xyz.service
LoadState=not-found
ActiveState=inactive
SubState=dead
UnitFileState=
Result=success
ActiveEnterTimestamp=
CanStart=yes
CanStop=no
"""

LIST = [
    {"unit": "dev-disk-by\\x2ddiskseq-10.device", "load": "loaded", "active": "active",
     "sub": "plugged", "description": "a kernel device node"},
    {"unit": "zz-last.service", "load": "loaded", "active": "active", "sub": "running",
     "description": "alphabetically last"},
    {"unit": "broken.service", "load": "loaded", "active": "failed", "sub": "failed",
     "description": "a unit that fell over"},
    {"unit": "aries-voice.service", "load": "loaded", "active": "active", "sub": "running",
     "description": "ARIES voice"},
]


def blocks(names):
    """One block per requested name, in the order requested — as systemctl does."""
    have = {b.split('\n', 1)[0][3:]: b for b in SHOW.rstrip().split('\n\n')}
    return '\n\n'.join(have.get(n) or f'Id={n}\nLoadState=loaded\nActiveState=active\n'
                                     f'SubState=running\nInvocationID={abs(hash(n)):032x}\n'
                                     'ActiveEnterTimestamp=@1790702951\n' for n in names)


def fake_systemctl(list_rows=LIST, code=0, err=''):
    async def run(argv, timeout=12):
        if 'list-units' in argv:
            return code, json.dumps(list_rows), err
        if 'show' in argv:
            return 0, blocks(argv[argv.index('--') + 1:] if '--' in argv else []), ''
        return code, '', err
    return run


async def test_show_parses_real_output():
    with patch.object(sc, '_run', fake_systemctl()):
        rows = {r['unit']: r for r in await sc.show('user', [
            'aries-core.service', 'aries-endurance.service', 'aries-endurance.timer',
            'no-such-unit-xyz.service'])}
    check('every captured block became one row', len(rows) == 4)
    core = rows['aries-core.service']
    check('ActiveState and SubState come from systemd, not from an exit code',
          (core['active_state'], core['sub_state']) == ('active', 'running'))
    check('since is a real timestamp', core['since'] == '2026-09-29T17:29:11+00:00')
    check('active_seconds is derived from it', isinstance(core['active_seconds'], int))
    check('main PID and unit file are reported',
          core['main_pid'] == 2014 and core['unit_file'].endswith('aries-core.service'))
    once = rows['aries-endurance.service']
    check('a oneshot that never "entered active" has no since, not a fake one',
          once['since'] is None and once['active_seconds'] is None)
    check('a oneshot still reports its result', once['result'] == 'success')
    timer = rows['aries-endurance.timer']
    check('a timer has no Type and no main PID, and neither is invented',
          timer['unit_type'] == '' and timer['main_pid'] is None)
    check('a timer reports SubState=waiting', timer['sub_state'] == 'waiting')
    check('a name systemd does not know is marked not-found, not inactive',
          rows['no-such-unit-xyz.service']['load_state'] == 'not-found')

    # systemctl exits 0 for an unknown unit. Reporting it as a dead service would
    # invent a unit; the capability has to turn that into an error.
    with patch.object(sc, '_run', fake_systemctl()):
        try:
            await sc.inspect_unit({'unit': 'no-such-unit-xyz', 'scope': 'user'}, {})
            check('an unknown unit is refused', False)
        except sc.SystemCapabilityError as exc:
            check('an unknown unit is TARGET_NOT_FOUND, not an empty answer',
                  exc.code == 'TARGET_NOT_FOUND' and 'no-such-unit-xyz.service' in str(exc))
    with patch.object(sc, '_run', fake_systemctl()):
        found = await sc.inspect_unit({'unit': 'aries-core', 'scope': 'user'}, {})
    check('a bare name is qualified with .service', found['unit'] == 'aries-core.service')


async def test_listing_excludes_devices_and_puts_broken_first():
    with patch.object(sc, '_run', fake_systemctl()):
        out = await sc.services({'scope': 'user', 'kind': 'all'}, {})
    check('kernel .device units are never listed',
          not any(u['unit'].endswith('.device') for u in out['units']))
    check('a failed unit is ranked first', sc.priority(LIST[2]) < sc.priority(LIST[3]))
    check("ARIES's own units outrank unrelated ones", sc.priority(LIST[3]) < sc.priority(LIST[1]))
    with patch.object(sc, 'MAX_UNITS', 1), patch.object(sc, '_run', fake_systemctl()):
        cut = await sc.services({'scope': 'user', 'kind': 'all'}, {})
    check('a cut list says so and reports the full count',
          cut['truncated'] and cut['count'] == 1 and cut['listed'] == 3)

    # One manager refusing to answer must be named, not silently dropped.
    async def only_user(argv, timeout=12):
        if '--user' not in argv:
            return 1, '', 'Failed to connect to bus'
        return await fake_systemctl()(argv, timeout)
    with patch.object(sc, '_run', only_user):
        mixed = await sc.services({'scope': 'both', 'kind': 'service'}, {})
    check('the scope that failed is named in unavailable',
          'system' in mixed['unavailable'] and 'user' not in mixed['unavailable'])
    check('the scope that answered still returns units', mixed['count'] > 0)
    with patch.object(sc, '_run', fake_systemctl(code=1, err='no bus')):
        try:
            await sc.services({'scope': 'both'}, {})
            check('both managers failing is an error', False)
        except sc.SystemCapabilityError as exc:
            check('both managers failing is CAPABILITY_UNAVAILABLE, not an empty desktop',
                  exc.code == 'CAPABILITY_UNAVAILABLE')
    with patch.object(sc, '_run', fake_systemctl(list_rows=[])):
        empty = await sc.services({'scope': 'user', 'state': 'failed'}, {})
        verdict = await sc.verify_services({'scope': 'user', 'state': 'failed'}, empty, {})
    check('"nothing is failed" is a verified answer, not a failed verification',
          empty['count'] == 0 and verdict['met'])


async def test_accepted_is_not_verified():
    """The whole point: systemd accepting a job proves only that it was asked."""
    active = {'load_state': 'loaded', 'active_state': 'active', 'invocation': 'AAA'}
    check('a restart that kept its InvocationID did not restart anything',
          sc.settled('restart', active, dict(active)) == (
              False, 'the InvocationID is unchanged: nothing actually restarted'))
    check('a restart with a new InvocationID is proven',
          sc.settled('restart', active, {**active, 'invocation': 'BBB'})[0])
    check('a restart that came back failed is not success',
          not sc.settled('restart', active, {**active, 'invocation': 'BBB',
                                             'active_state': 'failed'})[0])
    check('a unit that stopped existing is not success',
          not sc.settled('restart', active, {**active, 'load_state': 'not-found'})[0])
    check('stop is proven by inactive, not by exit 0',
          sc.settled('stop', active, {**active, 'active_state': 'inactive'})[0]
          and not sc.settled('stop', active, dict(active))[0])
    check('start on an already-running unit is honestly a no-op that met the goal',
          sc.settled('start', active, dict(active)) == (
              True, 'it was already running, so there was nothing to activate'))
    check('start from inactive needs a new InvocationID',
          not sc.settled('start', {**active, 'active_state': 'inactive'}, dict(active))[0])
    check('start from inactive with a new InvocationID is proven',
          sc.settled('start', {**active, 'active_state': 'inactive'},
                     {**active, 'invocation': 'BBB'})[0])

    # The executor/verifier pair, end to end, against a systemctl that accepts
    # everything and changes nothing — the exact failure this guards against.
    args = {'unit': 'mpris-proxy.service', 'action': 'restart', 'scope': 'user'}
    with patch.object(sc, '_run', lambda argv, timeout=12: _accept(argv)):
        result = await sc.control(args, {})
        verdict = await sc.verify_control(args, result, {})
    check('the executor reports the request as accepted', result['accepted'])
    check('the verifier refuses to call that success', not verdict['met'])
    check('the evidence names what was compared',
          verdict['data']['before']['invocation'] == verdict['data']['after']['invocation'])


async def _accept(argv):
    """A systemctl that accepts every job and never changes a unit."""
    if 'show' in argv:
        return 0, ('Id=mpris-proxy.service\nLoadState=loaded\nActiveState=active\n'
                   'SubState=running\nInvocationID=SAME\nActiveEnterTimestamp=@1790702951\n'
                   'Type=simple\nCanStart=yes\nCanStop=yes\n'), ''
    return 0, '', ''


async def test_refusals_are_by_name():
    for unit in ('pipewire.service', 'dbus.service', 'org.gnome.Shell@aries.service',
                 'gnome-keyring-daemon.service', 'at-spi-dbus-bus.service',
                 'aries-endurance.service', 'systemd-logind.service'):
        try:
            await sc.control({'unit': unit, 'action': 'stop', 'scope': 'user'}, {})
            check(f'{unit} must not be controllable', False)
        except sc.SystemCapabilityError as exc:
            check(f'{unit} is refused by name before any command runs',
                  exc.code == 'PERMISSION_REQUIRED' and unit in str(exc))
    check('the allowlist is small and explicit', 0 < len(sc.CONTROLLABLE) <= 10)
    check('every allowlisted unit is fully qualified',
          all(u.endswith(sc.SUFFIXES) for u in sc.CONTROLLABLE))

    # Measured on this machine: pkcheck answers auth_admin_keep for
    # org.freedesktop.systemd1.manage-units, so the system manager wants an admin
    # password dialog. ARIES refuses instead of raising one.
    try:
        await sc.control({'unit': 'chrony.service', 'action': 'restart', 'scope': 'system'}, {})
        check('system-scope control must be refused', False)
    except sc.SystemCapabilityError as exc:
        check('system scope is AUTH_REQUIRED and explains why',
              exc.code == 'AUTH_REQUIRED' and 'password' in str(exc))

    # Killing the process that is serving the request destroys the evidence.
    with patch.object(sc, 'own_unit', lambda: 'aries-core.service'):
        for action in ('stop', 'restart'):
            try:
                await sc.control({'unit': 'aries-core', 'action': action, 'scope': 'user'}, {})
                check(f'{action} of our own unit must be refused', False)
            except sc.SystemCapabilityError as exc:
                check(f'{action} of the unit running this request is refused',
                      exc.code == 'PERMISSION_REQUIRED' and 'verified' in str(exc))
    check('own_unit reads a real cgroup or honestly returns nothing',
          sc.own_unit() == '' or sc.own_unit().endswith(sc.SUFFIXES))


async def test_disk_is_bounded_and_honest():
    filesystems = await asyncio.to_thread(sc.filesystems)
    measured = [r for r in filesystems if 'used_pct' in r]
    check('statvfs measured at least the root filesystem',
          any(r['mountpoint'] == '/' for r in measured))
    for row in measured:
        check(f"{row['mountpoint']} usage adds up",
              row['used_bytes'] + row['available_bytes'] == row['total_bytes']
              and 0 <= row['used_pct'] <= 100)
    check('no pseudo-filesystem is counted as storage',
          not any(r['filesystem'] in {'tmpfs', 'proc', 'squashfs'} for r in filesystems))

    home = await asyncio.to_thread(sc.home_directories, [str(Path.home() / '.ssh')])
    check('the walk reported directories', home['directories'] > 0 and home['files'] > 0)
    check('reported depth never exceeds the cap',
          all(r['depth'] <= sc.SCAN['report_depth'] for r in home['largest']))
    check('at most the configured number of rows', len(home['largest']) <= sc.SCAN['top'])
    check('rows are ordered largest first',
          home['largest'] == sorted(home['largest'], key=lambda r: r['bytes'], reverse=True))
    check('no child is reported larger than the whole tree',
          all(r['bytes'] <= home['total_bytes'] for r in home['largest']))
    check('an excluded path is never walked',
          not any(r['path'].startswith(str(Path.home() / '.ssh')) for r in home['largest']))
    check('the time bound is honoured', home['elapsed_ms'] <= sc.SCAN['seconds'] * 1000 + 2000)
    check('the bounds are reported with the answer', home['bounds'] == dict(sc.SCAN))
    check('truncation is stated, never hidden', isinstance(home['truncated'], bool))

    # A bound that actually bites must say the totals are lower bounds.
    with patch.dict(sc.SCAN, {'directories': 1}):
        clipped = await asyncio.to_thread(sc.home_directories, [])
    check('a walk that hit its entry cap reports truncated',
          clipped['truncated'] and 'lower bound' in clipped['basis'])

    observed = await sc.disk({}, {})
    check('the fullest filesystem is the measured maximum, not a guess',
          observed['fullest']['used_pct'] == max(r['used_pct'] for r in measured))
    verdict = await sc.verify_disk({}, observed, {})
    check('verification re-reads statvfs and re-stats what it reported', verdict['met'])
    check('verification does not claim to have repeated the walk',
          'bounded sample' in verdict['data']['scope'])

    defaults = await sc.excluded_paths({})
    check('privacy.excluded_paths is honoured with no database session',
          any(p.endswith('.ssh') for p in defaults))


async def test_packages_query_only():
    # dpkg-query and snap both exist here; python3 is installed by definition,
    # because this test is running on it.
    out = await sc.packages({'package': 'python3'}, {})
    check('a package that is installed is reported installed', out['installed'])
    check('every entry names where the answer came from',
          all(e['source'] in {'dpkg', 'snap'} for e in out['entries']))
    check('a version is reported, not a bare yes',
          all(e['version'] for e in out['entries']))
    check('the queried package managers are listed', out['queried'])
    check('the answer says it does not install anything', 'query only' in out['scope'])
    verdict = await sc.verify_packages({'package': 'python3'}, out, {})
    check('an independent second query agrees', verdict['met'])

    absent = await sc.packages({'package': 'aries-no-such-package'}, {})
    check('a package that is absent is reported absent, and that is not an error',
          absent['installed'] is False and absent['entries'] == [])
    check('"not found" from dpkg or snap is not reported as a broken tool',
          not absent['unavailable'])
    check('a capitalised spoken name is folded, not refused',
          (await sc.packages({'package': 'Python3'}, {}))['installed'] == out['installed'])

    with patch.object(sc.shutil, 'which', lambda _: None):
        try:
            await sc.packages({'package': 'python3'}, {})
            check('no package manager at all is an error', False)
        except sc.SystemCapabilityError as exc:
            check('no package manager at all is CAPABILITY_UNAVAILABLE',
                  exc.code == 'CAPABILITY_UNAVAILABLE')


async def test_registration_and_policy_shape():
    from aries.workspace.registry import Registry
    registry = Registry()
    sc.register(registry)
    for name in ('system.services', 'system.service', 'system.service_control',
                 'system.disk', 'system.packages'):
        check(name + ' is registered', registry.get(name).name == name)
    control = registry.get('system.service_control')
    check('changing a unit requires approval', control.requires_approval)
    check('changing a unit is not a read effect', control.effect != 'read')
    for name in ('system.services', 'system.service', 'system.disk', 'system.packages'):
        check(name + ' is read-only and needs no approval',
              registry.get(name).effect == 'read' and not registry.get(name).requires_approval)
    check('a shell fragment is not a unit name',
          _rejected('system.service', {'unit': '; rm -rf /'}))
    check('an argument that looks like an option is not a unit name',
          _rejected('system.service', {'unit': '--user'}))
    check('reload and enable are outside this capability',
          _rejected('system.service_control', {'unit': 'aries-voice', 'action': 'reload'}))
    check('a glob is not a package name', _rejected('system.packages', {'package': 'fire*'}))
    check('the disk capability takes no arguments at all',
          _rejected('system.disk', {'path': '/etc'}))


def _rejected(name, args):
    try:
        registry.validate(name, args)
        return False
    except Exception:
        return True


async def test_live_reads_on_this_machine():
    own = await sc.services({'scope': 'user', 'pattern': 'aries*'}, {})
    if not own['count']:
        check('skipped — no aries-* user units are installed on this machine', True)
        return
    check('ARIES can see its own units', {'aries-core.service'} <= {u['unit'] for u in own['units']})
    check('each observed unit carries a real state',
          all(u['active_state'] in {'active', 'inactive', 'failed', 'activating', 'deactivating'}
              for u in own['units']))
    both = await sc.services({'scope': 'both'}, {})
    check('the system manager answers read-only questions without authentication',
          any(u['scope'] == 'system' for u in both['units']) and 'system' not in both['unavailable'])
    core = await sc.inspect_unit({'unit': 'aries-core', 'scope': 'user'}, {})
    check('a single unit inspects with a unit file path on disk',
          core['unit_file'] and Path(core['unit_file']).name == 'aries-core.service')
    check('the inspection says whether ARIES may control it', core['controllable'] is True)


async def test_live_control_opt_in():
    if os.environ.get('ARIES_SYSTEM_CONTROL_TEST') != '1':
        check('skipped — restarting a real unit needs ARIES_SYSTEM_CONTROL_TEST=1', True)
        return
    unit = 'mpris-proxy.service'
    before = await sc.show('user', [unit])
    if not before or before[0]['load_state'] == 'not-found':
        check('skipped — ' + unit + ' is not installed on this machine', True)
        return
    args = {'unit': unit, 'action': 'restart', 'scope': 'user'}
    result = await sc.control(args, {})
    verdict = await sc.verify_control(args, result, {})
    check('a live user-scope restart is verified by a new InvocationID',
          verdict['met'] and verdict['data']['after']['invocation'] != result['before']['invocation'])
    check('the unit came back active', verdict['data']['after']['active_state'] == 'active')


if __name__ == '__main__':
    run_module(sys.modules[__name__])
