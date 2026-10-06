"""Connectivity and screen brightness: the two answers ARIES could not give.

THREE THINGS THAT ARE NOT THE SAME, and conflating them is the usual bug:

  the LINK    — a device is associated with an access point and holds an
                address. `nmcli device status` says "connected" the moment that
                is true, which is why "am I online?" answered from it is wrong
                about every router that is itself offline.
  NAME RESOLUTION — a resolver answered. It may have answered with a lie: on
                this machine `example.com` resolves to the ISP's own address,
                so a successful lookup proves a resolver replied and nothing
                more.
  the INTERNET — a packet left the LAN, reached a host outside it, and the
                handshake came back. Only this one is what a person means.

So `network.status` reports all three separately and never collapses them, plus
NetworkManager's own verdict, which is the only probe here that can see a
captive portal: it checks the *content* of an HTTP reply, and a hotel router
that answers every request with a login page passes a TCP handshake happily.

Reachability is probed against literal IPs (1.1.1.1:443, 8.8.8.8:53) precisely
so that DNS is not in the path — otherwise a broken resolver reads as a dead
internet and the two get fixed in the wrong order.

BRIGHTNESS ON THIS MACHINE: THERE IS NONE, AND THAT IS THE HONEST ANSWER.
Four mechanisms exist on Linux and all four are absent or unreachable here:

  * /sys/class/backlight/*        — the directory exists and is EMPTY. A desktop
                                    GPU driving an external monitor exposes no
                                    backlight device; there is nothing to write.
  * org.gnome.SettingsDaemon.Power.Screen — gsd-power does not export the
                                    interface at all (only `.Keyboard`, whose
                                    property set is empty). gsd exports Screen
                                    only when it found a backlight.
  * org.gnome.Mutter.DisplayConfig — GNOME 50 has SetBacklight(), but its
                                    `Backlight` property is (2, []): mutter
                                    knows of zero controllable backlights.
  * DDC/CI to the monitor         — /dev/i2c-* are root:root 0600, the user is
                                    in no i2c group, `ddcutil` is not installed
                                    and there is no compiler to build one.

Writing to a backlight goes through logind's SetBrightness, which is permitted
for the *active* session's own user with no polkit prompt — that is the only
unprivileged write path on hardware that has a backlight, and sysfs directly
does not work because those files are root-owned. It is implemented here and it
is UNVERIFIED on this machine: there is no backlight to aim it at.

So `display.brightness` reads as a probe that names every mechanism and why each
one is unavailable, and `display.set_brightness` refuses with that same evidence.
Neither is a no-op: they work where a backlight exists and say exactly what is
missing where one does not. They are two capabilities rather than one with an
optional level because registry.policy() gates every effect that is not 'read'
behind operator.enabled, and "how bright is the screen" must keep working when
operator actions are switched off.

Deliberately NOT shipped: dimming by pushing a scaled gamma ramp through
Mutter's SetCrtcGamma. It does work unprivileged — measured on this machine, a
1024-entry ramp read back exactly as written — but it is not brightness. It
crushes output levels, so contrast degrades and black stays black, and gsd-color
owns that ramp for night light and ICC profiles and will overwrite it without
warning. Calling it brightness would be the same lie as calling a muted player
a quiet one.

Everything shells out: `nmcli`/`ip` for the network, `busctl --json=short` for
D-Bus. busctl rather than the gdbus this project uses elsewhere, because these
replies are structures and `--json=short` is parsed by json.loads instead of by
a regex over gdbus's prose. Same reason as media.py: no bound libraries, and
every call can be pasted into a terminal when something misbehaves.
"""
import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from aries.workspace.capability_types import Capability, Input

BACKLIGHT_ROOT = Path('/sys/class/backlight')
MUTTER = ('org.gnome.Mutter.DisplayConfig', '/org/gnome/Mutter/DisplayConfig',
          'org.gnome.Mutter.DisplayConfig')
GSD_POWER = ('org.gnome.SettingsDaemon.Power', '/org/gnome/SettingsDaemon/Power',
             'org.gnome.SettingsDaemon.Power.Screen')
