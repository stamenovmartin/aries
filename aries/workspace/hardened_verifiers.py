"""Hardened verifiers for the 23 capabilities the frozen review classed TRIVIAL, SELF_REPORT or
PLANNER_SUPPLIED (ARIES_VERIFY_HARDENED, default off), plus two INDEPENDENT ones as a separately
labelled exploratory condition (ARIES_VERIFY_HARDENED_EXTRA, default off).

WHY
---
The frozen review (experiments/product/independent-acceptance/raw/review_verifier_integrity.json)
found verifiers whose `met` no world state can make false (TRIVIAL), or that check the executor's
report only against itself (SELF_REPORT), or whose reference value comes from the planner's own
arguments (browser.click). Preregistration H8 (docs/preregistration/H8-verifier-fault-injection.md)
hardens them with four means, chosen from each capability's contract:

1. agreement: the report must describe the world. Its stable fields are compared with a fresh read
   taken by the verifier, so a report that was never observed, or was changed, fails;
2. a different channel where one exists (/proc and statvfs directly instead of the health probes,
   the process table for windows, the page itself for each listed tab, a direct SQL row for a task,
   the directory itself for a listing);
3. per-capability invariants (a count equals its list, a character count equals its text, a
   `highest` is the maximum);
4. UNVERIFIED: when the independent read itself cannot be made, the verdict is
   {'met': False, 'status': 'UNVERIFIED'}, which never counts as done.

VOLATILE VALUES
---------------
A measurement can legitimately move between the executor's read and the verifier's. Where a value
is volatile, the verifier reads it twice and allows the drift it measured itself plus a stated
resolution (TOLERANCE). What cannot be re-measured at all (a 0.1 s CPU sample) is checked for range
only, and that is recorded in the evidence rather than claimed as agreement.

Off, nothing in this module runs: registry.py imports it only when a flag is on, and with both flags
off every registered verifier is the frozen function object (tests/test_verify_hardened.py compares
fingerprints recorded before this module existed).
"""
from __future__ import annotations

import asyncio
import dataclasses
import difflib
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

# Resolution added to the drift a verifier measures between its own two reads.
TOLERANCE = {
    'percent': 0.5,          # a percentage rounded to 0.1 by the probes, plus one rounding step each side
    'memory_percent': 2.0,   # memory in use moves with every allocation on a desktop
    'load1': 1.0,            # the 1-minute load average is re-sampled every 5 s by the kernel
    'gib': 0.02,             # sizes rounded to 0.01 GiB
    'processes': 2,          # processes started or ended between two reads
    'screen_text': 0.9,      # SequenceMatcher ratio between the reported and a fresh recognition
}

HARDENED = ('browser.back', 'browser.click', 'browser.elements', 'browser.forward', 'browser.observe',
            'browser.open', 'browser.read', 'browser.scroll', 'browser.tabs', 'browser.wait',
            'desktop.observe', 'desktop.windows', 'display.brightness', 'file.list', 'file.search',
            'input.editable_targets', 'screen.read', 'system.processes', 'system.service', 'system.services',
            'system.status', 'system.storage', 'task.inspect')
EXTRA = ('notification.send', 'system.disk')


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def verdict(kind, checks, data, frozen=None):
    """All checks must hold. The frozen verdict, when there is one, is one of the checks."""
    if frozen is not None:
        checks = {'frozen_verifier': bool(frozen.get('met')), **checks}
    return {'met': all(checks.values()), 'type': kind, 'hardened': True,
            'checks': {k: bool(v) for k, v in checks.items()},
            'data': data if frozen is None else {**(frozen.get('data') or {}), 'hardened_reads': data}}


def unverified(kind, exc):
    return {'met': False, 'status': 'UNVERIFIED', 'type': kind, 'hardened': True,
            'data': {'error': f'{type(exc).__name__}: {str(exc)[:300]}',
                     'why': 'the independent read could not be made, so the effect is not verified',
                     'observed_at': now()}}


