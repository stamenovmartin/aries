"""Settings stay editable during optional probes; stale replies cannot repaint them."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aries_ui.client import Client
from aries_ui.pages.settings import SettingsPage
from gi.repository import Gtk, Adw, GLib

Gtk.init()
Adw.init()
release = threading.Event()
first_started = threading.Event()
calls = {'power': 0}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path.endswith('/settings'):
            value = {'settings': [{'key': 'power.test', 'section': 'power', 'title': 'Test setting',
                                  'description': '', 'type': 'str', 'value': 'saved'}]}
        else:
            calls['power'] += 1
            number = calls['power']
            if number == 1:
                first_started.set()
                release.wait(5)
            value = {'background_mode': number == 1}
        raw = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except BrokenPipeError:
            pass


def until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError('Timed out waiting for GTK callback')


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    client = Client(base=f'http://127.0.0.1:{server.server_port}')
    page = SettingsPage(SimpleNamespace(client=client))
    page.reload()
    until(lambda: page._loaded_once and first_started.is_set())
    assert page._visible_settings[0]['key'] == 'power.test'
    assert page._power_data is None and not release.is_set()
    print('PASS editable controls appear before slow optional probe completes')
    original_form = page._slot.get_first_child()
    page.reload(quiet=True)
    until(lambda: page._power_data is not None)
    assert page._power_data['background_mode'] is False
    fresh_form = page._slot.get_first_child()
    assert fresh_form is not original_form
    release.set()
    # Drain long enough for the superseded worker's response to be delivered.
    deadline = time.monotonic() + .2
    until(lambda: time.monotonic() >= deadline)
    assert page._power_data['background_mode'] is False
    assert page._slot.get_first_child() is fresh_form
    print('PASS stale optional probe cannot replace fresh state or editable form')
    calls['power'] = 0
    release.clear()
    first_started.clear()
    limited = SettingsPage(SimpleNamespace(client=Client(base=client.base, timeout=.15)))
    limited.reload()
    until(lambda: limited._loaded_once and first_started.is_set())
    editable_form = limited._slot.get_first_child()
    until(lambda: limited._power_data is not None)
    assert limited._power_data.get('unavailable')
    assert limited._slot.get_first_child() is editable_form
    assert limited._visible_settings
    print('PASS optional probe timeout leaves the form editable and reports unavailability')
finally:
    release.set()
    server.shutdown()
    server.server_close()
