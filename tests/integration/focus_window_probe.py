"""Run only inside test-shell.sh's isolated compositor and session bus."""
import ast
import json
import subprocess
import sys
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib

app = Gtk.Application(application_id='org.gnome.Nautilus')
failed = False
window = None
target = None

def call(method, *args):
    raw = subprocess.check_output(['gdbus', 'call', '--session', '--dest', 'org.aries.Shell',
        '--object-path', '/org/aries/Shell', '--method', 'org.aries.Shell.'+method, *args], timeout=3, text=True)
    return json.loads(ast.literal_eval(raw)[0])

def check(value, message):
    if not value:
        raise AssertionError(message)

def guarded(fn):
    def run():
        global failed
        try:
            fn()
        except Exception as exc:
            failed = True
            print('focus-probe: FAIL', str(exc), flush=True)
            app.quit()
        return False
    return run

@guarded
def inspect():
    global target
    target = next(w for w in call('Windows')['windows'] if w['title']=='ARIES isolated focus probe')
    check(target['app_id']=='org.gnome.Nautilus.desktop', 'Expected installed app identity')
    check(not call('FocusWindow', target['id'], 'wrong.desktop')['accepted'], 'Wrong identity must be refused')
    window.minimize()
    GLib.timeout_add_seconds(1, restore)

@guarded
def restore():
    current = next(w for w in call('Windows')['windows'] if w['id']==target['id'])
    check(current['minimised'], 'Probe must actually be minimised')
    check(call('FocusWindow', target['id'], target['app_id'])['accepted'], 'Restore request rejected')
    GLib.timeout_add_seconds(1, verify)

@guarded
def verify():
    windows = call('Windows')['windows']
    matching = [w for w in windows if w['title']=='ARIES isolated focus probe']
    check(len(matching)==1 and matching[0]['id']==target['id'], 'Must reuse same single window')
    check(matching[0]['focused'] and not matching[0]['minimised'], 'Must be visibly focused')
    check(not call('FocusWindow', '999999999', target['app_id'])['accepted'], 'Stale ID must be refused')
    print('focus-probe: PASS', flush=True)
    app.quit()

def activate(app):
    global window
    window = Gtk.ApplicationWindow(application=app, title='ARIES isolated focus probe')
    window.set_default_size(400, 300)
    window.present()
    GLib.timeout_add_seconds(2, inspect)

app.connect('activate', activate)
app.run([sys.argv[0]])
sys.exit(1 if failed else 0)