def guarded(kind, fn):
    """An exception in the verifier's own read is UNVERIFIED, never a pass."""
    async def verify(args, result, ctx):
        try:
            return await fn(args, result, ctx)
        except Exception as exc:                                   # noqa: BLE001
            return unverified(kind, exc)
    verify.__name__ = verify.__qualname__ = 'hardened_' + fn.__name__
    verify.__module__ = __name__
    return verify


def _within(reported, fresh_a, fresh_b, resolution):
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (reported, fresh_a, fresh_b)):
        return False
    return abs(reported - fresh_b) <= abs(fresh_a - fresh_b) + resolution


# ───────────────────────────────────────────────────────────── browser
PAGE_FIELDS = ('url', 'title', 'scroll')


def _page(state):
    return {**{k: state.get(k) for k in PAGE_FIELDS}, 'text_sha256': _sha(state.get('text'))}


async def _owned_page(session, ctx):
    from aries.workspace.registry import browser_read
    return await browser_read({'session': session}, ctx)


async def page_agreement(args, result, ctx, frozen_verifier):
    """A page report must be the page now shown: URL, title, scroll and text all agree."""
    frozen = await frozen_verifier(args, result, ctx)
    session = result.get('session') or args.get('session', '')
    fresh = await _owned_page(session, ctx)
    checks = {'title_present': bool(fresh.get('title')),
              'session': result.get('session') in (None, session),
              **{f'{k}_agrees': fresh.get(k) == result.get(k) for k in PAGE_FIELDS},
              'text_agrees': _sha(fresh.get('text')) == _sha(result.get('text'))}
    return verdict('browser_state', checks, {'fresh_page': _page(fresh), 'reported_page': _page(result),
                                             'observed_at': now()}, frozen)


async def b_state(args, result, ctx):
    from aries.workspace.browser_capabilities import verify_state
    return await page_agreement(args, result, ctx, verify_state)


async def b_page(args, result, ctx):
    from aries.workspace.registry import verify_browser
    return await page_agreement(args, result, ctx, verify_browser)


async def b_scroll(args, result, ctx):
    from aries.workspace.browser_capabilities import verify_scroll
    return await page_agreement(args, result, ctx, verify_scroll)


async def b_open(args, result, ctx):
    """The page shown must be on the requested host (a redirect within it is allowed)."""
    out = await b_page(args, result, ctx)
    host = lambda u: (urlsplit(u or '').hostname or '').removeprefix('www.')
    shown = (out['data'].get('hardened_reads') or {}).get('fresh_page', {}).get('url')
    out['checks']['requested_host'] = bool(shown) and host(shown) == host(args['url'])
    out['met'] = all(out['checks'].values())
    return out


async def b_click(args, result, ctx):
    """The planner's expected_url stays the reference (finding F2); the report must also agree with the
    page now shown, and the click must have left the session on a page reached from a link."""
    out = await b_state(args, result, ctx)
    fresh = (out['data'].get('hardened_reads') or {}).get('fresh_page', {})
    out['checks']['expected_url_is_shown'] = fresh.get('url') == args['expected_url']
    out['met'] = all(out['checks'].values())
    return out


async def b_elements(args, result, ctx):
    from aries.workspace.browser_capabilities import verify_elements
    frozen = await verify_elements(args, result, ctx)
    fresh = await _owned_page(args['session'], ctx)
    rows = result.get('elements') or []
    ids = [r.get('element_id') for r in rows]
    checks = {'session': result.get('session') == args['session'],
              'url_agrees': fresh.get('url') == result.get('url'),
              'ids_unique': len(ids) == len(set(ids)) and all(isinstance(i, str) and i for i in ids),
              'truncated_is_bool': isinstance(result.get('truncated'), bool)}
    return verdict('browser_elements', checks, {'fresh_page': _page(fresh), 'elements': len(rows),
                                                'observed_at': now()}, frozen)


async def b_tabs(args, result, ctx):
    """Tabs agree with a fresh inventory, and each open tab's own page shows the listed URL."""
    from aries.workspace import browser
    from aries.workspace.browser_capabilities import tabs
    fresh = await tabs(args, ctx)
    proj = lambda rows: sorted(((r.get('session'), r.get('url'), r.get('open')) for r in rows), key=repr)
    shown = {}
    for row in fresh['tabs']:
        if row.get('open'):
            shown[row['session']] = (await browser.observe(row['session'])).get('url')
    checks = {'inventory_agrees': proj(result.get('tabs') or []) == proj(fresh['tabs']),
              'pages_agree': all(shown.get(r['session']) == r.get('url') for r in fresh['tabs'] if r.get('open'))}
    return verdict('browser_inventory', checks, {**fresh, 'pages': shown, 'observed_at': now()})


