"""ARIES_VERIFY_SCOPE: a differential side-effect check around independent verifiers.

docs/AUDIT.md section 4e. In H8 the operator `side_effect_outside_scope` performs the
honest effect and then one change outside the requested target; 0 of 14 such mutants
were killed, in every run, because every independent verifier re-reads the TARGET and
nothing looks next to it. This module adds the missing comparison and nothing else:

* the executor is wrapped so that, immediately before it runs, the declared scope is
  snapshotted into the step's ctx;
* the verifier is wrapped so that the frozen verifier runs first, unchanged, and then
  the scope is snapshotted again and compared; a change to anything in it other than
  the declared target makes the verdict not met (status OUTSIDE_SCOPE_CHANGED), and a
  scope that cannot be read makes it UNVERIFIED (fail closed, as the hardened
  verifiers do). The frozen verdict is kept in `scope.frozen_met`.

Scopes, one per effect class:
  files          the parent folder of every path argument, one level (name, type,
                 size, mtime_ns); the declared targets are the paths the capability is
                 asked to create, change or remove.
  windows        every window other than the target (geometry, minimised, maximised,
                 workspace, monitor, and whether it exists). Focus and titles are not
                 compared: focus moves as a consequence of the target's change and
                 titles change on their own.
  notifications  the notification table: exactly the one returned row may be new, and
                 none may disappear. Edits to existing rows are not seen.

Known limits, stated rather than hidden: a change in a SIBLING folder of the target
folder is outside every snapshot and is not caught; a concurrent writer in the same
folder, window set or table is reported as a side effect (a false alarm). A verifier
run with no snapshot in its ctx (the completion recheck) is left as it was, marked
NOT_CHECKED.

Designed after the H8 baseline: exploratory, not part of the confirmatory H8 test.
Installed by aries/workspace/registry.py only when the flag is on; off, the registry
holds the frozen function objects.
"""
from __future__ import annotations

import dataclasses
import os

KEY = '_aries_scope_before'
MAX_ENTRIES = 10000

SCOPED = {
    'file.write': 'files', 'file.copy': 'files', 'file.edit': 'files', 'file.move': 'files',
    'file.rename': 'files', 'browser.download': 'files',
    'desktop.close': 'windows', 'desktop.maximize': 'windows', 'desktop.minimize': 'windows',
    'desktop.move': 'windows', 'desktop.resize': 'windows', 'desktop.tile': 'windows',
    'desktop.unmaximize': 'windows',
    'notification.send': 'notifications',
}

#: Path arguments whose entries the capability is asked to create, change or remove.
#: A copy declares only its destination: a source that changes is a side effect.
TARGETS = {'file.write': ('path',), 'browser.download': ('path',), 'file.edit': ('path',),
           'file.copy': ('destination',), 'file.move': ('path', 'destination'),
           'file.rename': ('path', 'destination')}
PATH_ARGUMENTS = ('path', 'destination')
WINDOW_FIELDS = ('geometry', 'minimized', 'maximized', 'workspace', 'monitor')


class ScopeUnreadable(RuntimeError):
    pass


def _where(raw):
    absolute = os.path.abspath(os.path.expanduser(str(raw)))
    return os.path.realpath(os.path.dirname(absolute)), os.path.basename(absolute)


def _listing(folder):
    """{name: [type, size, mtime_ns]} one level deep, or None when the folder does not exist."""
    out = {}
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if len(out) >= MAX_ENTRIES:
                    raise ScopeUnreadable(f'{folder} has more than {MAX_ENTRIES} entries')
                st = entry.stat(follow_symlinks=False)
                kind = 'd' if entry.is_dir(follow_symlinks=False) else 'l' if entry.is_symlink() else 'f'
                out[entry.name] = [kind, st.st_size if kind == 'f' else 0, st.st_mtime_ns if kind != 'd' else 0]
    except FileNotFoundError:
        return None
    return out


async def _windows(ctx):
    from aries.workspace.desktop_capabilities import observe
    return (await observe({}, ctx))['windows']


async def snapshot(name, args, ctx):
    kind = SCOPED[name]
    if kind == 'files':
        folders = sorted({_where(args[k])[0] for k in PATH_ARGUMENTS if args.get(k)})
        return {'folders': {f: _listing(f) for f in folders}}
    if kind == 'windows':
        return {'windows': {str(w.get('window_id')): {k: w.get(k) for k in WINDOW_FIELDS}
                            for w in await _windows(ctx)}}
    from sqlalchemy import func, select
    from aries.notify import AriesNotification
    count, top = (await ctx['db'].execute(select(func.count(AriesNotification.id),
                                                 func.max(AriesNotification.id)))).one()
    return {'count': int(count or 0), 'max_id': int(top or 0)}


