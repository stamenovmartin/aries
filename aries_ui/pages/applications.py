"""Installed apps and reviewed package installation, each request in its own tab."""
from gi.repository import Gtk
from aries_ui import widgets, hud
from aries_ui.page import Page

DESCRIPTIONS = {'vscode':'Visual Studio Code by Microsoft', 'pycharm':'Python development environment by JetBrains',
                'firefox':'Web browser', 'vlc':'Video and audio player', 'gimp':'Image editor'}

class ApplicationsPage(Page):
    title = 'Applications'
    icon = 'system-software-install-symbolic'
    subtitle = 'Open installed apps · review new installations · follow each task'

    def fetch(self, client):
        return client.get('/api/aries/workspace/applications')

    def _request(self, kind, app):
        self.act(lambda c: c.post('/api/aries/workspace', {'capability':kind,'args':{'app':app}}),
                 on_ok=lambda r:self.app.open_goal(r['id'], temporary=True), then_reload=False)

    def render(self, data):
        box = widgets.page_box()
        box.append(hud.hero('ARIES / APPLICATIONS', 'Tools for your next task',
                            'Choose an application. Installation opens a dedicated task tab with its exact package, review and result.', self.icon))
        grid = hud.grid(2)
        for app in data['catalogue']:
            if app['id']=='pycharm':
                continue
            panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            panel.add_css_class('hud-panel')
            name = 'VS Code' if app['id']=='vscode' else 'PyCharm' if app['id']=='pycharm' else app['id'].upper() if app['id'] in {'vlc','gimp'} else 'Firefox'
            panel.append(hud.label(name, 'hud-story-title'))
            panel.append(hud.label(DESCRIPTIONS.get(app['id'],''), 'hud-muted'))
            panel.append(hud.label('Desktop launcher found' if app['desktop_available'] else 'No desktop launcher found', 'hud-kicker'))
            controls = Gtk.Box(spacing=8)
            if app['desktop_available']:
                open_button = Gtk.Button(label='Open')
                open_button.connect('clicked', lambda _, a=app['id']:self._request('open_app',a))
                controls.append(open_button)
            install = Gtk.Button(label='Check installation' if app['desktop_available'] else 'Install')
            install.add_css_class('suggested-action')
            install.connect('clicked', lambda _, a=app['id']:self._request('install_app',a))
            controls.append(install)
            panel.append(controls)
            grid.append(panel)
        box.append(grid)
        box.append(hud.label('Supported installers: these four Snap packages. A new installation requires the exact-target review and may show the system authentication dialog.', 'hud-muted'))
        group = widgets.section('On your desktop', 'Launchers found on this machine. Opening one creates its own tracked task.')
        for item in data['installed']:
            row = widgets.row(item['title'], item['text'], activatable=True)
            row.connect('activated', lambda _, a=item['text']:self._request('open_app',a))
            group.add(row)
        box.append(group)
        return widgets.scrolled(box)