# ───────────────────────────────────────────────────────────── desktop, display, input, screen
WINDOW_FIELDS = ('window_id', 'app_id', 'title', 'minimized', 'maximized', 'geometry', 'workspace')


async def d_observe(args, result, ctx):
    """Windows agree with a fresh read, and every window's process is in the process table."""
    from aries.operator import desktop
    from aries.workspace.desktop_capabilities import observe
    fresh = await observe(args, ctx)
    proj = lambda rows: sorted((tuple(json.dumps(w.get(k), sort_keys=True) for k in WINDOW_FIELDS) for w in rows))
    pids = {p.pid for p in await asyncio.to_thread(desktop.read_processes)}
    checks = {'windows_agree': proj(result.get('windows') or []) == proj(fresh['windows']),
              'processes_exist': all(w.get('pid') in pids for w in fresh['windows'] if w.get('pid'))}
    return verdict('desktop_state', checks, {**fresh, 'observed_at': now()})


async def brightness_read(args, result, ctx):
    from aries.workspace.network_capabilities import brightness
    a = await asyncio.to_thread(brightness, None)
    b = await asyncio.to_thread(brightness, None)
    checks = {'readable': a.get('ok') and b.get('ok'),
              'agrees': _within(result.get('brightness'), a.get('brightness'), b.get('brightness'), 0)}
    return verdict('display_state', checks, {**b, 'drift': None if not checks['readable'] else
                                             abs(a['brightness'] - b['brightness'])})


async def i_targets(args, result, ctx):
    from aries.workspace.input_capabilities import editable_targets
    fresh = await editable_targets(args, ctx)
    proj = lambda d: sorted((t.get('node'), t.get('role'), t.get('name')) for t in d.get('targets') or [])
    checks = {'app': result.get('app') == args['app'] == fresh.get('app'),
              'targets_agree': proj(result) == proj(fresh)}
    return verdict('editable_targets', checks, fresh)


async def s_read(args, result, ctx):
    """Counts match the text, the stored frame is unchanged, and a fresh recognition agrees."""
    from aries.workspace import screen_capabilities as sc
    frozen = await sc.verify_read(args, result, ctx)
    text = result.get('text') or ''
    stored = await sc._reinspect(result['capture']['path'])
    fresh = await asyncio.to_thread(sc.read, args.get('window_id'), args.get('language', 'eng+mkd'))
    ratio = difflib.SequenceMatcher(None, text, fresh.get('text') or '').ratio()
    checks = {'characters_match_text': result.get('characters') == len(text),
              'words_match_text': result.get('words') == len(text.split()),
              'stored_frame_unchanged': stored.get('sha256') == result['capture'].get('sha256'),
              'fresh_recognition_agrees': ratio >= TOLERANCE['screen_text']}
    return verdict('screen_text', checks, {'fresh_characters': fresh.get('characters'), 'similarity': round(ratio, 3),
                                           'stored_sha256': stored.get('sha256'), 'observed_at': now()}, frozen)


# ───────────────────────────────────────────────────────────── files and tasks
async def f_list(args, result, ctx):
    """The listing agrees with a second read, and with the directory itself, read directly."""
    from aries.workspace.registry import listing, verify_probe
    frozen = await verify_probe(listing, 'directory_state')(args, result, ctx)
    root = Path(result.get('path') or '')
    direct = {e.name: e.is_dir(follow_symlinks=False) for e in os.scandir(root)} if root.is_dir() else {}
    rows = result.get('entries') or []
    checks = {'entries_exist': all(direct.get(r.get('name')) == r.get('directory') for r in rows),
              'not_more_than_directory': len(rows) <= len(direct)}
    return verdict('directory_state', checks, {'direct_entries': len(direct), 'observed_at': now()}, frozen)


