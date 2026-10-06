"""Analytics must show uncertainty and missing data without inventing success."""
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
from aries_ui.pages.analytics import AnalyticsPage, rate_text, latency_text

failures = []
def check(name, ok):
    print(('PASS  ' if ok else 'FAIL  ') + name)
    if not ok:
        failures.append(name)

def text(widget):
    values = []
    for method in ('get_label', 'get_title', 'get_subtitle'):
        if hasattr(widget, method):
            values.append(str(getattr(widget, method)() or ''))
    child = widget.get_first_child()
    while child:
        values.append(text(child))
        child = child.get_next_sibling()
    return '\n'.join(values)

page = AnalyticsPage(SimpleNamespace(client=None))
empty = text(page.render({'metrics': {}}))
check('empty windows never become 0% or 100% success', '0%' not in empty and 'No task outcomes' in empty)
check('missing rates remain unavailable', rate_text(None)[0] == '—')
check('unexpected missing-rate values do not crash', rate_text('unavailable')[0] == '—')
rate = {'successes': 3, 'trials': 4, 'rate': .75, 'lower': .301, 'upper': .954}
check('small samples retain denominator and confidence interval',
      rate_text(rate) == ('75.0%', '3 of 4 · 95% interval 30%–95%'))
check('latency uses quantiles and sample count',
      latency_text({'n': 2, 'p50': 100, 'p90': 2000, 'p99': 3000}) ==
      'Median 100ms · p90 2.0s · p99 3.0s · 2 samples')
payload = {'failed_metrics': ['attention'], 'window': {'goal_scan_cap': 500},
 'metrics': {'task_outcomes': {'truncated': True, 'n': 4, 'success': rate},
             'model_usage': {'models': [{'model': 'test', 'n': 18,
              'task_type': 'workspace.m14-planner', 'ok': {'rate': 0, 'successes': 0,
              'trials': 18, 'lower': 0, 'upper': .176}}]},
             'locking_failures': {'n': 74, 'hours_affected': 38}}}
rendered = text(page.render(payload))
check('partial and truncated measurements remain visible',
      'some measurements are unavailable' in rendered.lower() and 'limited history sample' in rendered.lower())
check('planner failures are shown with their denominator',
      'workspace.m14-planner' in rendered and '0 of 18' in rendered)
check('unknown cost is never displayed as free', 'not a zero-cost claim' in rendered)
calls = []
page.days = 30
page.fetch(SimpleNamespace(get=lambda path, **kw: calls.append((path, kw))))
check('selected period bounds the existing read-only endpoint',
      calls == [('/api/aries/analytics', {'days': 30, 'goal_scan': 500})])
print('ALL PASSED' if not failures else 'FAILURES')
sys.exit(bool(failures))