LOGIND = ('org.freedesktop.login1', '/org/freedesktop/login1', 'org.freedesktop.login1.Manager')
# Literal addresses, no names: this probe answers "did a packet leave the LAN",
# and a hostname here would make a resolver failure look like an outage.
REACH_TARGETS = (('1.1.1.1', 443), ('8.8.8.8', 53))
REACH_TARGETS_V6 = (('2606:4700:4700::1111', 443),)


def now():
    return datetime.now(timezone.utc).isoformat()


class NetworkCapabilityError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.retryable = code == 'NETWORK_UNREACHABLE'


class Empty(Input):
    pass


class ConnectionInput(Input):
    # A saved profile name, never a passphrase. See wifi_connect.
    name: str = Field(min_length=1, max_length=120)


class BrightnessInput(Input):
    # 1 rather than 0 is the floor on purpose: a screen set to zero is a screen
    # the user cannot see well enough to undo it with.
    level: int = Field(ge=1, le=100)


def _run(argv, timeout=8):
    """Same contract as media._run: (stdout, why). Never raises for a bad exit."""
    if not shutil.which(argv[0]):
        return None, argv[0] + ' is not installed'
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f'{type(exc).__name__}: {exc}'
    if out.returncode != 0:
        return None, (out.stderr or out.stdout or 'command failed').strip()[:300]
    return out.stdout.strip(), None


def _bus(kind, *args, timeout=8):
    """busctl --json=short, decoded. `kind` is 'call' or 'get-property'."""
    return _decode(_run(['busctl', '--user', '--json=short', kind, *args], timeout=timeout))


def _bus_system(kind, *args, timeout=8):
    return _decode(_run(['busctl', '--system', '--json=short', kind, *args], timeout=timeout))


def _decode(pair):
    """`get-property` puts the value in `data`; `call` puts a LIST of returns there."""
    out, why = pair
    if out is None:
        return None, why
    try:
        payload = json.loads(out)
    except ValueError as exc:
        return None, f'unreadable busctl reply: {type(exc).__name__}'
    if not isinstance(payload, dict) or 'data' not in payload:
        return None, 'busctl reply carried no data'
    return payload['data'], None


def _columns(line):
    r"""Split one `nmcli -t` row.

    nmcli escapes a colon inside a value as `\:` in its multi-column terse
    output — every BSSID contains five of them — so a plain str.split(':')
    shreds the row into MAC octets. Splitting on unescaped colons only is the
    whole job.
    """
    fields, current, escaped = [], [], False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == '\\':
            escaped = True
        elif ch == ':':
            fields.append(''.join(current))
            current = []
        else:
            current.append(ch)
    fields.append(''.join(current))
    return fields


def _pairs(text):
    """`nmcli -t ... device show` rows: KEY:VALUE, one key per line.

    Unlike the column output above, nmcli does NOT escape colons here, so an
    IPv6 address arrives raw. The key never contains a colon, so the first one
    is the separator and the rest of the line is the value; repeated keys
    (IP4.DNS[1], IP4.DNS[2]) collapse onto their base name as a list.
    """
    out = {}
    for line in text.splitlines():
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        out.setdefault(re.sub(r'\[\d+\]$', '', key.strip()), []).append(value.strip())
    return out


def _tcp(targets, timeout=2.0):
    """Did a handshake to a host outside the LAN complete? Which one, and how fast."""
    attempts = []
    for host, port in targets:
        started = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
        except OSError as exc:
            attempts.append({'target': f'{host}:{port}', 'reached': False,
                             'detail': f'{type(exc).__name__}: {exc}',
                             'ms': round((time.monotonic() - started) * 1000)})
            continue
        attempts.append({'target': f'{host}:{port}', 'reached': True,
                         'ms': round((time.monotonic() - started) * 1000)})
        break
    return any(a['reached'] for a in attempts), attempts


def _dns(name='example.com', timeout=3.0):
    started = time.monotonic()
    old = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        answers = sorted({info[4][0] for info in socket.getaddrinfo(name, None)})
    except OSError as exc:
        return False, {'name': name, 'resolved': False, 'detail': f'{type(exc).__name__}: {exc}',
                       'ms': round((time.monotonic() - started) * 1000)}
    finally:
        socket.setdefaulttimeout(old)
    # Resolved, not verified: a resolver that answers every name with the ISP's
    # own address also "resolves". This says a reply arrived, not that it is true.
    return True, {'name': name, 'resolved': True, 'answers': answers[:4],
                  'scope': 'a resolver replied; the answer is not authenticated',
                  'ms': round((time.monotonic() - started) * 1000)}


