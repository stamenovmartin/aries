"""The machine underneath the desktop: services, disks and packages.

ARIES could open applications and move files but knew nothing about what was
running, what was full or what was installed. These capabilities close that gap,
and every one of them is shaped by one measured fact about what an unprivileged
desktop session may actually do.

WHAT THIS SESSION CAN AND CANNOT DO — measured on this machine, not assumed

  reading   Both managers answer read-only questions with no authentication.
            `systemctl list-units` and `systemctl show` work for the system
            manager exactly as they do for `--user`.
  writing   Only `--user`. `pkcheck --action-id
            org.freedesktop.systemd1.manage-units` answers `auth_admin_keep`
            for this session: the system manager wants an ADMIN PASSWORD DIALOG
            on the person's screen before it starts anything. Worse, without
            `--no-ask-password` systemctl BLOCKS on that dialog — a measured
            `systemctl start cups-browsed.service` hung until it was killed.
            So every command here passes `--no-ask-password`, and system-scope
            control is refused up front, by name, rather than turned into a
            surprise password prompt nobody asked for. `sudo` is not a way
            round it either; it answers "interactive authentication is
            required" and exits.

Hence the shape: read both scopes, write only the user scope, and only units on
an explicit allowlist. Everything else is refused by name.

VERIFYING A UNIT ACTION. `systemctl restart` exits 0 for a job it queued, which
is a statement about the request and not about the unit. The proof is
InvocationID: systemd mints a new one per activation, so a restart that actually
happened has a different one afterwards and a no-op has the same one. The
executor records it before acting and the verifier re-reads it, which is the
same discipline desktop_capabilities uses against Mutter.
"""
import asyncio
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from aries.workspace.capability_types import Capability, Input


def now():
    return datetime.now(timezone.utc).isoformat()


class Empty(Input):
    pass


# systemd names carry @, :, dots and backslash-escaped device bytes. Anchored and
# length-capped: nothing here reaches a shell, but an argument beginning with '-'
# would still be read by systemctl as an option.
UNIT_NAME = r'[A-Za-z0-9_][A-Za-z0-9@:._\\-]{0,127}'
UNIT_GLOB = r'[A-Za-z0-9_*?\[\]][A-Za-z0-9@:._\\*?\[\]-]{0,127}'
SUFFIXES = ('.service', '.timer', '.socket', '.target', '.path', '.mount', '.slice', '.scope')


class ServicesInput(Input):
    scope: Literal['user', 'system', 'both'] = 'both'
    # Services by default. "Show me the services" does not mean the 328 .device
    # units the kernel generates, and systemd lists those FIRST, so an unfiltered
    # capped read returned three hundred disk nodes and not one service.
    kind: Literal['service', 'timer', 'socket', 'target', 'all'] = 'service'
    pattern: str = Field(default='', max_length=128, pattern='^(?:' + UNIT_GLOB + ')?$')
    state: Literal['all', 'active', 'inactive', 'running', 'failed'] = 'all'


class UnitInput(Input):
    unit: str = Field(min_length=1, max_length=128, pattern='^' + UNIT_NAME + '$')
    scope: Literal['user', 'system'] = 'user'


class ControlInput(UnitInput):
    action: Literal['start', 'stop', 'restart']


class PackageInput(Input):
    # Debian policy: lowercase, digits, '+', '-', '.'. Snap names are a subset.
    # Capitals are accepted and then folded, because "is Firefox installed" is how
    # a person says it and rejecting the question would be pedantry, not safety.
    # No '*': a glob would turn "is X installed" into "is anything like X".
    package: str = Field(min_length=1, max_length=120, pattern=r'^[A-Za-z0-9][A-Za-z0-9+._-]*$')


class SystemCapabilityError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.retryable = code == 'TRANSIENT'