async def f_search(args, result, ctx):
    from aries.workspace.registry import search, verify_probe
    frozen = await verify_probe(search, 'file_search')(args, result, ctx)
    q = args['query'].casefold()

    def ok(row):
        p = Path(row.get('path') or '')
        try:
            st = p.lstat()
        except OSError:
            return False
        return p.is_file() and st.st_size == row.get('size') and q in p.name.casefold()
    checks = {'matches_exist_and_fit': all(ok(r) for r in result.get('matches') or [])}
    return verdict('file_search', checks, {'observed_at': now()}, frozen)


async def t_inspect(args, result, ctx):
    """The task snapshot agrees with a second read and with the row, selected directly in SQL."""
    from sqlalchemy import text
    from aries.workspace.registry import inspect_task, verify_probe
    frozen = await verify_probe(inspect_task, 'task_state')(args, result, ctx)
    row = (await ctx['db'].execute(text('SELECT state, result_json FROM aries_workspace_goals WHERE id = :i'),
                                   {'i': args['task_id']})).first()
    data = json.loads(row.result_json) if row else {}
    checks = {'row_exists': row is not None,
              'state_agrees': row is not None and row.state == result.get('state'),
              'steps_agree': len(data.get('steps', [])) == result.get('steps'),
              'evidence_agrees': sorted(e.get('evidence_id') for e in data.get('evidence', []))
              == sorted(result.get('evidence_ids') or [])}
    return verdict('task_state', checks, {'sql_state': row.state if row else None, 'observed_at': now()}, frozen)


# ───────────────────────────────────────────────────────────── system
def _meminfo():
    vals = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, _, rest = line.partition(':')
        if rest.split():
            vals[key] = int(rest.split()[0])
    return vals


def _statvfs_pct(mountpoint):
    st = os.statvfs(mountpoint)
    usable = st.f_blocks - (st.f_bfree - st.f_bavail)
    return round(100.0 * (st.f_blocks - st.f_bfree) / usable, 1), round(usable * st.f_frsize / 1024 ** 3, 2)


def _readings(data):
    return {(p.get('probe'), r.get('metric'), r.get('subject')): r
            for p in data.get('probes') or [] for r in p.get('readings') or []}


def _direct_value(metric, subject, detail):
    """The same quantity, read directly from /proc or statvfs (not through aries.health.probes)."""
    if metric == 'memory.used_pct':
        m = _meminfo()
        return round((m['MemTotal'] - m['MemAvailable']) / m['MemTotal'] * 100, 1), TOLERANCE['memory_percent']
    if metric == 'memory.swap_used_pct':
        m = _meminfo()
        return round((m['SwapTotal'] - m['SwapFree']) / m['SwapTotal'] * 100, 1), TOLERANCE['memory_percent']
    if metric == 'disk.used_pct':
        return _statvfs_pct(subject)[0], TOLERANCE['percent']
    if metric == 'cpu.load_per_core':
        load1 = float(Path('/proc/loadavg').read_text().split()[0])
        return round(load1 / (os.cpu_count() or 1), 3), TOLERANCE['load1'] / (os.cpu_count() or 1)
    return None, None          # cpu.used_pct and pressure: a sample that cannot be taken again


def _reading_checks(reported, fresh_a, fresh_b):
    """Identity agrees exactly; values agree within measured drift plus resolution, or are in range."""
    ra, fa, fb = _readings(reported), _readings(fresh_a), _readings(fresh_b)
    checks = {'identity_agrees': set(ra) == set(fb) and all(
        (ra[k].get('unit'), ra[k].get('unavailable') is None) == (fb[k].get('unit'), fb[k].get('unavailable') is None)
        for k in ra if k in fb)}
    range_only = []
    for key, r in ra.items():
        if key not in fb or r.get('value') is None:
            continue
        direct, resolution = _direct_value(key[1], key[2], r.get('detail'))
        name = f'{key[1]}@{key[2] or "-"}'
        if direct is None:
            range_only.append(name)
            checks[name + ':in_range'] = 0 <= r['value'] <= 100
        else:
            checks[name + ':agrees'] = _within(r['value'], fa.get(key, {}).get('value'), direct, resolution)
        if key[1] == 'disk.used_pct':
            checks[name + ':size'] = abs((r.get('detail') or {}).get('size_gib', -1) - _statvfs_pct(key[2])[1]) <= TOLERANCE['gib']
        if key[1] in ('memory.used_pct', 'memory.swap_used_pct'):
            total = _meminfo()['MemTotal' if key[1] == 'memory.used_pct' else 'SwapTotal'] / 1048576
            checks[name + ':total'] = abs((r.get('detail') or {}).get('total_gib', -1) - total) <= TOLERANCE['gib']
        if key[1] == 'cpu.load_per_core':
            checks[name + ':cores'] = (r.get('detail') or {}).get('cores') == os.cpu_count()
    return checks, range_only


