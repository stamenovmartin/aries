import sqlite3
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-media-autoplay')
from aries.workspace import media


def _profile(root: Path) -> Path:
    con = sqlite3.connect(root / 'permissions.sqlite')
    con.execute('CREATE TABLE moz_perms (id INTEGER PRIMARY KEY, origin TEXT, type TEXT, permission INTEGER,'
                ' expireType INTEGER, expireTime INTEGER, modificationTime INTEGER)')
    con.execute("INSERT INTO moz_perms(origin,type,permission,expireType,expireTime,modificationTime)"
                " VALUES('https://example.com','autoplay-media',2,0,0,0)")
    con.commit(); con.close()
    return root


async def test_youtube_only_and_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        p = _profile(Path(tmp))
        check('first call grants', media.ensure_youtube_autoplay([p]) == {str(p): 'granted'})
        check('second call changes nothing', media.ensure_youtube_autoplay([p]) == {str(p): 'already'})
        rows = sqlite3.connect(p / 'permissions.sqlite').execute(
            "SELECT origin, permission FROM moz_perms WHERE type='autoplay-media'").fetchall()
        allowed = {o for o, perm in rows if perm == 1}
        check('only YouTube origins are allowed', allowed == set(media.AUTOPLAY_ORIGINS))
        check("another site's own setting is untouched", ('https://example.com', 2) in rows)


async def test_open_browser_defers_and_tests_never_touch_real_profile():
    check('no profile is touched under APP_ENV=test', media.ensure_youtube_autoplay() == {})
    with tempfile.TemporaryDirectory() as tmp:
        p = _profile(Path(tmp))
        lock = sqlite3.connect(p / 'permissions.sqlite'); lock.execute('BEGIN EXCLUSIVE')
        out = media.ensure_youtube_autoplay([p])
        lock.rollback(); lock.close()
        check('a running Firefox (locked file) defers instead of failing', out[str(p)].startswith('deferred'))


if __name__ == '__main__':
    run_module(sys.modules[__name__])
