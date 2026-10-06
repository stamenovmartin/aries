"""Installed-API acceptance for independent response windows and durable closing."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gio,GLib
from aries_ui.app import ControlCentre
from experiments.workspace.live_evaluate import api
app=ControlCentre();app.set_flags(app.get_flags()|Gio.ApplicationFlags.NON_UNIQUE)
goal=sys.argv[1]
state_before=next(g['state'] for g in api('GET','/workspace?goal_id='+goal)['goals'] if g['id']==goal)
result={}
def verify():
    try:
        assert app.window is None, 'Response opening created a control-centre container'
        app.go('news');app.go('applications')
        windows=list(app.responses.values())
        assert len(windows)==3 and len({id(w) for w in windows})==3
        assert all(w.get_application()==app for w in windows)
        app.responses['goal:'+goal].close()
        state_after=next(g['state'] for g in api('GET','/workspace?goal_id='+goal)['goals'] if g['id']==goal)
        assert state_after==state_before
        result.update(independent_windows=3,control_centre_required=False,closing_preserves_goal=True,passed=True)
    except Exception as exc:
        result.update(passed=False,error=str(exc))
    Path(__file__).with_name('response-results.json').write_text(json.dumps(result,indent=2)+'\n')
    print(result,flush=True);app.quit();return False
GLib.timeout_add_seconds(3,verify)
app.run([sys.argv[0],'--goal',goal])
sys.exit(0 if result.get('passed') else 1)
