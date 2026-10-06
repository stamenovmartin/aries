"""Inspect the installed review surface without posting a fabricated human vote."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import gi
gi.require_version('Gtk','4.0');gi.require_version('Adw','1');gi.require_version('Graphene','1.0')
from gi.repository import Gtk,Gio,GLib
from aries_ui.app import ControlCentre
from experiments.workspace.live_evaluate import api
app=ControlCentre();app.set_flags(app.get_flags()|Gio.ApplicationFlags.NON_UNIQUE)
goal=next(g for g in api('GET','/workspace')['goals'] if g['state']=='done')
def begin():
    app.open_goal(goal['id'])
    GLib.timeout_add_seconds(3,focus)
    return False
def focus():
    window=app.responses['goal:'+goal['id']]
    window.page._review_button.emit('clicked')
    GLib.timeout_add_seconds(1,capture)
    return False
def capture():
    window=app.responses['goal:'+goal['id']]
    paint=Gtk.WidgetPaintable.new(window);snapshot=Gtk.Snapshot()
    paint.snapshot(snapshot,window.get_width(),window.get_height())
    path=Path(__file__).parent/'screens/task-review.png'
    window.get_renderer().render_texture(snapshot.to_node(),None).save_to_png(str(path))
    print('Review entry exists:',bool(window.page._review_entry),'Pinned:',window.keep.get_active(),flush=True)
    app.quit();return False
GLib.timeout_add_seconds(1,begin)
app.run([sys.argv[0]])
