"""ARIES may read its own code and may not write it.

This is a security property with a measurement behind it, not a principle. On
2026-09-29 `checked_path(write=True)` allowed `aries/workspace/capabilities.py`
itself: the ARIES tree lives under the user's home, so the home confinement, the
symlink check and the hidden-path check all waved it through, and
`privacy.excluded_paths` held only `~/.ssh` and `~/.gnupg`.

Nothing could silently rewrite running code even then — `create_file` refuses to
overwrite an existing file and `file.edit` requires approval — but new files
could appear inside the package unapproved. A hole in the fence rather than the
lock, and the kind that only stays closed if a test keeps it closed.

Reads stay allowed on purpose. ARIES answering "what can you do" from its own
catalogue, and any future reviewed self-development, both need to read the source.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, reset_db, run_module
bootstrap('aries-self-protection')
from agentic_core.database.base import async_session
from aries.workspace import capabilities as cap


async def _ready():
    """Every test here reads privacy.excluded_paths, so the tables must exist."""
    await reset_db()


async def _refused(target):
    async with async_session() as db:
        try:
            await cap.checked_path(db, target, write=True)
            return None
        except ValueError as exc:
            return str(exc)


async def test_its_own_source_is_not_a_write_target():
    await _ready()
    check('the installation root is where this file lives',
          (cap.INSTALLATION / 'aries' / 'workspace' / 'capabilities.py').is_file())
    for target in ('~/aries/aries/workspace/capabilities.py',
                   '~/aries/aries/speech/engines.py',
                   '~/aries/scripts/aries-voice',
                   '~/aries/var/anything.txt',
                   '~/aries/brand-new-module.py'):
        why = await _refused(target)
        check(f'refused: {target}', why is not None and 'installation' in why)


async def test_reading_its_own_source_is_still_allowed():
    """A refusal that also blocked reads would break introspection and any
    reviewed self-development before either was written."""
    await _ready()
    async with async_session() as db:
        path = await cap.checked_path(db, '~/aries/aries/speech/engines.py', write=False)
        check('ARIES can still read its own code', path.name == 'engines.py')


async def test_the_users_own_files_are_untouched_by_the_guard():
    """The guard must not become a second, wider confinement. Cyrillic paths are
    in here because this user's folders are named in Macedonian and an alphabet
    has never been a reason to refuse a path."""
    await _ready()
    async with async_session() as db:
        for target in ('~/Documents/notes.txt', '~/Документи/белешка.txt',
                       '~/Мои проекти/Скопје/датотека.md', '~/Downloads/тест.txt'):
            path = await cap.checked_path(db, target, write=True)
            check(f'still allowed: {target}', str(path).startswith(str(Path.home())))


async def test_the_older_guards_did_not_go_away():
    await _ready()
    outside = await _refused('/etc/passwd')
    check(f'outside home is still refused ({outside})', outside is not None)
    home = await _refused('~')
    check('the home folder itself is still refused', home is not None)
    hidden = await _refused('~/.config/aries/x')
    check('hidden configuration is still refused', hidden is not None and 'Hidden' in hidden)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
