"""Capture a real saved reading response in its own desktop window."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gtk,Gio,GLib
from aries_ui.app import ControlCentre
app=ControlCentre();app.set_flags(app.get_flags()|Gio.ApplicationFlags.NON_UNIQUE)
goal=sys.argv[1]
def capture():
    window=app.responses['goal:'+goal]
    snapshot=Gtk.Snapshot()
    Gtk.WidgetPaintable.new(window).snapshot(snapshot,window.get_width(),window.get_height())
    texture=window.get_renderer().render_texture(snapshot.to_node(),None)
    texture.save_to_png(str(Path(__file__).parent/'screens'/'reading.png'))
    print('captured independent reading window')
    app.quit();return False
GLib.timeout_add_seconds(5,capture)
app.run([sys.argv[0],'--goal',goal])
