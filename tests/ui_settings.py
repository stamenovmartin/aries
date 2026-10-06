"""Exercise native settings filtering and editing without a network or windows."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw
Gtk.init_check()
Adw.init()
from aries_ui.pages.settings import SettingsPage, control_for, matching_settings, changed_from_default

failures = []
def check(label, ok):
    print(('PASS  ' if ok else 'FAIL  ') + label)
    if not ok:
        failures.append(label)


def row(key, **extra):
    return {'key': key, 'section': key.split('.')[0], 'title': key, 'description': '',
            'type': 'float', 'control': 'number', 'value': .7, 'minimum': 0,
            'maximum': 2, 'source': 'default', **extra}


writes = []
client = SimpleNamespace(put=lambda path, body: writes.append((path, body)))
page = SettingsPage(SimpleNamespace(client=client))
page.act = lambda work, **kwargs: work(client)
settings = [row('ai.temperature', title='Temperature', advanced=True),
            row('future_feature.strength', title='New capability', source='user'),
            row('general.enabled', type='bool', control='toggle', value=True),
            row('power.restore_idle_delay', type='int', value=10)]
data = {'settings': settings}
page.render(data)
check('initial view opens one section instead of constructing every control',
      {s['key'] for s in page._visible_settings} == {'general.enabled'})
page._settings_selector.set_selected(0)
check('rendering creates no settings writes', not writes)
check('new sections appear automatically and internal restore state stays hidden',
      {s['key'] for s in page._visible_settings} ==
      {'ai.temperature', 'future_feature.strength', 'general.enabled'})
page._settings_search.set_text('TEMPERATURE')
page._settings_search.emit('search-changed')
check('search finds advanced model parameters case-insensitively',
      [s['key'] for s in page._visible_settings] == ['ai.temperature'])
page.render(data)
check('refresh preserves the current search',
      page._settings_search.get_text() == 'TEMPERATURE' and len(page._visible_settings) == 1)
page._settings_search.set_text('')
page._settings_search.emit('search-changed')
page._settings_changed_button.set_active(True)
check('changed-only shows explicit overrides',
      [s['key'] for s in page._visible_settings] == ['future_feature.strength'])
page._settings_changed_button.set_active(False)
page._settings_selector.set_selected(1)
check('section selector narrows to AI without a sidebar',
      [s['key'] for s in page._visible_settings] == ['ai.temperature'])
page._settings_search.set_text('nothing matches')
page._settings_search.emit('search-changed')
check('an empty search result remains renderable', not page._visible_settings)
check('filtering never writes settings', not writes)
spin = control_for(page, settings[0])
spin.set_value(1.2)
check('editing a model parameter uses the existing typed settings endpoint',
      writes == [('/api/aries/settings/ai.temperature', {'value': 1.2})])
check('schema bounds remain enforced by the native control',
      spin.get_adjustment().get_lower() == 0 and spin.get_adjustment().get_upper() == 2)
without_source = [{'key': 'ai.temperature', 'section': 'ai', 'default': .7, 'value': .7},
                  {'key': 'ai.top_p', 'section': 'ai', 'default': 1., 'value': .9}]
check('the real list API needs no source field to identify changed values',
      [s['key'] for s in matching_settings(without_source, changed_only=True)] == ['ai.top_p'])
check('missing provenance never implies all settings were changed',
      not changed_from_default(without_source[0]))
print('ALL PASSED' if not failures else 'FAILURES')
sys.exit(bool(failures))