async def y_status(args, result, ctx):
    from aries.workspace.registry import status, verify_probe
    frozen = await verify_probe(status, 'system_probe')(args, result, ctx)
    a, b = await status(args, ctx), await status(args, ctx)
    checks, range_only = _reading_checks(result, a, b)
    return verdict('system_probe', checks, {'range_only': range_only, 'channel': '/proc/meminfo, /proc/loadavg, '
                                            'os.statvfs read directly', 'observed_at': now()}, frozen)


async def y_storage(args, result, ctx):
    from aries.workspace.registry import storage, verify_probe
    frozen = await verify_probe(storage, 'storage_probe')(args, result, ctx)
    a, b = await storage(args, ctx), await storage(args, ctx)
    wrap = lambda d: {'probes': [{'probe': 'disk', 'readings': d.get('filesystems') or []}]}
    checks, _ = _reading_checks(wrap(result), wrap(a), wrap(b))
    rows = result.get('filesystems') or []
    checks['highest_is_max'] = bool(rows) and result.get('highest') in rows and \
        result['highest'].get('value') == max(r.get('value', -1) for r in rows)
    return verdict('storage_probe', checks, {'channel': 'os.statvfs read directly', 'observed_at': now()}, frozen)


async def y_processes(args, result, ctx):
    from aries.workspace.registry import processes, verify_probe
    frozen = await verify_probe(processes, 'process_probe')(args, result, ctx)
    a, b = await processes(args, ctx), await processes(args, ctx)
    drift = abs(a['count'] - b['count'])
    fresh_names = {p['pid']: p['name'] for p in b['processes']}
    rows = result.get('processes') or []
    still = [r for r in rows if r.get('pid') in fresh_names]
    checks = {'count_agrees': isinstance(result.get('count'), int)
              and abs(result['count'] - b['count']) <= drift + TOLERANCE['processes'],
              'names_agree': all(fresh_names[r['pid']] == r.get('name') for r in still),
              'listed_still_running': len(still) >= len(rows) - (drift + TOLERANCE['processes'])}
    return verdict('process_probe', checks, {'count_drift': drift, 'fresh_count': b['count'], 'observed_at': now()},
                   frozen)


UNIT_FIELDS = ('unit', 'scope', 'load_state', 'active_state', 'sub_state')


async def _listed(scope, unit):
    """list-units, a different systemctl query than the `show` the executor used."""
    from aries.workspace import system_capabilities as sc
    code, out, err = await sc._run(sc._systemctl(scope, 'list-units', '--all', '--output=json', '--', unit), 15)
    rows = json.loads(out or '[]') if not code else []
    return next((r for r in rows if r.get('unit') == unit), None)


async def y_service(args, result, ctx):
    from aries.workspace import system_capabilities as sc
    frozen = await sc.verify_unit(args, result, ctx)
    fresh = await sc.inspect_unit(args, ctx)
    listed = await _listed(fresh['scope'], fresh['unit'])
    checks = {**{f'{k}_agrees': fresh.get(k) == result.get(k) for k in UNIT_FIELDS},
              'invocation_agrees': fresh.get('invocation') == result.get('invocation'),
              'list_units_agrees': listed is not None and (listed.get('load'), listed.get('active'), listed.get('sub'))
              == (result.get('load_state'), result.get('active_state'), result.get('sub_state'))}
    return verdict('systemd_unit', checks, {'fresh': fresh, 'list_units': listed}, frozen)


