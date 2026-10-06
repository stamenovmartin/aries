"""File command surface with real task history and explicit locations."""
from gi.repository import Gtk, Adw
from aries_ui import hud, widgets
from aries_ui.page import Page

class FilesPage(Page):
    title = 'Files'
    icon = 'folder-symbolic'
    subtitle = 'Locations · search · file operations'

    def fetch(self, client):
        return client.get('/api/aries/workspace')

    def _submit(self, body):
        def done(result):
            self.app.open_goal(result['id'], temporary=True)
        self.act(lambda c: c.post('/api/aries/workspace', body), on_ok=done, then_reload=False)

    def render(self, data):
        box = widgets.page_box()
        box.append(hud.hero('ARIES / FILE EXPLORER', 'Your working space',
                            'Browse a location, find a file, or follow the changes ARIES has made.', self.icon))
        places = hud.grid(3)
        for name in ('Documents', 'Downloads', 'Desktop'):
            places.append(hud.portal(name, 'Inspect this folder', 'folder-symbolic',
                          lambda n=name: self._submit({'capability':'list_folder','args':{'path':'~/'+n}})))
        box.append(places)
        group = widgets.section('Find something')
        entry = Adw.EntryRow(title='File name')
        entry.set_show_apply_button(True)
        def search(e, *_):
            if e.get_text().strip():
                self._submit({'capability':'find_files','args':{'query':e.get_text().strip()}})
        entry.connect('apply', search)
        entry.connect('entry-activated', search)
        group.add(entry)
        box.append(group)
        history = widgets.section('File activity', 'Moves and Trash keep their target review and verification.')
        file_kinds = {'open_path','find_files','list_folder','read_file','create_folder','create_file','move_file','trash_file'}
        recent = [g for g in data['goals'] if any(s.get('capability') in file_kinds for s in g.get('steps',[]))]
        for goal in recent[:15]:
            row = widgets.row(goal['request'], goal['state'].title(), activatable=True)
            def select(_, gid=goal['id']):
                self.app.open_goal(gid)
            row.connect('activated', select)
            history.add(row)
        if not recent:
            history.add(widgets.row('No file tasks yet', 'Choose a location above to start.'))
        box.append(history)
        return widgets.scrolled(box)