def devices():
    """Every NM device with its type, state and active connection."""
    out, why = _run(['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE,CONNECTION', 'device', 'status'])
    if out is None:
        return None, why
    found = []
    for line in out.splitlines():
        cols = _columns(line)
        if len(cols) < 4:
            continue
        found.append({'device': cols[0], 'type': cols[1], 'state': cols[2], 'connection': cols[3]})
    return found, None


def _addresses():
    """Addresses and the default route from `ip -j` — JSON, so no escaping to get wrong."""
    result = {'ipv4': [], 'ipv6': [], 'gateway': None, 'gateway_device': None,
              'links': [], 'source': 'ip -j addr / ip -j route'}
    out, why = _run(['ip', '-j', 'addr', 'show'])
    if out is None:
        result['unavailable'] = why
        return result
    try:
        links = json.loads(out)
    except ValueError:
        result['unavailable'] = 'ip -j produced unreadable JSON'
        return result
    for link in links:
        name = link.get('ifname', '')
        flags = link.get('flags') or []
        result['links'].append({'device': name, 'operstate': link.get('operstate'),
                                'up': 'UP' in flags, 'carrier': 'NO-CARRIER' not in flags})
        for info in link.get('addr_info') or []:
            if name == 'lo' or info.get('scope') == 'host':
                continue
            row = {'device': name, 'address': f"{info.get('local')}/{info.get('prefixlen')}",
                   'scope': info.get('scope')}
            result['ipv4' if info.get('family') == 'inet' else 'ipv6'].append(row)
    route, why = _run(['ip', '-j', 'route', 'show', 'default'])
    if route:
        try:
            for row in json.loads(route):
                if row.get('dst') == 'default' and row.get('gateway'):
                    result['gateway'], result['gateway_device'] = row['gateway'], row.get('dev')
                    break
        except ValueError:
            pass
    return result


def _resolvers(device):
    """Configured nameservers. NM first, /etc/resolv.conf as the no-nmcli fallback."""
    if device:
        out, _ = _run(['nmcli', '-t', '-f', 'IP4.DNS,IP6.DNS', 'device', 'show', device])
        if out:
            pairs = _pairs(out)
            servers = [v for key in ('IP4.DNS', 'IP6.DNS') for v in pairs.get(key, []) if v]
            if servers:
                return {'servers': servers, 'source': 'nmcli device show ' + device}
    try:
        text = Path('/etc/resolv.conf').read_text(encoding='utf-8', errors='replace')
    except OSError as exc:
        return {'servers': [], 'unavailable': f'{type(exc).__name__}: {exc}'}
    servers = re.findall(r'^\s*nameserver\s+(\S+)', text, re.M)
    note = ('127.0.0.53 is the systemd-resolved stub, not the upstream resolver'
            if any(s.startswith('127.0.0.53') for s in servers) else None)
    return {k: v for k, v in {'servers': servers[:6], 'source': '/etc/resolv.conf',
                              'note': note}.items() if v is not None}


def _ssid_of(device):
    """The SSID actually associated, from NM or from `iw` when NM is absent."""
    out, _ = _run(['nmcli', '-t', '-f', 'ACTIVE,SSID', 'device', 'wifi', 'list', 'ifname', device])
    for line in (out or '').splitlines():
        cols = _columns(line)
        if len(cols) >= 2 and cols[0] == 'yes':
            return cols[1], 'nmcli device wifi list'
    out, _ = _run(['iw', 'dev', device, 'link'])
    match = re.search(r'^\s*SSID:\s*(.+)$', out or '', re.M)
    return (match.group(1).strip(), 'iw dev link') if match else (None, None)


