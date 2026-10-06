"""Live execution observatory, using persisted outcomes rather than model claims."""
from datetime import datetime
from collections import Counter
from gi.repository import Gtk
from aries_ui import hud, widgets


def measurement(goals):
    counts = Counter(g['state'] for g in goals)
    terminal = [g for g in goals if g['state'] in {'done', 'answered', 'partial', 'failed', 'interrupted'}]
    durations = []
    for goal in terminal:
        try:
            duration = (datetime.fromisoformat(goal['updated_at']) - datetime.fromisoformat(goal['created_at'])).total_seconds()
            if duration >= 0:
                durations.append(duration)
        except (KeyError, ValueError, TypeError):
            pass
    return counts, terminal, durations


class MonitorPage(hud.LivePage):
    title = 'Monitoring'
    icon = 'utilities-system-monitor-symbolic'
    subtitle = 'Live work · background execution · observed outcomes'

    def fetch(self, client):
        return {'workspace': client.get('/api/aries/workspace'),
                'automations': client.get('/api/aries/automations')}

    def render(self, data):
        box = widgets.page_box()
        goals = data['workspace']['goals']
        counts, terminal, durations = measurement(goals)
        box.append(hud.hero('ARIES / OPERATIONS', 'Mission control',
                            'Updates every 5 seconds while open. Every status below comes from recorded execution.', self.icon))
        stats = hud.grid(4)
        stats.append(hud.metric('In progress', counts['running'] + counts['queued'], 'Running + queued'))
        stats.append(hud.metric('Needs your decision', counts['proposed'], 'Exact changes awaiting review'))
        stats.append(hud.metric('Verified completion', f"{counts['done']}/{len(terminal)}", 'Recent completed attempts; partial and interrupted included'))
        stats.append(hud.metric('Mean elapsed', f'{sum(durations)/len(durations):.1f}s' if durations else '—', 'Queue + execution; not model-only latency'))
        box.append(stats)
        evaluate = Gtk.Button(label='Evaluate recorded task outcomes')
        evaluate.connect('clicked', lambda *_: self.act(lambda c:c.post('/api/aries/workspace', {'capability':'evaluation','args':{}}), on_ok=lambda r:self.app.open_goal(r['id'], temporary=True)))
        box.append(evaluate)
        scheduler = data['workspace'].get('scheduler', {})
        if scheduler:
            box.append(hud.metric('Concurrent goals', f"{scheduler.get('running', 0)}/{scheduler.get('capacity', 3)}",
                                  'Independent goals can progress together. Shared desktop, model and file resources are coordinated.'))

        runtime = data['workspace'].get('runtime', {})
        if runtime:
            windows = widgets.section('Browser windows now', 'Fresh owned-session state; saved task evidence is historical.')
            if not runtime.get('available'):
                windows.add(widgets.row('State unavailable', runtime.get('reason', '')))
            elif not runtime.get('browsers'):
                windows.add(widgets.row('No owned browser sessions open', ''))
            for window in runtime.get('browsers', []):
                windows.add(widgets.row(window.get('url') or window['session'], 'Open' if window['open'] else 'Closed'))
            box.append(windows)
            desktop = runtime.get('desktop', {})
            app_windows = widgets.section('Desktop windows now', 'Observed by the desktop; unavailable is not the same as closed.')
            if not desktop.get('available'):
                app_windows.add(widgets.row('Observation unavailable', desktop.get('reason', '')))
            elif not desktop.get('windows'):
                app_windows.add(widgets.row('No application windows observed', ''))
            for w in desktop.get('windows', [])[:40]:
                app_windows.add(widgets.row(w.get('title') or w.get('app_id', 'Window'),
                    ('Focused' if w.get('focused') else 'Minimized' if w.get('minimised') else 'Open') + ' · ' + w.get('app_id', '')))
            box.append(app_windows)

        active = [g for g in goals if g['state'] in {'running','queued','proposed'}]
        if active:
            group = widgets.section('Live operations', 'Open any task to inspect steps, cancel or review its proposed change.')
            for goal in active:
                group.add(self._goal(goal))
            box.append(group)
        else:
            box.append(hud.metric('Work queue', 'Standing by', 'No active user goals in the recent task window.'))

        background = data['automations']
        worker = background.get('worker', {})
        worker_state = 'Running' if worker.get('alive') and worker.get('state') == 'running' else worker.get('state', 'Unknown').title()
        box.append(hud.hero('BACKGROUND / DISPATCHER', worker_state, 'Scheduled automations are running in the background.' if worker.get('alive') else 'The dispatcher is not currently running.', 'system-run-symbolic'))
        grid = hud.grid(2)
        for automation in background.get('automations', []):
            last = automation.get('last_run') or {}
            health = automation.get('health') or {}
            rate = health.get('success_rate')
            panel = hud.metric(automation['name'], last.get('status', 'No run').title(),
                               ('Enabled' if automation.get('enabled') else 'Disabled') + ' · Last ' + widgets.when(last.get('started_at')),
                               fraction=float(rate) if rate is not None else None)
            panel.append(hud.label(last.get('summary') or automation.get('purpose',''), 'hud-muted'))
            if rate is not None:
                panel.append(hud.label(f'Historical run success: {float(rate):.0%}', 'hud-kicker'))
            grid.append(panel)
        box.append(grid)
        recent = widgets.section('Execution timeline', f'{len(goals)} recent goals. Failures are retained; cancelled and pending work is outside the completion denominator.')
        for goal in goals[:30]:
            recent.add(self._goal(goal))
        box.append(recent)
        box.append(hud.hero('EVALUATION / SCOPE', 'Measured, not assumed',
            'These are operational measurements, not a controlled model comparison. Fresh application installation, research superiority and autonomous self-improvement have not been established.', 'dialog-information-symbolic'))
        return widgets.scrolled(box)

    def _goal(self, goal):
        detail = goal['state'].upper() + ' · ' + widgets.when(goal['created_at'])
        if goal.get('progress') and goal['state']=='running':
            detail += ' · ' + goal['progress']
        row = widgets.row(goal['request'], detail, activatable=True)
        row.add_prefix(widgets.dot('ok' if goal['state'] in ('done','answered') else 'warning' if goal['state'] in {'partial','failed','interrupted'} else 'notice'))
        def open_goal(*_):
            self.app.open_goal(goal['id'])
        row.connect('activated', open_goal)
        return row
