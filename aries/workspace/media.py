"""Sound and playback: the part of the desktop ARIES could not touch.

Two different things live here because Linux keeps them apart, and conflating
them is the usual bug:

  the PLAYER   — play, pause, skip. Every media application on the session bus
                 speaks MPRIS2, so this works for Firefox, Spotify, VLC and
                 anything else without knowing which one is running.
  the OUTPUT   — how loud the machine is. That is PipeWire's, not the player's.
                 Muting Firefox and muting the speakers are different requests
                 and a person means the second one when they say "turn it down".

Everything shells out to gdbus and wpctl rather than binding a D-Bus library,
which is what aries/operator/desktop.py already does for the shell bridge. It
keeps the dependency list honest and it is what can be pasted into a terminal
when something misbehaves.

Nothing here reports success it did not observe. A player that accepts Next()
may have done nothing; the callers re-read PlaybackStatus and Volume afterwards.
"""
import json
import re
import subprocess

MPRIS_PREFIX = 'org.mpris.MediaPlayer2.'
MPRIS_PATH = '/org/mpris/MediaPlayer2'
PLAYER_IFACE = 'org.mpris.MediaPlayer2.Player'
ACTIONS = {'play': 'Play', 'pause': 'Pause', 'playpause': 'PlayPause',
           'stop': 'Stop', 'next': 'Next', 'previous': 'Previous'}
SINK = '@DEFAULT_AUDIO_SINK@'

# WHY THE DEFAULT SINK IS NOT TRUSTED AS A NAME
#
# Found 2026-10-03: with the screen locked and the monitor asleep, this session had
# no effective default sink at all, and `wpctl get-volume @DEFAULT_AUDIO_SINK@`
# answered
#
#     Translate ID error: '-1' is not a valid ID (returned by default-nodes-api)
#
# on stdout and **exited 0**. Every volume read and every volume verification went
# through that string, so the capability's own oracle was failing successfully —
# the project's founding bug, in the tool it uses to check itself. A concrete node
# id is resolved instead, and an unresolvable default is reported as a failure with
# the reason rather than as a reading.
TRANSLATE_FAILURES = ('translate id error', 'not a valid id', 'no such')


def _looks_like_failure(text):
    low = (text or '').casefold()
    return (not text) or any(marker in low for marker in TRANSLATE_FAILURES)


def resolve_sink():
    """A concrete sink to address, or a reason there is none.

    Prefers the session default when it resolves. Falls back to the only sink that
    exists, because one sink is unambiguous and a machine with audio hardware should
    not lose volume control because a monitor went to sleep. Refuses to guess among
    several.
    """
    probe, why = _run(['wpctl', 'get-volume', SINK])
    if probe is not None and not _looks_like_failure(probe):
        return SINK, None
    out, why = _run(['wpctl', 'status'])
    if out is None:
        return None, why or 'the audio graph could not be read'
    sinks, inside = [], False
    for line in out.splitlines():
        if 'Sinks:' in line:
            inside = True
            continue
        if inside and ('Sources:' in line or 'Filters:' in line):
            break
        if inside:
            found = re.search(r'(\d+)\.\s+(.+?)\s*\[', line)
            if found:
                sinks.append((found.group(1), found.group(2).strip(),
                              '*' in line.split('.')[0]))
    if not sinks:
        return None, 'this machine currently has no audio output at all'
    starred = [s for s in sinks if s[2]]
    chosen = starred[0] if starred else (sinks[0] if len(sinks) == 1 else None)
    if chosen is None:
        return None, ('several outputs exist and none is the default: '
                      + ', '.join(name for _, name, _ in sinks))
    return chosen[0], None


def _run(argv, timeout=8):
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f'{type(exc).__name__}: {exc}'
    if out.returncode != 0:
        return None, (out.stderr or out.stdout or 'command failed').strip()[:200]
    return out.stdout.strip(), None


def _unwrap(payload):
    """gdbus prints ('value',) or (<'value'>,) — take what is inside."""
    if payload is None:
        return None
    s = payload.strip()
    m = re.fullmatch(r"\((?:<)?(.*?)(?:>)?,\)", s, re.S)
    inner = m.group(1) if m else s
    return inner.strip().strip("'\"")


def _prop(bus, name, iface=PLAYER_IFACE):
    out, _ = _run(['gdbus', 'call', '--session', '--dest', bus, '--object-path', MPRIS_PATH,
                   '--method', 'org.freedesktop.DBus.Properties.Get', iface, name])
    return _unwrap(out)


