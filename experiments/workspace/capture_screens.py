"""Capture the actual GTK screens against the running API, without mock data."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import gi
gi.require_version('Gtk','4.0')
gi.require_version('Adw','1')
gi.require_version('Graphene','1.0')
from gi.repository import Gtk, Gio, GLib
from aries_ui.app import ControlCentre
app = ControlCentre()
app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
sections = iter(['monitor','news','system','files','applications','dashboard'])
out = Path(__file__).parent / 'screens'
out.mkdir(exist_ok=True)
current = None

def capture():
    window = app.responses.get("screen:"+current) or app.window
    paintable = Gtk.WidgetPaintable.new(window)
    snapshot = Gtk.Snapshot()
    paintable.snapshot(snapshot, window.get_width(), window.get_height())
    node = snapshot.to_node()
    texture = window.get_renderer().render_texture(node, None)
    texture.save_to_png(str(out/(current+'.png')))
    print('captured',current,flush=True)
    advance()
    return GLib.SOURCE_REMOVE

def advance():
    global current
    current = next(sections,None)
    if current is None:
        app.quit()
    else:
        app.go(current)
        GLib.timeout_add_seconds(4,capture)

def start():
    advance()
    return GLib.SOURCE_REMOVE
GLib.timeout_add_seconds(2,start)
app.run([sys.argv[0]])