def status(*, probe=True):
    """What is connected, and whether the internet is actually reachable.

    `probe=False` skips every live probe and reports configuration only; the
    tests use it so that a machine with no network still exercises this code.
    """
    found, why = devices()
    addresses = _addresses()
    managed = [d for d in (found or []) if d['type'] != 'loopback']
    primary = None
    if addresses.get('gateway_device'):
        primary = next((d for d in managed if d['device'] == addresses['gateway_device']), None)
    if primary is None:
        primary = next((d for d in managed if d['state'].startswith('connected')), None)
    result = {
        'ok': True,
        'primary': dict(primary) if primary else None,
        'devices': managed,
        'addresses': {k: addresses[k] for k in ('ipv4', 'ipv6')},
        'links': addresses['links'],
        'gateway': addresses.get('gateway'),
        'dns': _resolvers(primary['device'] if primary else None),
        'observed_at': now(),
    }
    if why:
        result['manager_unavailable'] = why          # no nmcli: ip-only answer
    if primary and primary['type'] == 'wifi':
        ssid, source = _ssid_of(primary['device'])
        result['primary']['ssid'] = ssid
        result['primary']['ssid_source'] = source
    # The link is up in the only sense that matters for the next question: a
    # global address and a default route through it. NM saying "connected"
    # without a route is not a usable link.
    result['link_up'] = bool(addresses.get('gateway')) and any(
        r['scope'] == 'global' for r in addresses['ipv4'] + addresses['ipv6'])
    if not probe:
        result['probes'] = {'scope': 'configuration only; no reachability probe was run'}
        result['dns_resolves'] = None
        result['internet_reachable'] = None
        result['internet_reachable_ipv6'] = None
        result['nm_connectivity'] = None
        return result
    reachable, attempts = _tcp(REACH_TARGETS)
    resolves, dns_detail = _dns()
    # Only probe IPv6 when a global v6 address exists. Probing without one is a
    # guaranteed failure that would read as "IPv6 is broken" when it is absent.
    has_v6 = any(r['scope'] == 'global' for r in addresses['ipv6'])
    v6_reachable, v6_attempts = _tcp(REACH_TARGETS_V6) if has_v6 else (None, [])
    verdict, verdict_why = _run(['nmcli', '-t', 'networking', 'connectivity', 'check'], timeout=10)
    result.update({
        'internet_reachable': reachable,
        'internet_reachable_ipv6': v6_reachable,
        'dns_resolves': resolves,
        'nm_connectivity': verdict or None,
        'probes': {
            'tcp': attempts,
            'tcp_ipv6': v6_attempts if has_v6 else 'no global IPv6 address; not probed',
            'dns': dns_detail,
            'nm_connectivity': verdict or verdict_why,
            'scope': ('link_up is a route and an address; internet_reachable is a completed '
                      'TCP handshake outside the LAN; dns_resolves is only that a resolver '
                      'replied; nm_connectivity checks an HTTP reply and is the only one of '
                      'the four that can see a captive portal'),
        },
    })
    return result


def saved_connections():
    """Every saved NM profile, with the SSID a wifi profile actually joins.

    The profile name and the SSID are different fields and are allowed to
    differ, so matching a scan result against profile names alone silently
    reports a saved network as new.
    """
    out, why = _run(['nmcli', '-t', '-f', 'NAME,UUID,TYPE,DEVICE,AUTOCONNECT', 'connection', 'show'])
    if out is None:
        return None, why
    profiles = []
    for line in out.splitlines():
        cols = _columns(line)
        if len(cols) < 5 or cols[2] == 'loopback':
            continue
        row = {'name': cols[0], 'uuid': cols[1], 'type': cols[2],
               'device': cols[3], 'autoconnect': cols[4] == 'yes'}
        if cols[2] == '802-11-wireless' and len(profiles) < 50:
            detail, _ = _run(['nmcli', '-t', '-f', '802-11-wireless.ssid', 'connection', 'show', cols[1]])
            ssid = _pairs(detail or '').get('802-11-wireless.ssid', [])
            row['ssid'] = ssid[0] if ssid else None
        profiles.append(row)
    return profiles, None


