"""Exercise real GTK window state transitions without touching other apps."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import gi
gi.require_version('Gtk','4.0');gi.require_version('Adw','1');gi.require_version('Graphene','1.0')
from gi.repository import Gtk,Gio,GLib,Gdk
from aries_ui.app import ControlCentre
app=ControlCentre();app.set_flags(app.get_flags()|Gio.ApplicationFlags.NON_UNIQUE)
records=[]
def check(name,value):
    records.append({'check':name,'passed':bool(value)})
    print('PASS' if value else 'FAIL',name,flush=True)
def snapshot(w,name):
    paint=Gtk.WidgetPaintable.new(w);snap=Gtk.Snapshot();paint.snapshot(snap,w.get_width(),w.get_height())
    w.get_renderer().render_texture(snap.to_node(),None).save_to_png(str(Path(__file__).parent/'screens'/name))
def later(fn):GLib.timeout_add_seconds(2,lambda:(fn(),GLib.SOURCE_REMOVE)[1])
def start():
    app.go('learning');w=app.responses['screen:learning'];w.set_title('ARIES · Window controls acceptance');w.set_default_size(640,600)
    later(lambda:narrow(w))
def narrow(w):
    check('response resizes to compact width',w.get_width()<=680)
    snapshot(w,'top-navigation-compact.png');w.maximize();later(lambda:maximized(w))
def maximized(w):
    check('response maximizes',w.is_maximized())
    snapshot(w,'top-navigation-maximized.png');w.unmaximize();w.fullscreen();later(lambda:full(w))
def full(w):
    check('response fills screen',w.is_fullscreen())
    w.unfullscreen();later(lambda:begin_minimize(w))
def begin_minimize(w):
    w.minimize();later(lambda:minimized(w))
def minimized(w):
    bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
    reply=bus.call_sync('org.aries.Shell','/org/aries/Shell','org.aries.Shell','Windows',None,None,Gio.DBusCallFlags.NONE,3000,None)
    windows=json.loads(reply.unpack()[0])['windows']
    check('response minimizes',any(x['title']=='ARIES · Window controls acceptance' and x['minimised'] for x in windows))
    w.present();later(lambda:restored(w))
def restored(w):
    check('response restores',not bool(w.get_surface().get_state() & Gdk.ToplevelState.MINIMIZED))
    app.window.maximize();later(main_check)
def main_check():
    check('main control centre maximizes',app.window.is_maximized())
    Path(__file__).with_suffix('.json').write_text(json.dumps(records,indent=2))
    app.quit()
GLib.timeout_add_seconds(2,lambda:(start(),False)[1])
app.run([sys.argv[0]])
sys.exit(0 if records and all(r['passed'] for r in records) else 1)
