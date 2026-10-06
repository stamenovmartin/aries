"""Windowed execution analytics with visible uncertainty and incomplete coverage."""
from gi.repository import Gtk
from aries_ui import hud, widgets
from aries_ui.page import Page


def rate_text(value):
    if not isinstance(value, dict) or value.get('rate') is None:
        return '—', value.get('reason', 'No measured outcomes') if isinstance(value, dict) else 'No measured outcomes'
    detail = f"{value.get('successes', 0)} of {value.get('trials', 0)}"
    if value.get('lower') is not None and value.get('upper') is not None:
        detail += f" · 95% interval {value['lower']:.0%}–{value['upper']:.0%}"
    return f"{value['rate']:.1%}", detail


def duration(value):
    if value is None:
        return '—'
    return f'{value / 1000:.1f}s' if value >= 1000 else f'{value:.0f}ms'


def latency_text(value):
    if not value or not value.get('n'):
        return (value or {}).get('reason', 'No timing samples')
    return (f"Median {duration(value.get('p50'))} · p90 {duration(value.get('p90'))}"
            f" · p99 {duration(value.get('p99'))} · {value['n']} samples")


class AnalyticsPage(Page):
    title = 'Analytics'
    icon = 'view-list-symbolic'
    subtitle = 'Task outcomes, model use and reliability'
    days = 7

    def fetch(self, client):
        return client.get('/api/aries/analytics', days=self.days, goal_scan=500)

    def header_suffix(self):
        periods = (1, 7, 30, 90)
        selector = Gtk.DropDown.new_from_strings(['Last day', 'Last 7 days', 'Last 30 days', 'Last 90 days'])
        selector.set_selected(periods.index(self.days))
        selector.set_tooltip_text('Analytics time window')
        def selected(widget, *_):
            self.days = periods[widget.get_selected()]
            self.reload()
        selector.connect('notify::selected', selected)
        return selector

    def render(self, data):
        box = widgets.page_box()
        metrics = data.get('metrics') or {}
        window = data.get('window') or {}
        days = window.get('window_days', self.days)
        box.append(hud.hero('ARIES / ANALYTICS', 'See how your system performs',
            f'Last {days} days. User tasks and background automation are measured separately.', self.icon))
        failures = data.get('failed_metrics') or []
        if failures:
            box.append(hud.metric('Some measurements are unavailable', len(failures),
                ', '.join(name.replace('_', ' ') for name in failures)))
        sampled = [name.replace('_', ' ') for name, metric in metrics.items() if metric.get('truncated')]
        if sampled:
            box.append(hud.metric('Limited history sample', window.get('goal_scan_cap', 500),
                'Recent-task limit reached for ' + ', '.join(sampled) + '. These are samples, not all-time totals.'))

        outcomes = metrics.get('task_outcomes') or {}
        elapsed = metrics.get('goal_elapsed') or {}
        usage = metrics.get('model_usage') or {}
        success, success_detail = rate_text(outcomes.get('success'))
        cards = hud.grid(4)
        cards.append(hud.metric('User tasks', outcomes.get('n', '—'), outcomes.get('reason') or 'Submitted in this time window'))
        cards.append(hud.metric('Completed', success, success_detail))
        cards.append(hud.metric('Median task elapsed', duration(elapsed.get('p50')),
                               'Estimated from timestamps; includes queue time'))
        cards.append(hud.metric('Model calls', usage.get('n', '—'), usage.get('reason') or 'Recorded local and cloud calls'))
        box.append(cards)

        states = widgets.section('Task outcomes',
            (outcomes.get('success') or {}).get('of', outcomes.get('reason', 'Recorded task states')))
        for state, count in (outcomes.get('states') or {}).items():
            row = widgets.row(state.replace('_', ' ').title())
            row.add_suffix(widgets.tag(str(count)))
            states.add(row)
        if not outcomes.get('states'):
            states.add(widgets.row('No task outcomes', outcomes.get('reason') or outcomes.get('detail', 'No data in this window')))
        box.append(states)

        verification = metrics.get('verification_honesty') or {}
        coverage, coverage_detail = rate_text(verification.get('coverage'))
        confidence = widgets.section('How much was independently checked',
            'An accepted action and a verified result are different outcomes.')
        confidence.add(widgets.row('Verification coverage · ' + coverage, coverage_detail))
        if verification.get('unverified') is not None:
            confidence.add(widgets.row('Successful-looking steps without independent proof',
                                       str(verification['unverified'])))
        contradictions = metrics.get('verification_contradictions') or {}
        if contradictions.get('contradiction'):
            value, detail = rate_text(contradictions['contradiction'])
            confidence.add(widgets.row('Contradictory verification · ' + value, detail))
        box.append(confidence)

        timings = metrics.get('latency') or {}
        group = widgets.section('Response times', 'Median is the typical recorded sample; p90 and p99 show slower responses.')
        for label, key in [('Background automation', 'automation_runs'), ('Execution steps', 'executor_steps'),
                           ('Choosing an action', 'routing')]:
            group.add(widgets.row(label, latency_text(timings.get(key))))
        for level, values in (timings.get('model_generation') or {}).items():
            group.add(widgets.row(level.title() + ' model generation', latency_text(values)))
        if elapsed.get('discarded_negative'):
            group.add(widgets.row('Clock corrections excluded',
                                   f"{elapsed['discarded_negative']} invalid negative durations were discarded."))
        box.append(group)

        models = widgets.section('Models & consumption', 'Calls and token counts come from recorded provider usage.')
        for model in usage.get('models') or []:
            title = f"{model.get('model', 'Unknown model')} · {model.get('level', 'unknown')}"
            subtitle = (f"{model.get('provider', 'Unknown provider')} · {model.get('n', 0)} calls"
                        f" · {model.get('input_tokens', 0):,} input / {model.get('output_tokens', 0):,} output tokens")
            ok, interval = rate_text(model.get('ok'))
            subtitle += f" · {model.get('task_type', 'all tasks')} · successful calls {ok} ({interval})"
            models.add(widgets.row(title, subtitle))
        cost = usage.get('cost_usd')
        models.add(widgets.row('Recorded cost', f'${cost:.4f}' if cost is not None
                               else usage.get('cost_reason', 'Pricing is not available; this is not a zero-cost claim.')))
        if usage.get('cost_covers'):
            models.add(widgets.row('Cost coverage', str(usage['cost_covers'])))
        box.append(models)

        automations = metrics.get('automation_health') or {}
        background = widgets.section('Background automation', 'These runs are separate from user-goal completion.')
        for item in automations.get('automations') or []:
            ok, interval = rate_text(item.get('ok'))
            background.add(widgets.row(item.get('automation_id', 'Unknown automation'),
                f"{item.get('runs', 0)} runs · successful attempts {ok} · {interval}"))
        if not automations.get('automations'):
            background.add(widgets.row('No recorded runs', automations.get('reason', 'No data in this window')))
        box.append(background)

        errors = metrics.get('failure_shapes') or {}
        error_group = widgets.section('Failures to investigate', 'Failure classes are retained instead of being folded into a success rate.')
        for item in (errors.get('typed_codes') or [])[:12]:
            error_group.add(widgets.row(item.get('code', 'Unknown failure'),
                f"{item.get('n', 0)} occurrences · " + ', '.join((item.get('capabilities') or {}).keys())))
        locking = metrics.get('locking_failures') or {}
        error_group.add(widgets.row('Database lock failures', str(locking.get('n', '—'))))
        if locking.get('hours_affected'):
            error_group.add(widgets.row('Hours affected', str(locking['hours_affected'])))
        box.append(error_group)

        capabilities = metrics.get('outcomes_by_capability') or {}
        caps = widgets.section('Capability outcomes', capabilities.get('note') or 'Recorded step outcomes, including missing verification.')
        for item in (capabilities.get('capabilities') or [])[:25]:
            buckets = item.get('buckets') or {}
            caps.add(widgets.row(item.get('capability', 'Unknown capability'),
                f"{item.get('attempts', 0)} steps · {buckets.get('verified', 0)} verified"
                f" · {buckets.get('failed', 0)} failed · {buckets.get('withheld', 0)} awaiting approval"))
        if not capabilities.get('capabilities'):
            caps.add(widgets.row('No capability outcomes', capabilities.get('reason', 'No data in this window')))
        box.append(caps)

        attention = metrics.get('attention') or {}
        messages = widgets.section('Notifications', 'Delivered, held and suppressed notifications remain separate.')
        for disposition, count in (attention.get('notifications_by_disposition') or {}).items():
            row = widgets.row(disposition.replace('_', ' ').title())
            row.add_suffix(widgets.tag(str(count)))
            messages.add(row)
        if not attention.get('notifications_by_disposition'):
            messages.add(widgets.row('No notifications', attention.get('reason', 'No data in this window')))
        box.append(messages)
        if data.get('honesty'):
            interpretation = widgets.section('How to read these measurements', str(data['honesty']))
            box.append(interpretation)
        timing = data.get('timing') or {}
        box.append(hud.label(f"Refreshed in {duration(timing.get('total_ms'))}. Use Refresh for new measurements.", 'hud-muted'))
        return widgets.scrolled(box)