def wifi_list():
    """Visible access points with signal strength, and which ones are saved.

    `--rescan no` on purpose: this is a read. Forcing a rescan makes the radio
    leave its channel and can stall traffic on the connection this is running
    over, which is not something a question about nearby networks should do. The
    list is NetworkManager's most recent scan, and how old that is is reported
    rather than hidden.
    """
    out, why = _run(['nmcli', '-t', '-f', 'IN-USE,SSID,BSSID,SIGNAL,FREQ,SECURITY',
                     'device', 'wifi', 'list', '--rescan', 'no'], timeout=20)
    if out is None:
        raise NetworkCapabilityError('CAPABILITY_UNAVAILABLE', why)
    profiles, _ = saved_connections()
    saved_ssids = {p['ssid'] for p in profiles or [] if p.get('ssid')}
    networks, seen = [], set()
    for line in out.splitlines():
        cols = _columns(line)
        if len(cols) < 6:
            continue
        ssid = cols[1]
        try:
            signal = int(cols[3])
        except ValueError:
            signal = None
        row = {'ssid': ssid or None, 'hidden': not ssid, 'bssid': cols[2], 'signal': signal,
               'frequency': cols[4], 'security': cols[5] or 'open',
               'in_use': cols[0].strip() == '*', 'saved': bool(ssid) and ssid in saved_ssids}
        # One SSID on several bands appears once per access point. Keep the
        # strongest; a list of duplicate names is not an answer to "what is
        # nearby", and the BSSID of the weak one is not what anyone wanted.
        if ssid and ssid in seen:
            previous = next(r for r in networks if r['ssid'] == ssid)
            if (signal or 0) > (previous['signal'] or 0):
                networks[networks.index(previous)] = row
            continue
        seen.add(ssid)
        networks.append(row)
    networks.sort(key=lambda r: (r['signal'] is None, -(r['signal'] or 0)))
    return {'networks': networks, 'count': len(networks),
            'saved_profiles': [p for p in profiles or [] if p.get('ssid')],
            'scan': 'NetworkManager cached scan; no rescan was forced',
            'observed_at': now()}


def connection_state(name):
    """`activated` / `activating` / `deactivated` for one saved profile, re-read.

    Two nmcli calls because they answer different questions and the first one
    alone is a trap: the whole `GENERAL.*` group exists only while a profile is
    ACTIVE, so `nmcli -t -f GENERAL.STATE connection show <inactive>` prints an
    empty string and exits 0. Reading only that, an inactive profile and a
    profile whose state could not be read look identical. The `connection.*`
    settings group is always present, so it establishes that the profile exists
    at all; a missing profile is the nonzero exit, which is a third answer again.
    """
    settings, why = _run(['nmcli', '-t', '-f', 'connection.id,connection.uuid,connection.type',
                          'connection', 'show', name])
    if settings is None:
        return None, why
    fields = _pairs(settings)
    # The docstring above is the rule; this is the line that enforces it. Measured
    # 2026-10-04: `nmcli` can print NOTHING for the settings group and exit 0, and
    # without this the fallbacks invented a profile — `connection.id` defaulted to the
    # requested name, uuid and type to empty — and then `GENERAL.STATE` was trusted on
    # top of it. That reported a profile as `activated` whose existence had never been
    # established, and in the all-blank case reported `deactivated`, which is a state
    # rather than the absence of one. A blank group is not an inactive profile.
    if not any(key.startswith('connection.') for key in fields):
        return None, (f'nmcli exited 0 for {name!r} but printed no connection.* settings, so '
                      f'whether the profile exists at all was never established; neither '
                      f'activated nor deactivated can be concluded')
    row = {'name': (fields.get('connection.id') or [name])[0],
           'uuid': (fields.get('connection.uuid') or [''])[0],
           'type': (fields.get('connection.type') or [''])[0],
           'state': 'deactivated', 'device': '', 'observed_at': now()}
    active, _ = _run(['nmcli', '-t', '-f', 'GENERAL.STATE,GENERAL.DEVICES',
                      'connection', 'show', name])
    if active:
        pairs = _pairs(active)
        row['state'] = (pairs.get('GENERAL.STATE') or ['deactivated'])[0] or 'deactivated'
        row['device'] = (pairs.get('GENERAL.DEVICES') or [''])[0]
    return row, None