async def changes(name, args, result, before, ctx):
    """What changed in the snapshotted scope apart from the declared target."""
    kind = SCOPED[name]
    found = []
    if kind == 'files':
        declared = {_where(args[k]) for k in TARGETS[name] if args.get(k)}
        for folder, old in before['folders'].items():
            new = _listing(folder)
            old, new = old or {}, new or {}
            for entry in sorted(set(old) | set(new)):
                if (folder, entry) in declared or old.get(entry) == new.get(entry):
                    continue
                change = 'added' if entry not in old else 'removed' if entry not in new else 'modified'
                found.append({'folder': folder, 'name': entry, 'change': change,
                              'before': old.get(entry), 'after': new.get(entry)})
        return found
    if kind == 'windows':
        target = str(args.get('window_id'))
        old = {k: v for k, v in before['windows'].items() if k != target}
        new = {str(w.get('window_id')): {k: w.get(k) for k in WINDOW_FIELDS} for w in await _windows(ctx)
               if str(w.get('window_id')) != target}
        for window in sorted(set(old) | set(new)):
            if old.get(window) != new.get(window):
                change = 'added' if window not in old else 'removed' if window not in new else 'modified'
                found.append({'window_id': window, 'change': change,
                              'before': old.get(window), 'after': new.get(window)})
        return found
    from sqlalchemy import func, select
    from aries.notify import AriesNotification
    db = ctx['db']
    ids = [int(i) for i in (await db.execute(select(AriesNotification.id).where(
        AriesNotification.id > before['max_id']))).scalars().all()]
    allowed = {int((result or {}).get('notification_id') or -1)}
    found += [{'notification_id': i, 'change': 'added'} for i in ids if i not in allowed]
    count = int((await db.execute(select(func.count(AriesNotification.id)))).scalar() or 0)
    if count != before['count'] + len(ids):
        found.append({'change': 'removed', 'rows': before['count'] + len(ids) - count})
    return found


def _executor(name, original):
    async def execute(args, ctx):
        try:
            ctx[KEY] = {'capability': name, 'before': await snapshot(name, args, ctx)}
        except Exception as exc:                                    # noqa: BLE001
            ctx[KEY] = {'capability': name, 'error': f'{type(exc).__name__}: {str(exc)[:300]}'}
        return await original(args, ctx)
    execute.scope_kind = SCOPED[name]
    execute.frozen = original
    return execute


def _verifier(name, original):
    async def verify(args, result, ctx):
        verdict = dict(await original(args, result, ctx))
        frozen_met = verdict.get('met') is True
        armed = (ctx or {}).get(KEY)
        if not armed or armed.get('capability') != name:
            verdict['scope'] = {'status': 'NOT_CHECKED', 'why': 'no pre-execution snapshot in this context'}
            return verdict
        why = armed.get('error')
        found = None
        if why is None:
            try:
                found = await changes(name, args, result, armed['before'], ctx)
            except Exception as exc:                                # noqa: BLE001
                why = f'{type(exc).__name__}: {str(exc)[:300]}'
        if why is not None:
            verdict.update(met=False, status='UNVERIFIED')
            verdict['scope'] = {'status': 'UNVERIFIED', 'why': why, 'frozen_met': frozen_met}
            return verdict
        if found:
            verdict['met'] = False
            verdict['scope'] = {'status': 'OUTSIDE_SCOPE_CHANGED', 'changes': found[:50], 'frozen_met': frozen_met}
        else:
            verdict['scope'] = {'status': 'IN_SCOPE', 'changes': [], 'frozen_met': frozen_met}
        return verdict
    verify.scope_kind = SCOPED[name]
    verify.frozen = original
    return verify


def wrap(cap):
    return dataclasses.replace(cap, executor=_executor(cap.name, cap.executor),
                               verifier=_verifier(cap.name, cap.verifier))


def install(registry):
    """Wrap the scoped capabilities in the registry. Called only with the flag on."""
    for name in SCOPED:
        registry._items[name] = wrap(registry._items[name])
    return tuple(SCOPED)
