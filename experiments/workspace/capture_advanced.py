"""Capture new native response surfaces against real saved API results."""
import sys
import json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import gi
gi.require_version('Gtk','4.0');gi.require_version('Adw','1');gi.require_version('Graphene','1.0')
from gi.repository import Gtk,Gio,GLib
from aries_ui.app import ControlCentre
from experiments.workspace.live_evaluate import api

out=Path(__file__).parent/'screens';out.mkdir(exist_ok=True)
baseline=json.loads((Path(__file__).parent/'acceptance-20260914-232236.json').read_text())
code=next(g['id'] for g in baseline['goals'] if g['capability']=='build_python')
goals=api('GET','/workspace')['goals']
agent=next((g['id'] for g in goals if g.get('agent') and g['state']=='done'),None)
targets=iter([('advanced-monitor',None),('advanced-development',code)]+([('advanced-browser',agent)] if agent else []))
app=ControlCentre();app.set_flags(app.get_flags()|Gio.ApplicationFlags.NON_UNIQUE)
current=None

def capture():
    name,goal=current
    window=app.responses.get('goal:'+goal) if goal else app.responses.get('screen:monitor')
    paintable=Gtk.WidgetPaintable.new(window);snapshot=Gtk.Snapshot()
    paintable.snapshot(snapshot,window.get_width(),window.get_height())
    node=snapshot.to_node();texture=window.get_renderer().render_texture(node,None)
    texture.save_to_png(str(out/(name+'.png')))
    print('captured',name,flush=True)
    advance();return GLib.SOURCE_REMOVE

def advance():
    global current
    current=next(targets,None)
    if current is None:
        app.quit();return GLib.SOURCE_REMOVE
    _,goal=current
    if goal:app.open_goal(goal)
    else:app.go('monitor')
    GLib.timeout_add_seconds(4,capture)
    return GLib.SOURCE_REMOVE

GLib.timeout_add_seconds(2,advance)
app.run([sys.argv[0]])