def wifi_connect(name, *, wait=25):
    """Bring up an ALREADY-SAVED connection by name.

    NO PASSWORD PATH, deliberately. Joining a new network means ARIES accepting
    a passphrase, holding it in a request, a log line and a model's context, and
    then writing it into NetworkManager's store. ARIES has no business handling
    wifi passwords: the person types those into GNOME's own dialog, which is the
    one thing on the machine already trusted with them. So this activates
    profiles that already exist and refuses anything else by name.
    """
    profiles, why = saved_connections()
    if profiles is None:
        raise NetworkCapabilityError('CAPABILITY_UNAVAILABLE', why)
    wanted = name.strip()
    matches = [p for p in profiles if p['name'] == wanted or p.get('ssid') == wanted
               or p['uuid'] == wanted]
    if not matches:
        known = ', '.join(sorted({p.get('ssid') or p['name'] for p in profiles})) or 'none'
        raise NetworkCapabilityError(
            'TARGET_NOT_FOUND',
            f'No saved connection called {wanted!r}. ARIES can only bring up a profile that '
            f'already exists; saved: {known}. A new network must be joined in GNOME itself, '
            'because that is where its password belongs.')
    if len(matches) > 1:
        raise NetworkCapabilityError(
            'AMBIGUOUS', 'Several saved profiles match that name: '
            + ', '.join(f"{p['name']} ({p['uuid']})" for p in matches))
    profile = matches[0]
    before, _ = connection_state(profile['uuid'])
    # By UUID, not by name: two profiles may share a name and `con up id` would
    # then pick one of them for us.
    out, why = _run(['nmcli', '--wait', str(int(wait)), 'connection', 'up', 'uuid', profile['uuid']],
                    timeout=wait + 10)
    accepted = out is not None
    after, after_why = connection_state(profile['uuid'])
    return {'ok': True, 'profile': profile, 'accepted': accepted,
            'accept_detail': why if not accepted else out[:200],
            'was': (before or {}).get('state'), 'now': (after or {}).get('state'),
            # Accepted is not verified: nmcli exits 0 the moment NM reports the
            # activation finished, and the state is re-read to say so anyway.
            'verified': bool(after) and after['state'] == 'activated',
            'state_unavailable': after_why, 'observed_at': now()}


def _logind_session():
    """The object path of this user's active graphical session.

    GetSessionByPID is the obvious call and it fails for anything not itself in
    a login session (a systemd user unit, or an agent's shell), so the seat is
    what identifies the session that owns the screen: active, on a seat, and
    wayland or x11.
    """
    if os.environ.get('XDG_SESSION_ID'):
        path, why = _bus_system('call', *LOGIND, 'GetSession', 's', os.environ['XDG_SESSION_ID'])
        if path:
            return (path[0] if isinstance(path, list) else path), None
    sessions, why = _bus_system('call', *LOGIND, 'ListSessions', '')
    if not sessions:
        return None, why or 'logind listed no sessions'
    rows = sessions[0] if sessions and isinstance(sessions[0], list) else sessions
    uid = os.getuid()
    for row in rows:
        if len(row) < 5 or row[1] != uid or not row[3]:
            continue
        path = row[4]
        kind, _ = _bus_system('get-property', LOGIND[0], path, 'org.freedesktop.login1.Session', 'Type')
        active, _ = _bus_system('get-property', LOGIND[0], path, 'org.freedesktop.login1.Session', 'Active')
        if active is True and kind in ('wayland', 'x11'):
            return path, None
    return None, 'no active graphical logind session for this user'


def backlight_devices():
    """Kernel backlight devices, with whether we could write them directly."""
    found = []
    try:
        entries = sorted(BACKLIGHT_ROOT.iterdir())
    except OSError as exc:
        return found, f'{BACKLIGHT_ROOT} is unreadable: {type(exc).__name__}'
    for entry in entries:
        row = {'name': entry.name, 'path': str(entry)}
        for key, filename in (('raw', 'brightness'), ('max', 'max_brightness'),
                              ('actual', 'actual_brightness')):
            try:
                row[key] = int((entry / filename).read_text().strip())
            except (OSError, ValueError):
                row[key] = None
        row['writable'] = os.access(entry / 'brightness', os.W_OK)
        if row['max']:
            row['percent'] = round(100 * (row['actual'] if row['actual'] is not None
                                          else row['raw'] or 0) / row['max'])
        found.append(row)
    return found, None if found else f'{BACKLIGHT_ROOT} is empty: this machine has no backlight device'


def mutter_backlights():
    """GNOME 48+ exposes controllable backlights as (serial, [{connector,...}])."""
    data, why = _bus('get-property', *MUTTER, 'Backlight')
    if data is None:
        return None, None, why
    serial, rows = (data + [None, None])[:2] if isinstance(data, list) else (None, None)
    if not isinstance(rows, list):
        return serial, [], 'Mutter reported no readable Backlight array'
    # The per-entry keys are unverified here: mutter lists nothing on this
    # machine, so what a populated entry looks like has not been observed.
    return serial, rows, None if rows else 'Mutter lists no controllable backlight'