# Exactly these units, by full name, and only in the user manager.
#
# ARIES's own, because "restart your voice" is a reasonable thing to say to an
# assistant, plus three user units whose worst failure is a missing convenience.
# Deliberately absent, and it is the important half of the list: dbus.service,
# pipewire*, wireplumber, gnome-session*, org.gnome.Shell@*, gnome-keyring-daemon,
# gcr-ssh-agent and at-spi-dbus-bus. Stopping any of those takes down the
# desktop, the microphone, the keyring or ARIES's own accessibility bridge, and
# no spoken sentence is worth that.
#
# aries-endurance.SERVICE is absent on purpose while its TIMER is present: the
# service is a Type=oneshot with TimeoutStartSec=90, so a start request can
# outlive any honest capability timeout and could not be verified. Its timer
# settles instantly, and "stop the endurance sampling" is the real request.
CONTROLLABLE = frozenset({
    'aries-core.service',
    'aries-voice.service',
    'aries-local-model.service',
    'aries-endurance.timer',
    'ollama.service',           # ARIES's model server; a restart evicts the model, nothing more
    'mpris-proxy.service',      # Bluetooth media-key bridge
    'localsearch-3.service',    # GNOME file indexer; rebuilds its own index
})

PROPERTIES = ('Id', 'Description', 'LoadState', 'ActiveState', 'SubState', 'UnitFileState', 'Type',
              'RemainAfterExit', 'InvocationID', 'Result', 'ExecMainPID', 'ExecMainStatus',
              'NRestarts', 'ActiveEnterTimestamp', 'ActiveExitTimestamp', 'StateChangeTimestamp',
              'FragmentPath', 'CanStart', 'CanStop')

# `systemctl --output=json` for the system manager measures 105 KB for all units.
# The shared capabilities.command() helper caps stdout at 16 KB, which would cut
# that JSON in half and turn a working read into a parse error, so this module
# runs its own bounded subprocess instead of borrowing that one.
MAX_OUTPUT = 2_000_000
MAX_UNITS = 300          # per manager; 300 units cost one 0.6 s `show` call
SETTLE_SECONDS = 6.0