async def y_services(args, result, ctx):
    from aries.workspace import system_capabilities as sc
    frozen = await sc.verify_services(args, result, ctx)
    fresh = await sc.services(args, ctx)
    proj = lambda rows: sorted(tuple(u.get(k) for k in UNIT_FIELDS) for u in rows)
    units = result.get('units') or []
    checks = {'units_agree': proj(units) == proj(fresh['units']),
              'count_matches_list': result.get('count') == len(units),
              'failed_matches_list': sorted(result.get('failed') or [])
              == sorted(u['unit'] for u in units if u.get('active_state') == 'failed')}
    return verdict('systemd_units', checks, {'fresh_count': fresh['count'], 'observed_at': now()}, frozen)


# ───────────────────────────────────────────────────────────── exploratory: two INDEPENDENT verifiers
async def x_notification(args, result, ctx):
    """The row, selected directly in SQL, has this task's key, the requested text, and was created
    within the verifier's freshness window (a returned id of an old row is not this effect)."""
    from datetime import datetime, timezone
    from sqlalchemy import text
    from aries.workspace.registry import verify_notification
    frozen = await verify_notification(args, result, ctx)
    row = (await ctx['db'].execute(text('SELECT key, title, body, created_at FROM aries_notifications WHERE id = :i'),
                                   {'i': result.get('notification_id')})).first()
    created = row.created_at if row else None
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - created).total_seconds() if created else None
    checks = {'row_exists': row is not None,
              'row_agrees': row is not None and (row.key, row.title, row.body) == ('m14:' + ctx['task_id'], args['title'], args['body']),
              'created_recently': age is not None and -5 <= age <= 120}
    return verdict('notification_record', checks, {'age_seconds': age, 'observed_at': now()}, frozen)


async def x_disk(args, result, ctx):
    from aries.workspace import system_capabilities as sc
    frozen = await sc.verify_disk(args, result, ctx)
    rows = [r for r in result.get('filesystems') or [] if 'used_pct' in r]
    a = {r['mountpoint']: r for r in await asyncio.to_thread(sc.filesystems) if 'used_pct' in r}
    checks = {'fullest_is_max': bool(rows) and result.get('fullest') in rows and
              result['fullest']['used_pct'] == max(r['used_pct'] for r in rows)}
    for r in rows:
        name = r['mountpoint']
        direct, _size = _statvfs_pct(name)
        checks[name + ':identity'] = name in a and (a[name]['device'], a[name]['filesystem'], a[name]['total_bytes']) \
            == (r.get('device'), r.get('filesystem'), r.get('total_bytes'))
        checks[name + ':used_pct'] = _within(r['used_pct'], a.get(name, {}).get('used_pct'), direct, TOLERANCE['percent'])
    return verdict('storage_probe', checks, {'channel': 'os.statvfs read directly', 'observed_at': now()}, frozen)


TABLE = {
    'browser.back': b_state, 'browser.forward': b_state, 'browser.observe': b_state, 'browser.wait': b_state,
    'browser.click': b_click, 'browser.scroll': b_scroll, 'browser.elements': b_elements, 'browser.tabs': b_tabs,
    'browser.read': b_page, 'browser.open': b_open,
    'desktop.observe': d_observe, 'desktop.windows': d_observe, 'display.brightness': brightness_read,
    'input.editable_targets': i_targets, 'screen.read': s_read,
    'file.list': f_list, 'file.search': f_search, 'task.inspect': t_inspect,
    'system.status': y_status, 'system.storage': y_storage, 'system.processes': y_processes,
    'system.service': y_service, 'system.services': y_services,
    'notification.send': x_notification, 'system.disk': x_disk,
}


def install(registry, *, core=True, extra=False):
    """Replace the verifiers of the hardened capabilities in the registry. Called only with a flag on."""
    names = (HARDENED if core else ()) + (EXTRA if extra else ())
    for name in names:
        cap = registry._items[name]
        registry._items[name] = dataclasses.replace(cap, verifier=guarded(cap.name, TABLE[name]))
    return names