def players():
    """Every media application currently on the session bus, with its state."""
    out, why = _run(['gdbus', 'call', '--session', '--dest', 'org.freedesktop.DBus',
                     '--object-path', '/org/freedesktop/DBus',
                     '--method', 'org.freedesktop.DBus.ListNames'])
    if out is None:
        return [], why
    found = []
    for bus in sorted(set(re.findall(r"'(" + re.escape(MPRIS_PREFIX) + r"[^']+)'", out))):
        found.append({
            'bus': bus,
            'name': bus[len(MPRIS_PREFIX):].split('.')[0],
            'identity': _prop(bus, 'Identity', 'org.mpris.MediaPlayer2') or '',
            'desktop_entry': _prop(bus, 'DesktopEntry', 'org.mpris.MediaPlayer2') or '',
            'status': _prop(bus, 'PlaybackStatus') or 'Unknown',
            'can_control': (_prop(bus, 'CanControl') or 'false') == 'true',
        })
    return found, None


def choose(found, wanted=None):
    """Which player did they mean?

    Preference order, and the reasoning: something already Playing is almost
    always the thing being talked about; failing that a single running player is
    unambiguous. With several idle players and no name, refuse — the project's
    rule is to say what it cannot tell rather than pick one and be wrong.
    """
    usable = [p for p in found if p['can_control']]
    if wanted:
        w = wanted.casefold()
        named = [p for p in usable if w in p['name'].casefold() or w in p['identity'].casefold()]
        if len(named) == 1:
            return named[0], None
        if not named:
            return None, f"no player called '{wanted}' is running"
        return None, 'several players match that name: ' + ', '.join(p['identity'] or p['name'] for p in named)
    if not usable:
        return None, 'no media player is running'
    playing = [p for p in usable if p['status'] == 'Playing']
    if len(playing) == 1:
        return playing[0], None
    if len(usable) == 1:
        return usable[0], None
    return None, 'several players are running: ' + ', '.join(p['identity'] or p['name'] for p in usable)


def control(action, wanted=None):
    """play / pause / playpause / stop / next / previous, verified afterwards."""
    method = ACTIONS.get(action)
    if method is None:
        return {'ok': False, 'detail': f'unknown playback action {action!r}'}
    found, why = players()
    if why:
        return {'ok': False, 'detail': why}
    player, why = choose(found, wanted)
    if player is None:
        return {'ok': False, 'detail': why}
    before = player['status']
    out, why = _run(['gdbus', 'call', '--session', '--dest', player['bus'],
                     '--object-path', MPRIS_PATH, '--method', PLAYER_IFACE + '.' + method])
    if out is None:
        return {'ok': False, 'detail': why, 'player': player['identity'] or player['name']}
    after = _prop(player['bus'], 'PlaybackStatus') or 'Unknown'
    # Next and Previous keep the status at Playing, so status is not evidence for
    # them; for the others a change of state is exactly what was asked for.
    expected = {'play': 'Playing', 'pause': 'Paused', 'stop': 'Stopped'}.get(action)
    met = (after == expected) if expected else (after != 'Stopped')
    if action == 'playpause':
        met = after != before
    return {'ok': True, 'verified': met, 'player': player['identity'] or player['name'],
            'was': before, 'now': after}


def volume(*, level=None, delta=None):
    """Read, set or nudge the machine's output volume. 0.0-1.5, not percent."""
    sink, why = resolve_sink()
    if sink is None:
        return {'ok': False, 'detail': why}
    current, why = _run(['wpctl', 'get-volume', sink])
    if current is None or _looks_like_failure(current):
        return {'ok': False, 'detail': why or f'wpctl could not read {sink}: {current!r}'}
    m = re.search(r'([\d.]+)', current)
    now = float(m.group(1)) if m else 0.0
    muted = 'MUTED' in current
    if level is None and delta is None:
        return {'ok': True, 'volume': now, 'muted': muted}
    target = level if level is not None else now + delta
    # Cap at 1.0. PipeWire will happily go past it, and software gain above the
    # hardware maximum is where speakers start to distort rather than get louder.
    target = max(0.0, min(1.0, target))
    out, why = _run(['wpctl', 'set-volume', sink, f'{target:.2f}'])
    if out is None:
        return {'ok': False, 'detail': why}
    again, _ = _run(['wpctl', 'get-volume', sink])
    if _looks_like_failure(again):
        return {'ok': False, 'detail': f'the volume was set but {sink} could not be read back'}
    m = re.search(r'([\d.]+)', again or '')
    reached = float(m.group(1)) if m else target
    return {'ok': True, 'verified': abs(reached - target) < 0.02,
            'was': now, 'volume': reached, 'requested': target}