def gsd_screen_brightness():
    data, why = _bus('get-property', *GSD_POWER, 'Brightness')
    if data is None:
        return None, why
    return (data if isinstance(data, int) else None), None


def brightness_sources():
    """Every mechanism, what it reads, and why it cannot be written. Read-only."""
    sysfs, sysfs_why = backlight_devices()
    serial, mutter_rows, mutter_why = mutter_backlights()
    gsd, gsd_why = gsd_screen_brightness()
    session, session_why = _logind_session()
    i2c = sorted(str(p) for p in Path('/dev').glob('i2c-*'))
    return [
        {'mechanism': 'logind SetBrightness on /sys/class/backlight',
         'available': bool(sysfs) and session is not None,
         'devices': sysfs, 'session': session,
         'unavailable': sysfs_why or session_why,
         'writes': 'org.freedesktop.login1.Session.SetBrightness — no polkit prompt for the '
                   'active session; writing the sysfs file directly is root-only'},
        {'mechanism': 'org.gnome.Mutter.DisplayConfig SetBacklight',
         'available': bool(mutter_rows), 'serial': serial, 'backlights': mutter_rows,
         'unavailable': mutter_why},
        {'mechanism': 'org.gnome.SettingsDaemon.Power.Screen Brightness',
         'available': gsd is not None, 'brightness': gsd, 'unavailable': gsd_why},
        {'mechanism': 'DDC/CI to the monitor', 'available': False,
         'unavailable': ('no ddcutil, and ' + (f'{len(i2c)} /dev/i2c-* nodes are not writable by '
                                               'this user' if i2c else 'no /dev/i2c-* nodes exist')),
         'writable_i2c': [p for p in i2c if os.access(p, os.W_OK)]},
    ]


def brightness(level=None):
    """Read the screen brightness, or set it to a percentage and re-read it."""
    sources = brightness_sources()
    usable = [s for s in sources if s['available']]
    current = None
    for source in usable:
        if source['mechanism'].startswith('logind') and source['devices']:
            current = source['devices'][0].get('percent')
        elif source['mechanism'].startswith('org.gnome.Mutter') and source['backlights']:
            entry = source['backlights'][0]
            current = entry.get('value') if isinstance(entry, dict) else None
        elif source['mechanism'].startswith('org.gnome.SettingsDaemon'):
            current = source['brightness']
        if current is not None:
            break
    if level is None:
        return {'ok': True, 'brightness': current, 'sources': sources,
                'controllable': bool(usable),
                'detail': None if usable else
                'This machine exposes no screen brightness control: '
                + '; '.join(s['unavailable'] for s in sources if s.get('unavailable')),
                'observed_at': now()}
    if not usable:
        raise NetworkCapabilityError(
            'CAPABILITY_UNAVAILABLE',
            'Nothing on this machine can set the screen brightness. '
            + '; '.join(s['unavailable'] for s in sources if s.get('unavailable'))
            + '. On a desktop driving an external monitor the brightness lives in the '
              'monitor and is reachable only over DDC/CI, which needs write access to '
              '/dev/i2c-* that this user does not have.')
    target = max(1, min(100, int(level)))
    chosen, why = usable[0], None
    if chosen['mechanism'].startswith('logind'):
        device = chosen['devices'][0]
        raw = max(1, round(target * device['max'] / 100)) if device.get('max') else target
        _, why = _bus_system('call', LOGIND[0], chosen['session'],
                             'org.freedesktop.login1.Session', 'SetBrightness', 'ssu',
                             'backlight', device['name'], str(raw))
    elif chosen['mechanism'].startswith('org.gnome.Mutter'):
        entry = chosen['backlights'][0]
        _, why = _bus('call', *MUTTER, 'SetBacklight', 'usi',
                      str(chosen['serial']), str(entry.get('connector', '')), str(target))
    else:
        # busctl spells a variant as its type and value in SEPARATE argv slots:
        # 'ssv' then iface, property, 'i', value. One "i 50" string is refused.
        _, why = _bus('call', GSD_POWER[0], GSD_POWER[1], 'org.freedesktop.DBus.Properties',
                      'Set', 'ssv', GSD_POWER[2], 'Brightness', 'i', str(target))
    reached = brightness(None)
    return {'ok': why is None, 'detail': why, 'mechanism': chosen['mechanism'],
            'was': current, 'requested': target, 'brightness': reached['brightness'],
            # Within one step: a backlight with 20 hardware levels cannot land on
            # every percentage, so demanding equality would fail a correct write.
            'verified': why is None and reached['brightness'] is not None
            and abs(reached['brightness'] - target) <= 5,
            'sources': reached['sources'], 'observed_at': now()}