async def _run(argv, timeout=12):
    """Fixed argv, no shell, bounded output, never orphans the child."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    except (OSError, ValueError) as exc:
        raise SystemCapabilityError('CAPABILITY_UNAVAILABLE',
                                    f'{argv[0]} could not be run: {exc}') from exc
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except BaseException:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 3)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        raise
    return (proc.returncode,
            out.decode(errors='replace')[:MAX_OUTPUT],
            err.decode(errors='replace')[:2000])


def _systemctl(scope, *args):
    # --no-ask-password on EVERY call, read or write. A background assistant that
    # can hang on a password dialog it cannot see is worse than one that refuses.
    argv = ['systemctl', '--no-pager', '--no-ask-password']
    if scope == 'user':
        argv.append('--user')
    return argv + list(args)


def qualify(unit):
    """A spoken or typed unit name rarely carries its suffix."""
    return unit if unit.endswith(SUFFIXES) else unit + '.service'


def own_unit():
    """The user unit this process runs inside, from its cgroup, or ''.

    Needed because aries-core.service is the thing serving the request: stopping
    it would kill this process before anything could be re-read, so the answer
    would be silence, not evidence.
    """
    try:
        line = Path('/proc/self/cgroup').read_text().strip().splitlines()[-1]
    except (OSError, IndexError):
        return ''
    leaf = line.rpartition('/')[2]
    return leaf if leaf.endswith(SUFFIXES) else ''


def _epoch(value):
    # --timestamp=unix prints '@1790702951'; a unit that never activated prints ''.
    text = (value or '').strip().lstrip('@')
    return int(text) if text.isdigit() else None


def _int(value):
    text = (value or '').strip()
    return int(text) if re.fullmatch(r'-?\d+', text) else None


def _row(raw, scope):
    since = _epoch(raw.get('ActiveEnterTimestamp'))
    pid = _int(raw.get('ExecMainPID'))
    return {'unit': raw.get('Id', ''), 'scope': scope,
            'description': raw.get('Description', ''),
            'load_state': raw.get('LoadState', ''),
            'active_state': raw.get('ActiveState', ''),
            'sub_state': raw.get('SubState', ''),
            'enablement': raw.get('UnitFileState') or 'unknown',
            'unit_type': raw.get('Type') or '',
            'remain_after_exit': raw.get('RemainAfterExit') == 'yes',
            'invocation': raw.get('InvocationID') or '',
            'result': raw.get('Result') or '',
            'restarts': _int(raw.get('NRestarts')),
            'main_pid': pid or None,
            'exit_status': _int(raw.get('ExecMainStatus')),
            'unit_file': raw.get('FragmentPath') or '',
            'can_start': raw.get('CanStart') == 'yes',
            'can_stop': raw.get('CanStop') == 'yes',
            'since': datetime.fromtimestamp(since, timezone.utc).isoformat() if since else None,
            'active_seconds': max(0, int(time.time() - since)) if since else None}


async def show(scope, units, timeout=12):
    """Properties of one or more units. Blank-line separated key=value blocks."""
    if not units:
        return []
    argv = _systemctl(scope, 'show', *(a for p in PROPERTIES for a in ('-p', p)),
                      '--timestamp=unix', '--', *units)
    code, out, err = await _run(argv, timeout)
    if code and not out.strip():
        raise SystemCapabilityError('CAPABILITY_UNAVAILABLE',
                                    f'systemctl show ({scope}) failed: ' + (err.strip() or 'no output'))
    rows = []
    for block in out.split('\n\n'):
        raw = {}
        for line in block.splitlines():
            key, sep, value = line.partition('=')
            if sep:
                raw[key] = value
        if raw.get('Id'):
            rows.append(_row(raw, scope))
    return rows


def priority(row):
    """When the list has to be cut, keep what somebody would actually look for.

    systemd's own order is by unit type, which buries a failed service behind
    three hundred device nodes. Broken first, then ARIES's own and anything ARIES
    may control, then alphabetical.
    """
    unit = row.get('unit', '')
    return (0 if row.get('active') == 'failed' else 1,
            0 if unit.startswith('aries') or unit in CONTROLLABLE else 1,
            unit)


async def services(args, ctx):
    """List units in either manager. A scope that cannot answer says so by name."""
    wanted = ('user', 'system') if args.get('scope', 'both') == 'both' else (args['scope'],)
    kind = args.get('kind', 'service')
    units, unavailable, truncated, listed_total = [], {}, False, 0
    for scope in wanted:
        argv = _systemctl(scope, 'list-units', '--all', '--output=json')
        if kind != 'all':
            argv.append('--type=' + kind)
        if args.get('state', 'all') != 'all':
            argv.append('--state=' + args['state'])
        if args.get('pattern'):
            argv += ['--', args['pattern']]
        try:
            code, out, err = await _run(argv, timeout=15)
        except SystemCapabilityError as exc:
            unavailable[scope] = str(exc)
            continue
        if code:
            unavailable[scope] = (err.strip() or out.strip() or 'systemctl list-units failed')[:200]
            continue
        try:
            listed = json.loads(out or '[]')
        except ValueError:
            unavailable[scope] = 'systemctl --output=json returned output this build cannot parse'
            continue
        rows = [r for r in listed if isinstance(r, dict) and r.get('unit')
                and not r['unit'].endswith('.device')]
        listed_total += len(rows)
        chosen = sorted(rows, key=priority)[:MAX_UNITS]
        truncated = truncated or len(chosen) < len(rows)
        # list-units carries no timestamps, so the ActiveState/SubState/since the
        # caller asked for comes from one bulk `show` rather than N calls.
        asked = [r['unit'] for r in chosen]
        enriched = await show(scope, asked, timeout=25)
        # A bulk `show` that returns fewer units than were listed has LOST some, and
        # losing them silently is the worst available outcome: measured 2026-10-04,
        # with `show` returning a malformed block this dropped 86 user units to 1 and
        # reported `unavailable: {}`. "What services are running" then answered with
        # one service and nothing said the other 85 had gone missing. The count is
        # still the number actually enriched — that stays honest — but the loss is now
        # named, so a caller cannot read `count` as the whole list.
        if len(enriched) < len(asked):
            unavailable[scope] = (
                f'systemctl listed {len(asked)} {kind} unit(s) in the {scope} manager and the '
                f'bulk property read returned only {len(enriched)}; the missing '
                f'{len(asked) - len(enriched)} could not be described and are NOT in this answer')
        units += enriched
    if not units and unavailable:
        raise SystemCapabilityError('CAPABILITY_UNAVAILABLE',
                                    '; '.join(f'{k}: {v}' for k, v in unavailable.items()))
    return {'units': units, 'count': len(units), 'listed': listed_total, 'truncated': truncated,
            'scopes': list(wanted), 'kind': kind, 'unavailable': unavailable,
            'failed': [u['unit'] for u in units if u['active_state'] == 'failed'],
            'controllable': sorted(CONTROLLABLE),
            'source': 'systemd via systemctl; kernel .device units are never listed',
            'observed_at': now()}


async def verify_services(args, result, ctx):
    # "Nothing is failed" is a real answer, so an empty list is not a failed
    # verification. A manager that refused to answer is.
    fresh = await services(args, ctx)
    return {'met': not fresh['unavailable'], 'type': 'systemd_units', 'data': fresh}


async def inspect_unit(args, ctx):
    unit = qualify(args['unit'])
    scope = args.get('scope', 'user')
    rows = await show(scope, [unit])
    if not rows:
        raise SystemCapabilityError('CAPABILITY_UNAVAILABLE',
                                    f'systemctl returned no properties for {unit} ({scope})')
    # systemctl exits 0 for a name it has never heard of and says so in LoadState.
    # Reporting that as an inactive unit would invent a unit that does not exist.
    if rows[0]['load_state'] == 'not-found':
        raise SystemCapabilityError('TARGET_NOT_FOUND', f'{unit} is not a known {scope} unit')
    # And it can exit 0 with properties present and LoadState ABSENT. Measured
    # 2026-10-04: that produced a confident answer about a unit whose existence was
    # never established — `active_state` reads `inactive`, which is a state, from a
    # reply that contained none. The two cases above do not cover it: there ARE rows,
    # and the missing field is not the string `not-found`. An absent LoadState is the
    # absence of an answer, so it is reported as one.
    if not rows[0]['load_state']:
        raise SystemCapabilityError(
            'CAPABILITY_UNAVAILABLE',
            f'systemctl exited 0 for {unit} ({scope}) without reporting LoadState, so whether '
            f'the unit is loaded at all was never established; the other properties cannot be '
            f'read as a state')
    return {**rows[0], 'controllable': unit in CONTROLLABLE and scope == 'user',
            'observed_at': now()}


async def verify_unit(args, result, ctx):
    fresh = await inspect_unit(args, ctx)
    return {'met': fresh['unit'] == result['unit'] and fresh['load_state'] != 'not-found',
            'type': 'systemd_unit', 'data': fresh}


async def control(args, ctx):
    """Start, stop or restart one allowlisted user unit. Refuses everything else."""
    unit = qualify(args['unit'])
    action, scope = args['action'], args.get('scope', 'user')
    if scope != 'user':
        raise SystemCapabilityError(
            'AUTH_REQUIRED',
            f'Refusing to {action} the system unit {unit}: the system manager requires an '
            'interactive administrator password (polkit auth_admin_keep for '
            'org.freedesktop.systemd1.manage-units), which ARIES cannot answer and will not '
            'pop up on your screen. System units can be read here, not changed.')
    if unit not in CONTROLLABLE:
        raise SystemCapabilityError(
            'PERMISSION_REQUIRED',
            f'{unit} is not a unit ARIES may control. Allowed user units: '
            + ', '.join(sorted(CONTROLLABLE)))
    if unit == own_unit() and action in {'stop', 'restart'}:
        raise SystemCapabilityError(
            'PERMISSION_REQUIRED',
            f'{unit} is running this very request. Stopping it would kill the process before '
            'anything could be re-read, so the result could never be verified. Restart it from '
            'a terminal with: systemctl --user restart ' + unit)
    before = await show('user', [unit])
    if not before or before[0]['load_state'] == 'not-found':
        raise SystemCapabilityError('TARGET_NOT_FOUND', f'{unit} is not a known user unit')
    code, out, err = await _run(_systemctl('user', action, '--', unit), timeout=45)
    detail = (err.strip() or out.strip())[:400]
    if code:
        if 'interactive authentication' in detail.casefold():
            raise SystemCapabilityError('AUTH_REQUIRED', detail)
        after = await show('user', [unit])
        state = after[0]['active_state'] if after else 'unknown'
        raise SystemCapabilityError(
            'NON_RETRYABLE',
            f'systemctl --user {action} {unit} exited {code}: {detail or "no message"}. '
            f'The unit is now {state}.')
    return {'unit': unit, 'action': action, 'scope': 'user', 'accepted': True,
            'exit_code': code, 'detail': detail, 'before': before[0], 'requested_at': now()}


def settled(action, before, after):
    """Did the unit actually reach the requested state? Reason included."""
    if after['load_state'] == 'not-found':
        return False, 'the unit is no longer loaded'
    changed = bool(after['invocation']) and after['invocation'] != before['invocation']
    state = after['active_state']
    if action == 'stop':
        return state == 'inactive', f'active_state is {state}'
    if action == 'start':
        # A unit that was already active accepts start and changes nothing. That
        # is still the requested end state, and calling it a failure would be a
        # false alarm — so the no-op is allowed only when it was active BEFORE.
        if state != 'active':
            return False, f'active_state is {state}'
        if changed:
            return True, 'a new InvocationID proves it was activated'
        if before['active_state'] == 'active':
            return True, 'it was already running, so there was nothing to activate'
        return False, 'it reports active but the InvocationID never changed'
    if state != 'active':
        return False, f'active_state is {state}'
    # A restart that kept its InvocationID did not restart anything.
    return changed, ('a new InvocationID proves it was restarted' if changed
                     else 'the InvocationID is unchanged: nothing actually restarted')


async def verify_control(args, result, ctx):
    unit, action = result['unit'], result['action']
    deadline = asyncio.get_running_loop().time() + SETTLE_SECONDS
    while True:
        rows = await show('user', [unit])
        after = rows[0] if rows else {'unit': unit, 'load_state': 'not-found', 'active_state': 'unknown',
                                      'sub_state': '', 'invocation': ''}
        met, why = settled(action, result['before'], after)
        transitional = after['active_state'] in {'activating', 'deactivating', 'reloading'}
        if met or not transitional or asyncio.get_running_loop().time() >= deadline:
            return {'met': met, 'type': 'systemd_unit',
                    'data': {'unit': unit, 'action': action, 'why': why,
                             'before': result['before'], 'after': after,
                             'evidence': 'systemctl show re-read after the request; an accepted job '
                                         'is not evidence, a new InvocationID is',
                             'observed_at': now()}}
        await asyncio.sleep(0.25)


# ── disks ────────────────────────────────────────────────────────────────────
# Bounds, because "how big is my home folder" must never become an unbounded walk
# of an unknown tree. Measured on this machine: 61 060 files and 8 662
# directories in 0.23 s, so these ceilings are headroom, not a handicap.
SCAN = {'seconds': 8.0, 'directories': 40_000, 'report_depth': 3, 'descent': 32, 'top': 15}


def filesystems():
    """statvfs per real mount, not `df`.

    A syscall cannot be mis-parsed, and the free figure that matters is the one an
    unprivileged process may actually use: ext4 reserves about 5% for root, so
    counting total blocks calls an already-full disk "95% full". Same choice, same
    reason, as aries/health/probes.probe_disk.
    """
    from aries.health.probes import PSEUDO_FS
    try:
        mounts = Path('/proc/mounts').read_text()
    except OSError as exc:
        raise SystemCapabilityError('CAPABILITY_UNAVAILABLE', f'/proc/mounts is unreadable: {exc}')
    rows, seen = [], set()
    for line in mounts.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mountpoint, fstype = parts[0], parts[1].replace('\\040', ' '), parts[2]
        if fstype in PSEUDO_FS or not device.startswith('/') or mountpoint in seen:
            continue
        seen.add(mountpoint)
        try:
            st = os.statvfs(mountpoint)
        except OSError as exc:
            rows.append({'device': device, 'mountpoint': mountpoint, 'filesystem': fstype,
                         'unavailable': f'statvfs failed: {exc}'})
            continue
        usable = st.f_blocks - (st.f_bfree - st.f_bavail)
        if usable <= 0:
            continue
        used = st.f_blocks - st.f_bfree
        rows.append({'device': device, 'mountpoint': mountpoint, 'filesystem': fstype,
                     'total_bytes': usable * st.f_frsize,
                     'used_bytes': used * st.f_frsize,
                     'available_bytes': st.f_bavail * st.f_frsize,
                     'used_pct': round(100.0 * used / usable, 1),
                     'basis': 'blocks available to an unprivileged process; '
                              "root's reserve is excluded from the total"})
    return rows


def home_directories(excluded=()):
    """Largest directories under $HOME, bounded by depth, entries and wall time."""
    from aries.sources.safety import _under
    root = os.path.realpath(Path.home())
    try:
        device = os.stat(root).st_dev
    except OSError as exc:
        raise SystemCapabilityError('CAPABILITY_UNAVAILABLE', f'{root} cannot be read: {exc}')
    deadline = time.monotonic() + SCAN['seconds']
    counted, sizes = set(), {}
    stats = {'directories': 0, 'files': 0, 'truncated': False, 'skipped': []}

    def walk(path, depth):
        total = 0
        try:
            entries = os.scandir(path)
        except OSError:
            return 0
        with entries:
            for entry in entries:
                if stats['directories'] >= SCAN['directories'] or time.monotonic() > deadline:
                    stats['truncated'] = True
                    break
                try:
                    if entry.is_symlink():
                        continue                    # counted where the target lives, not twice
                    st = entry.stat(follow_symlinks=False)
                    if st.st_dev != device:
                        continue                    # another filesystem is another question
                    if entry.is_dir(follow_symlinks=False):
                        if depth >= SCAN['descent']:
                            stats['truncated'] = True
                            continue
                        if any(_under(entry.path, e) for e in excluded):
                            stats['skipped'].append(entry.path)
                            continue
                        stats['directories'] += 1
                        total += walk(entry.path, depth + 1)
                    else:
                        if st.st_nlink > 1:
                            key = (st.st_dev, st.st_ino)
                            if key in counted:      # a hardlink occupies its blocks once
                                continue
                            counted.add(key)
                        stats['files'] += 1
                        total += st.st_blocks * 512  # blocks on disk, which is what `du` reports
                except OSError:
                    continue
        if depth <= SCAN['report_depth']:
            sizes[path] = total
        return total

    started = time.monotonic()
    grand = walk(root, 0)
    largest = sorted(((p, s) for p, s in sizes.items() if p != root),
                     key=lambda kv: kv[1], reverse=True)[:SCAN['top']]
    return {'root': root, 'total_bytes': grand,
            'largest': [{'path': p, 'bytes': s,
                         'depth': len(Path(p).relative_to(root).parts)} for p, s in largest],
            'files': stats['files'], 'directories': stats['directories'],
            'excluded': stats['skipped'][:20], 'truncated': stats['truncated'],
            'elapsed_ms': int((time.monotonic() - started) * 1000),
            'bounds': dict(SCAN),
            'basis': 'allocated blocks, symlinks not followed, one filesystem, hardlinks counted '
                     'once' + ('; TRUNCATED, so every total here is a lower bound'
                               if stats['truncated'] else '')}


async def excluded_paths(ctx):
    """privacy.excluded_paths, from the live settings when there is a session."""
    from aries.settings import get_def
    db = (ctx or {}).get('db')
    if db is not None:
        from aries.settings import SettingsService
        raw = await SettingsService(db).get('privacy.excluded_paths')
    else:
        definition = get_def('privacy.excluded_paths')
        raw = definition.default if definition else []
    return [os.path.realpath(os.path.expanduser(str(p))) for p in raw or [] if str(p).strip()]


async def disk(args, ctx):
    rows = await asyncio.to_thread(filesystems)
    measured = [r for r in rows if 'used_pct' in r]
    if not measured:
        raise SystemCapabilityError('CAPABILITY_UNAVAILABLE',
                                    'No real filesystem could be measured through statvfs')
    home = await asyncio.to_thread(home_directories, await excluded_paths(ctx))
    return {'filesystems': rows, 'fullest': max(measured, key=lambda r: r['used_pct']),
            'home': home, 'probe': 'os.statvfs + bounded os.scandir walk', 'observed_at': now()}


async def verify_disk(args, result, ctx):
    """Re-read statvfs and re-stat what was reported. The walk is not repeated."""
    fresh = await asyncio.to_thread(filesystems)
    mountpoints = {r['mountpoint'] for r in fresh}
    same = all(r['mountpoint'] in mountpoints for r in result['filesystems'])
    present = [os.path.isdir(r['path']) for r in result['home']['largest']]
    return {'met': same and all(present), 'type': 'storage_probe',
            'data': {'filesystems': fresh, 'mountpoints_still_present': same,
                     'directories_still_present': sum(present), 'of': len(present),
                     'scope': 'a fresh statvfs and an existence check; usage figures move '
                              'between reads and the directory walk is a bounded sample',
                     'observed_at': now()}}


# ── packages ─────────────────────────────────────────────────────────────────
# Query only. Installing belongs to capabilities.install_app, which has its own
# allowlist and needs pkexec — and this session has no root at all, so an install
# attempted from here could only ever fail or hang on a password dialog.
DPKG_FORMAT = r'-f=${binary:Package}\t${Version}\t${db:Status-Status}\t${db:Status-Want}\n'


async def packages(args, ctx):
    name = args['package'].casefold()
    entries, queried, unavailable = [], [], {}
    if shutil.which('dpkg-query'):
        queried.append('dpkg')
        code, out, err = await _run(['dpkg-query', '-W', DPKG_FORMAT, '--', name], timeout=10)
        if code and 'no packages found matching' not in err.casefold():
            unavailable['dpkg'] = (err.strip() or 'dpkg-query failed')[:200]
        for line in out.splitlines():
            fields = line.split('\t')
            if len(fields) >= 3 and fields[0]:
                entries.append({'source': 'dpkg', 'name': fields[0], 'version': fields[1],
                                # 'installed' is one of several dpkg states. A package that
                                # is config-files-only is NOT installed, and saying otherwise
                                # is how "it is already there" becomes a wrong answer.
                                'status': fields[2], 'wanted': fields[3] if len(fields) > 3 else '',
                                'installed': fields[2] == 'installed'})
    else:
        unavailable['dpkg'] = 'dpkg-query is not present'
    if shutil.which('snap'):
        queried.append('snap')
        code, out, err = await _run(['snap', 'list', '--', name], timeout=20)
        if code and 'no matching snaps' not in err.casefold():
            unavailable['snap'] = (err.strip() or 'snap list failed')[:200]
        for line in out.splitlines()[1:]:                 # first line is the column header
            fields = line.split()
            if len(fields) >= 3 and fields[0] == name:
                entries.append({'source': 'snap', 'name': fields[0], 'version': fields[1],
                                'revision': fields[2],
                                'publisher': fields[4] if len(fields) > 4 else '',
                                'notes': fields[5] if len(fields) > 5 else '',
                                'status': 'installed', 'installed': True})
    else:
        unavailable['snap'] = 'snap is not present'
    if not queried:
        raise SystemCapabilityError('CAPABILITY_UNAVAILABLE',
                                    'Neither dpkg-query nor snap is available on this machine')
    return {'package': name, 'installed': any(e['installed'] for e in entries),
            'entries': entries, 'queried': queried, 'unavailable': unavailable,
            'scope': 'query only; ARIES does not install from here',
            'observed_at': now()}


async def verify_packages(args, result, ctx):
    """An independent second query. A package can be mid-upgrade between them."""
    fresh = await packages(args, ctx)
    before = sorted((e['source'], e['name'], e['version'], e['installed']) for e in result['entries'])
    after = sorted((e['source'], e['name'], e['version'], e['installed']) for e in fresh['entries'])
    return {'met': fresh['installed'] == result['installed'] and before == after,
            'type': 'package_state', 'data': fresh}


def register(registry):
    registry.register(Capability(
        'system.services',
        'List systemd units with their real ActiveState/SubState and activation time, from the user '
        'and system managers. Read-only; a manager that cannot answer is named, not hidden.',
        ServicesInput, services, verify_services, timeout_seconds=45))
    registry.register(Capability(
        'system.service',
        'Inspect ONE systemd unit by name. A name systemd does not know is an error, never an '
        'inactive unit.',
        UnitInput, inspect_unit, verify_unit))
    registry.register(Capability(
        'system.service_control',
        'Start, stop or restart ONE allowlisted user unit. System units are refused: they need an '
        'interactive administrator password. Verified by re-reading the unit; a new InvocationID '
        'is the proof, not an accepted job.',
        ControlInput, control, verify_control,
        effect='service', requires_approval=True, risk_level='medium', timeout_seconds=60))
    registry.register(Capability(
        'system.disk',
        'Measure filesystem usage with statvfs and the largest directories under your home folder. '
        'Bounded by depth, entry count and time; a truncated walk says so.',
        Empty, disk, verify_disk, timeout_seconds=30))
    registry.register(Capability(
        'system.packages',
        'Check whether a package is installed and at what version, through dpkg and snap. Never '
        'installs anything.',
        PackageInput, packages, verify_packages))