def mute(on=True):
    sink, why = resolve_sink()
    if sink is None:
        return {'ok': False, 'detail': why}
    out, why = _run(['wpctl', 'set-mute', sink, '1' if on else '0'])
    if out is None:
        return {'ok': False, 'detail': why}
    state, _ = _run(['wpctl', 'get-volume', sink])
    if _looks_like_failure(state):
        return {'ok': False, 'detail': f'mute was issued but {sink} could not be read back'}
    is_muted = 'MUTED' in (state or '')
    return {'ok': True, 'verified': is_muted == on, 'muted': is_muted}


def resolve(query, timeout=25):
    """Find one YouTube video for a spoken request, without downloading it.

    yt-dlp rather than the Data API: no key to obtain, no quota, no account, and
    it keeps working when the page markup changes because keeping up with that is
    the entire point of the project. Metadata only — extract_flat stops it from
    resolving stream URLs, which is most of the time and none of the value here.
    """
    try:
        import yt_dlp
    except ImportError:
        return None, 'yt-dlp is not installed'
    opts = {'quiet': True, 'no_warnings': True, 'skip_download': True,
            'extract_flat': True, 'socket_timeout': timeout, 'noplaylist': True}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info('ytsearch1:' + query, download=False)
    except Exception as exc:
        return None, f'search failed: {type(exc).__name__}'
    entries = (info or {}).get('entries') or []
    if not entries:
        return None, f'nothing found for {query!r}'
    top = entries[0]
    if not top.get('id'):
        return None, 'the result carried no video id'
    return {'id': top['id'], 'title': top.get('title') or query,
            'uploader': top.get('uploader') or '',
            'url': 'https://www.youtube.com/watch?v=' + top['id']}, None


# Browsers refuse to start video with sound until the person has clicked the
# page, so "play X" opened a silent, paused YouTube — and a paused Firefox does
# not even register as an MPRIS player, so "play" had nothing to press. The
# global switch (media.autoplay.default=0) would let every site blare; this is
# the per-site permission Firefox itself writes when you allow autoplay for one
# site, granted to YouTube only.
AUTOPLAY_ORIGINS = ('https://www.youtube.com', 'https://youtube.com',
                    'https://m.youtube.com', 'https://music.youtube.com')


def firefox_profiles():
    """Default profile directories of the snap and the deb Firefox."""
    import configparser
    from pathlib import Path
    found = []
    for root in (Path.home() / 'snap/firefox/common/.mozilla/firefox', Path.home() / '.mozilla/firefox'):
        ini = root / 'profiles.ini'
        if not ini.is_file():
            continue
        cp = configparser.ConfigParser()
        try:
            cp.read(ini)
        except configparser.Error:
            continue
        for section in cp.sections():
            if section.startswith('Profile') and cp[section].get('Default') == '1' and cp[section].get('Path'):
                rel = cp[section].get('IsRelative', '1') == '1'
                found.append(root / cp[section]['Path'] if rel else Path(cp[section]['Path']))
    return [p for p in found if (p / 'permissions.sqlite').is_file()]


def ensure_youtube_autoplay(profiles=None):
    """Grant YouTube autoplay in each default profile. Idempotent.

    Firefox holds permissions.sqlite exclusively while running, so this only
    succeeds with the browser closed; it is retried on every play request until
    it has been written once, then it is a single read.
    """
    import sqlite3
    import time as _time
    from agentic_core.security import environments
    out = {}
    if environments.is_test() and not profiles:
        return out                                          # never the developer's real browser
    for profile in profiles or firefox_profiles():
        try:
            con = sqlite3.connect(str(profile / 'permissions.sqlite'), timeout=0.2)
            try:
                have = {r[0] for r in con.execute(
                    "SELECT origin FROM moz_perms WHERE type='autoplay-media' AND permission=1")}
                missing = [o for o in AUTOPLAY_ORIGINS if o not in have]
                now = int(_time.time() * 1000)
                for origin in missing:
                    con.execute("DELETE FROM moz_perms WHERE origin=? AND type='autoplay-media'", (origin,))
                    con.execute("INSERT INTO moz_perms(origin,type,permission,expireType,expireTime,modificationTime) "
                                "VALUES(?,?,1,0,0,?)", (origin, 'autoplay-media', now))
                con.commit()
                out[str(profile)] = 'granted' if missing else 'already'
            finally:
                con.close()
        except sqlite3.Error as exc:
            out[str(profile)] = f'deferred: {exc}'           # browser open; next time
    return out