async def observe_status(args, ctx):
    return await asyncio.to_thread(status)


async def verify_status(args, result, ctx):
    fresh = await asyncio.to_thread(status)
    # A second independent probe. The verdict is that the reachability answer
    # held, not that the executor said so.
    met = (fresh['internet_reachable'] == result['internet_reachable']
           and fresh['link_up'] == result['link_up'])
    return {'met': met, 'type': 'network_state', 'data': fresh}


async def observe_wifi(args, ctx):
    return await asyncio.to_thread(wifi_list)


async def verify_wifi(args, result, ctx):
    fresh = await asyncio.to_thread(wifi_list)
    # SSIDs come and go between two scans; that the saved set still matches is
    # what this can honestly assert.
    before = {r['ssid'] for r in result['networks'] if r['saved']}
    after = {r['ssid'] for r in fresh['networks'] if r['saved']}
    return {'met': before == after, 'type': 'wifi_scan', 'data': fresh}


async def connect(args, ctx):
    out = await asyncio.to_thread(wifi_connect, args['name'])
    if not out['accepted']:
        raise NetworkCapabilityError('NON_RETRYABLE', out['accept_detail'] or 'nmcli refused the request')
    return out


async def verify_connect(args, result, ctx):
    state, why = await asyncio.to_thread(connection_state, result['profile']['uuid'])
    live = await asyncio.to_thread(status)
    return {'met': bool(state) and state['state'] == 'activated',
            'type': 'network_state',
            'data': {'connection': state, 'unavailable': why, 'network': live,
                     'scope': 'connection re-read after activation, not the nmcli exit code'}}


async def read_brightness(args, ctx):
    return await asyncio.to_thread(brightness, None)


async def verify_read_brightness(args, result, ctx):
    fresh = await asyncio.to_thread(brightness, None)
    return {'met': True, 'type': 'display_state', 'data': fresh}


async def set_brightness(args, ctx):
    out = await asyncio.to_thread(brightness, args['level'])
    if not out['ok']:
        raise NetworkCapabilityError('NON_RETRYABLE', out.get('detail') or 'the brightness request failed')
    return out


async def verify_set_brightness(args, result, ctx):
    fresh = await asyncio.to_thread(brightness, None)
    return {'met': fresh['brightness'] is not None and abs(fresh['brightness'] - args['level']) <= 5,
            'type': 'display_state', 'data': fresh}


def register(registry):
    registry.register(Capability(
        'network.status',
        'Observe connectivity: link, addresses, gateway, DNS, and separately whether the '
        'internet is actually reachable',
        Empty, observe_status, verify_status, timeout_seconds=20))
    registry.register(Capability(
        'network.wifi_list',
        'List visible wifi networks with signal strength and which are already saved; '
        'no rescan is forced',
        Empty, observe_wifi, verify_wifi, timeout_seconds=30))
    registry.register(Capability(
        'network.wifi_connect',
        'Bring up an ALREADY-SAVED connection by name; ARIES never accepts a wifi password',
        ConnectionInput, connect, verify_connect,
        effect='network', risk_level='high', requires_approval=True, timeout_seconds=60))
    # Read and set are two capabilities, not one with an optional level: policy()
    # gates every effect that is not 'read' behind operator.enabled, and "how
    # bright is the screen" must not stop working when operator actions are off.
    registry.register(Capability(
        'display.brightness',
        'Read the screen brightness; reports every mechanism it probed and why none is '
        'available when this machine has no brightness control',
        Empty, read_brightness, verify_read_brightness, timeout_seconds=20))
    registry.register(Capability(
        'display.set_brightness',
        'Set the screen brightness to a percentage and re-read it; refuses with evidence '
        'when the hardware exposes no backlight',
        BrightnessInput, set_brightness, verify_set_brightness,
        effect='display', requires_approval=True, timeout_seconds=20))
