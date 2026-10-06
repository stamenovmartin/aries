"""Network and display capabilities.

Two rules this file obeys, because breaking either ends the session it runs in:
no test requires a network to be present, and no test changes connectivity. The
parsing and verdict logic is driven from recorded `nmcli` output, so it is
exercised on a machine with the radio off; the only live calls are read-only and
they assert shape, never a particular SSID or a particular answer.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-network-capabilities')
from aries.workspace import network_capabilities as nc

# Recorded from this machine, including nmcli's escaping of the colons inside a
# BSSID, which is the whole reason _columns exists.
WIFI_ROWS = (
    r'*:Juninho-2.4G:24\:91\:BB\:8D\:B1\:18:63:2417 MHz:WPA1 WPA2',
    r' :Juninho-2.4G:24\:91\:BB\:8D\:B1\:19:88:5180 MHz:WPA1 WPA2',
    r' :Telekom-424362:D8\:D8\:E5\:00\:13\:E0:54:2437 MHz:WPA2 WPA3',
    r' ::A4\:CF\:D2\:7A\:2C\:9D:27:2462 MHz:',
)
CONNECTIONS = ('Home wifi:b340b690-c7c8-4894-9e7a-41a829ff4e22:802-11-wireless:wlan0:yes\n'
               'netplan-enp4s0:6051479d-df65-3705-9f22-99be0f7f2e09:802-3-ethernet::yes\n'
               'lo:205c9ecc-2687-4536-a6ff-20f75d98767c:loopback:lo:yes')
ADDR_JSON = ('[{"ifindex":3,"ifname":"wlan0","flags":["BROADCAST","UP","LOWER_UP"],'
             '"operstate":"UP","addr_info":[{"family":"inet","local":"192.168.100.5",'
             '"prefixlen":24,"scope":"global"},{"family":"inet6","local":"fe80::1",'
             '"prefixlen":64,"scope":"link"}]}]')
ROUTE_JSON = '[{"dst":"default","gateway":"192.168.100.1","dev":"wlan0"}]'


class Fake:
    """Stands in for nc._run. Records every argv so a test can prove what ran."""

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def __call__(self, argv, timeout=8):
        self.calls.append(list(argv))
        joined = ' '.join(argv)
        # EVERY token of a key must appear. A single substring is not enough:
        # "connection show" is in the argv of the profile list AND of every
        # per-field query, so it would answer all of them with the first reply.
        for key, reply in self.replies.items():
            if all(token in joined for token in key.split()):
                return reply
        return None, 'not stubbed: ' + joined


def patched(**attrs):
    """Swap module attributes and hand back a restore callable."""
    original = {k: getattr(nc, k) for k in attrs}
    for k, v in attrs.items():
        setattr(nc, k, v)
    return lambda: [setattr(nc, k, v) for k, v in original.items()]


NETWORK_STUBS = {
    'device status': ('wlan0:wifi:connected:Home wifi\nenp4s0:ethernet:unavailable:', None),
    'ip -j addr': (ADDR_JSON, None),
    'ip -j route': (ROUTE_JSON, None),
    'device show wlan0': ('IP4.DNS[1]:192.168.100.1\nIP4.DNS[2]:1.1.1.1', None),
    'device wifi list ifname': (' :Other:x\nyes:Home network:y', None),
    'networking connectivity check': ('full', None),
}


def test_terse_columns_survive_escaped_colons():
    cols = nc._columns(WIFI_ROWS[0])
    check('six columns, not eleven MAC fragments', len(cols) == 6)
    check('BSSID is reassembled', cols[2] == '24:91:BB:8D:B1:18')
    check('SSID and signal intact', (cols[1], cols[3]) == ('Juninho-2.4G', '63'))
    check('a hidden SSID is an empty field, not a missing column',
          len(nc._columns(WIFI_ROWS[3])) == 6 and nc._columns(WIFI_ROWS[3])[1] == '')
    check('an escaped backslash stays one backslash',
          nc._columns(r'a\\b:c') == ['a\\b', 'c'])


def test_key_value_rows_keep_raw_ipv6_and_collapse_indices():
    # `nmcli ... device show` does NOT escape colons, unlike the column output,
    # so an IPv6 address arrives raw and only the first colon is a separator.
    pairs = nc._pairs('IP6.ADDRESS[1]:fe80::ae16:c201/64\nIP4.DNS[1]:192.168.100.1\n'
                      'IP4.DNS[2]:1.1.1.1\nGENERAL.STATE:100 (connected)')
    check('IPv6 value is not truncated at its first colon',
          pairs['IP6.ADDRESS'] == ['fe80::ae16:c201/64'])
    check('indexed keys collapse onto one list', pairs['IP4.DNS'] == ['192.168.100.1', '1.1.1.1'])
    check('a value containing a space and a paren survives', pairs['GENERAL.STATE'] == ['100 (connected)'])


def test_status_without_probes_reports_unknown_rather_than_false():
    restore = patched(_run=Fake(NETWORK_STUBS))
    try:
        state = nc.status(probe=False)
    finally:
        restore()
    check('link_up is answered from the route and the address', state['link_up'] is True)
    # False would be a claim that the internet is unreachable. Nothing was
    # measured, so the only honest value is None.
    for key in ('internet_reachable', 'dns_resolves', 'nm_connectivity'):
        check(f'{key} is unknown, not False', state[key] is None)
    check('the gateway is read', state['gateway'] == '192.168.100.1')
    check('DNS servers are read', state['dns']['servers'] == ['192.168.100.1', '1.1.1.1'])
    check('loopback is not offered as a connection',
          all(d['type'] != 'loopback' for d in state['devices']))
    check('the link-local address is not counted as global',
          state['addresses']['ipv6'][0]['scope'] == 'link')


def test_link_up_and_internet_reachable_are_separate_answers():
    """The bug this module exists to avoid: a connected radio behind a dead router."""
    restore = patched(_run=Fake(dict(NETWORK_STUBS, **{
                          'networking connectivity check': ('limited', None)})),
                      _tcp=lambda targets, timeout=2.0: (False, [
                          {'target': '1.1.1.1:443', 'reached': False, 'detail': 'TimeoutError'}]),
                      _dns=lambda name='example.com', timeout=3.0: (True, {'resolved': True}))
    try:
        state = nc.status()
    finally:
        restore()
    check('the link is up', state['link_up'] is True)
    check('the internet is NOT reported reachable', state['internet_reachable'] is False)
    check('a resolver answering is not evidence of reach', state['dns_resolves'] is True)
    check("NetworkManager's own verdict is carried through", state['nm_connectivity'] == 'limited')
    check('no global IPv6, so IPv6 was not probed at all',
          state['internet_reachable_ipv6'] is None
          and state['probes']['tcp_ipv6'] == 'no global IPv6 address; not probed')
    check('the answer says what each signal means',
          'captive portal' in state['probes']['scope'])


def test_captive_portal_is_only_visible_in_the_manager_verdict():
    # A hotel router completes TCP handshakes and resolves names; only the
    # checked HTTP reply shows the login page. All four signals are needed.
    restore = patched(_run=Fake(dict(NETWORK_STUBS, **{
                          'networking connectivity check': ('portal', None)})),
                      _tcp=lambda targets, timeout=2.0: (True, [{'target': '1.1.1.1:443', 'reached': True}]),
                      _dns=lambda name='example.com', timeout=3.0: (True, {'resolved': True}))
    try:
        state = nc.status()
    finally:
        restore()
    check('the TCP probe alone would have said yes', state['internet_reachable'] is True)
    check('the portal is still reported', state['nm_connectivity'] == 'portal')


def test_status_degrades_honestly_without_networkmanager():
    restore = patched(_run=Fake({'ip -j addr': (ADDR_JSON, None), 'ip -j route': (ROUTE_JSON, None)}))
    try:
        state = nc.status(probe=False)
    finally:
        restore()
    check('the missing manager is named, not hidden', 'not stubbed' in state['manager_unavailable'])
    check('addresses still come from ip', state['addresses']['ipv4'][0]['address'] == '192.168.100.5/24')
    check('the gateway still comes from ip', state['gateway'] == '192.168.100.1')


def test_wifi_list_marks_saved_by_ssid_not_by_profile_name():
    """The profile here is called "Home wifi" and joins the SSID "Juninho-2.4G"."""
    stubs = {'device wifi list --rescan no': ('\n'.join(WIFI_ROWS), None),
             'NAME,UUID,TYPE,DEVICE,AUTOCONNECT': (CONNECTIONS, None),
             '802-11-wireless.ssid': ('802-11-wireless.ssid:Juninho-2.4G', None)}
    restore = patched(_run=Fake(stubs))
    try:
        out = nc.wifi_list()
    finally:
        restore()
    rows = {r['ssid']: r for r in out['networks']}
    check('the saved network is recognised although its profile has another name',
          rows['Juninho-2.4G']['saved'] is True)
    check('an unsaved network is not claimed as saved', rows['Telekom-424362']['saved'] is False)
    check('a hidden network is reported as hidden, not dropped',
          None in rows and rows[None]['hidden'] is True and rows[None]['bssid'] == 'A4:CF:D2:7A:2C:9D')
    check('an unsecured network is labelled open', rows[None]['security'] == 'open')
    check('the loopback profile is not offered as a wifi profile',
          all(p['type'] != 'loopback' for p in out['saved_profiles']))
    check('no rescan was forced', 'no rescan' in out['scan'])
    check('the read is described as a cached scan', 'cached' in out['scan'])


def test_wifi_list_collapses_one_network_on_two_bands_keeping_the_strongest():
    stubs = {'device wifi list --rescan no': ('\n'.join(WIFI_ROWS), None),
             'NAME,UUID,TYPE,DEVICE,AUTOCONNECT': (CONNECTIONS, None),
             '802-11-wireless.ssid': ('802-11-wireless.ssid:Juninho-2.4G', None)}
    restore = patched(_run=Fake(stubs))
    try:
        out = nc.wifi_list()
    finally:
        restore()
    same = [r for r in out['networks'] if r['ssid'] == 'Juninho-2.4G']
    check('one row per SSID', len(same) == 1)
    check('the stronger band wins', same[0]['signal'] == 88)
    check('and its own BSSID came with it', same[0]['bssid'] == '24:91:BB:8D:B1:19')
    check('strongest first', [r['signal'] for r in out['networks']]
          == sorted((r['signal'] for r in out['networks']), reverse=True))


def test_wifi_connect_refuses_an_unsaved_name_and_never_activates_anything():
    fake = Fake({'NAME,UUID,TYPE,DEVICE,AUTOCONNECT': (CONNECTIONS, None),
                 '802-11-wireless.ssid': ('802-11-wireless.ssid:Juninho-2.4G', None)})
    restore = patched(_run=fake)
    try:
        try:
            nc.wifi_connect('Telekom-424362')
            raised = None
        except nc.NetworkCapabilityError as exc:
            raised = exc
    finally:
        restore()
    check('an unsaved network is refused', raised is not None and raised.code == 'TARGET_NOT_FOUND')
    check('the refusal lists what IS saved', 'Juninho-2.4G' in str(raised))
    check('it says where a new network must be joined instead', 'GNOME' in str(raised))
    # The point of the test: nothing was activated, so nothing could drop.
    check('`nmcli connection up` was never run',
          not any('up' in argv for argv in fake.calls))


def test_wifi_connect_refuses_two_profiles_with_the_same_name():
    doubled = ('Guest:11111111-1111-1111-1111-111111111111:802-11-wireless::yes\n'
               'Guest:22222222-2222-2222-2222-222222222222:802-11-wireless::yes')
    fake = Fake({'NAME,UUID,TYPE,DEVICE,AUTOCONNECT': (doubled, None),
                 '802-11-wireless.ssid': ('802-11-wireless.ssid:Guest', None)})
    restore = patched(_run=fake)
    try:
        try:
            nc.wifi_connect('Guest')
            raised = None
        except nc.NetworkCapabilityError as exc:
            raised = exc
    finally:
        restore()
    check('an ambiguous name is refused rather than guessed',
          raised is not None and raised.code == 'AMBIGUOUS')
    check('both candidates are named', str(raised).count('Guest') >= 2)
    check('nothing was activated', not any('up' in argv for argv in fake.calls))


def test_wifi_connect_activates_by_uuid_and_verifies_by_re_reading():
    fake = Fake({'connection up': ('Connection successfully activated', None),
                 'GENERAL.STATE': ('GENERAL.STATE:activated\nGENERAL.DEVICES:wlan0', None),
                 'connection.id': ('connection.id:Home wifi\n'
                                   'connection.uuid:b340b690-c7c8-4894-9e7a-41a829ff4e22\n'
                                   'connection.type:802-11-wireless', None),
                 'NAME,UUID,TYPE,DEVICE,AUTOCONNECT': (CONNECTIONS, None),
                 '802-11-wireless.ssid': ('802-11-wireless.ssid:Juninho-2.4G', None)})
    restore = patched(_run=fake)
    try:
        out = nc.wifi_connect('Juninho-2.4G', wait=1)
    finally:
        restore()
    up = next(argv for argv in fake.calls if 'up' in argv)
    check('the SSID resolved to its saved profile', out['profile']['name'] == 'Home wifi')
    check('activation is by UUID, not by a name two profiles could share',
          'uuid' in up and 'b340b690-c7c8-4894-9e7a-41a829ff4e22' in up)
    check('accepted is recorded separately from verified',
          out['accepted'] is True and 'verified' in out)
    check('verified comes from the re-read state, not the exit code',
          out['verified'] is True and out['now'] == 'activated')


def test_a_failed_activation_is_not_reported_as_verified():
    fake = Fake({'connection up': (None, 'Error: Connection activation failed: Secrets were required'),
                 'connection.id': ('connection.id:Home wifi\n'
                                   'connection.uuid:b340b690-c7c8-4894-9e7a-41a829ff4e22\n'
                                   'connection.type:802-11-wireless', None),
                 'NAME,UUID,TYPE,DEVICE,AUTOCONNECT': (CONNECTIONS, None),
                 '802-11-wireless.ssid': ('802-11-wireless.ssid:Juninho-2.4G', None)})
    restore = patched(_run=fake)
    try:
        out = nc.wifi_connect('Juninho-2.4G', wait=1)
    finally:
        restore()
    check('a refused activation is not accepted', out['accepted'] is False)
    check('and it is not verified', out['verified'] is False)
    check("nmcli's reason is carried through", 'Secrets' in out['accept_detail'])
    check('the state re-read still ran', out['now'] == 'deactivated')


def test_no_capability_can_be_handed_a_wifi_password():
    check('the input has exactly one field', set(nc.ConnectionInput.model_fields) == {'name'})
    for extra in ('password', 'psk', 'wifi-sec.psk', 'secret'):
        try:
            nc.ConnectionInput.model_validate({'name': 'X', extra: 'hunter2'})
            accepted = True
        except Exception:
            accepted = False
        check(f'{extra!r} is refused by the schema', accepted is False)
    source = Path(nc.__file__).read_text(encoding='utf-8')
    check('the module never builds a `nmcli device wifi connect` argv',
          "'connect'" not in source and '"connect"' not in source)
    check('and never passes a nmcli password option',
          'wifi-sec' not in source and '--ask' not in source)


def test_brightness_names_every_mechanism_and_why_it_is_unavailable():
    out = nc.brightness(None)
    check('a read always answers', out['ok'] is True)
    check('controllable is a plain boolean', isinstance(out['controllable'], bool))
    check('all four mechanisms are reported', len(out['sources']) == 4)
    check('every unavailable mechanism carries a reason',
          all(s.get('unavailable') for s in out['sources'] if not s['available']))
    check('a reason is a sentence, not a flag',
          all(len(s['unavailable']) > 12 for s in out['sources'] if not s['available']))
    if out['controllable']:
        check('a controllable screen reports a percentage',
              isinstance(out['brightness'], int) and 0 <= out['brightness'] <= 100)
    else:
        check('an uncontrollable screen reports no number rather than 0',
              out['brightness'] is None)
        check('and says so in one sentence', 'no screen brightness control' in out['detail'])


def test_setting_brightness_refuses_instead_of_pretending():
    """Never a no-op: with nothing to write, this raises and names what it probed."""
    no_sources = [dict(s, available=False, unavailable=s.get('unavailable') or 'absent')
                  for s in nc.brightness_sources()]
    restore = patched(brightness_sources=lambda: no_sources)
    try:
        try:
            nc.brightness(50)
            raised = None
        except nc.NetworkCapabilityError as exc:
            raised = exc
    finally:
        restore()
    check('it raises rather than returning a cheerful ok',
          raised is not None and raised.code == 'CAPABILITY_UNAVAILABLE')
    check('the refusal explains the hardware', 'DDC/CI' in str(raised))
    check('and it is not retryable', raised.retryable is False)


def test_brightness_floor_is_one_so_the_screen_stays_visible():
    check('zero is refused by the schema', _rejects(nc.BrightnessInput, {'level': 0}))
    check('over a hundred is refused', _rejects(nc.BrightnessInput, {'level': 101}))
    check('a string level is refused under strict mode', _rejects(nc.BrightnessInput, {'level': '50'}))
    check('an unknown field is refused', _rejects(nc.BrightnessInput, {'level': 50, 'device': 'x'}))
    check('a valid level passes', nc.BrightnessInput.model_validate({'level': 1}).level == 1)


def _rejects(model, payload):
    try:
        model.model_validate(payload)
        return False
    except Exception:
        return True


def test_registration_gates_only_the_mutating_capabilities():
    class Collector:
        def __init__(self):
            self.items = {}

        def register(self, cap):
            assert cap.name not in self.items, 'duplicate ' + cap.name
            self.items[cap.name] = cap

    registry = Collector()
    nc.register(registry)
    check('all five capabilities registered',
          set(registry.items) == {'network.status', 'network.wifi_list', 'network.wifi_connect',
                                  'display.brightness', 'display.set_brightness'})
    for name in ('network.status', 'network.wifi_list', 'display.brightness'):
        cap = registry.items[name]
        # policy() gates every effect that is not 'read' behind operator.enabled;
        # asking how bright the screen is must not need the operator switched on.
        check(f'{name} is a read that needs no approval',
              cap.effect == 'read' and cap.requires_approval is False)
    for name in ('network.wifi_connect', 'display.set_brightness'):
        cap = registry.items[name]
        check(f'{name} needs approval and is not a read',
              cap.requires_approval is True and cap.effect != 'read')
    check('joining a network is marked high risk',
          registry.items['network.wifi_connect'].risk_level == 'high')
    check('every capability describes a JSON schema',
          all(c.describe()['input_schema'] for c in registry.items.values()))
    check('the wifi_connect description says ARIES takes no password',
          'password' in registry.items['network.wifi_connect'].description)


async def test_capability_executors_and_verifiers_agree_on_shape():
    restore = patched(_run=Fake(NETWORK_STUBS),
                      _tcp=lambda targets, timeout=2.0: (True, [{'target': '1.1.1.1:443', 'reached': True}]),
                      _dns=lambda name='example.com', timeout=3.0: (True, {'resolved': True}))
    try:
        result = await nc.observe_status({}, {})
        verdict = await nc.verify_status({}, result, {})
    finally:
        restore()
    check('the verifier re-probed and agreed', verdict['met'] is True)
    check('the evidence is typed', verdict['type'] == 'network_state')
    check('the evidence is a fresh observation, not the executor result',
          verdict['data']['observed_at'] != result['observed_at'])
    read = await nc.read_brightness({}, {})
    verdict = await nc.verify_read_brightness({}, read, {})
    check('a brightness read verifies as a display observation',
          verdict['met'] is True and verdict['type'] == 'display_state')


def test_this_machine_observed_read_only():
    """Live, read-only. Records what is true here; asserts only shape."""
    import shutil
    if not shutil.which('nmcli'):
        check('skipped — nmcli is not installed on this machine', True)
        return
    state = nc.status()
    print(f'      link_up={state["link_up"]} internet_reachable={state["internet_reachable"]} '
          f'dns_resolves={state["dns_resolves"]} nm_connectivity={state["nm_connectivity"]}')
    check('the four signals are each answered', all(
        state[k] is not None for k in ('link_up', 'internet_reachable', 'dns_resolves')))
    check('every TCP attempt records how long it took',
          all('ms' in a for a in state['probes']['tcp']))
    if state['primary'] and state['primary']['type'] == 'wifi':
        check('a wifi connection reports where its SSID came from',
              state['primary']['ssid_source'] is not None)
    else:
        check('skipped — the primary connection is not wifi', True)
    scan = nc.wifi_list()
    print(f'      {scan["count"]} networks visible, '
          f'{sum(1 for r in scan["networks"] if r["saved"])} saved')
    check('every scanned network has a reassembled BSSID',
          all(r['bssid'].count(':') == 5 for r in scan['networks'] if r['bssid']))
    check('no SSID appears twice', len({r['ssid'] for r in scan['networks'] if r['ssid']})
          == len([r for r in scan['networks'] if r['ssid']]))
    bright = nc.brightness(None)
    print('      brightness: ' + (f'{bright["brightness"]}%' if bright['controllable']
                                  else 'no mechanism available'))
    check('the brightness answer is either a number or a stated reason',
          bright['brightness'] is not None or bool(bright['detail']))


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
