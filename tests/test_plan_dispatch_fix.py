"""ARIES_PLAN_DISPATCH_FIX: the planner context's audit metadata must not fail a goal before planning.

docs/AUDIT.md 7.2: six held-out goals failed with 'Context metadata exceeds planner budget' before their first
planner call. Each memory dropped for budget adds an omitted_items entry, so with many memories the metadata alone
outgrows the budget.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-plan-dispatch-fix')
from aries import flags
from aries.workspace.context_engine import Item, planner_context, select


def crowded():
    """A constructed case (the 2026-10-06 contexts were not saved): four long-id records that do not fit, ten
    source statuses and preferences that need the bounded envelope. Once every record is dropped, the
    omitted_items entries, source_status and preferences alone exceed 2,500 characters."""
    sources = ['memory', 'tasks', 'projects', 'files']
    items = [Item('https://example.org/2026/10/06/' + 'a-long-article-slug-' * 12 + f'{k:03d}', sources[k % 4],
                  f'project comet update {k} ' + 'detail ' * 12, relevance=1 - k / 1000) for k in range(60)]
    packet = select(items, 'project comet news tasks calendar', max_chars=2000)
    packet['source_status'] = {s: {'status': 'ok', 'truncated': False} for s in
                               ('memory', 'tasks', 'projects', 'files', 'calendar', 'news', 'reviews', 'mail',
                                'notes', 'browser')}
    return packet


PREFERENCES = [{'rule': f'Prefer "concise" replies about "topic" {k}', 'weight': 0.7} for k in range(40)]


def test_flag_is_registered_and_off_by_default():
    check('registered', 'ARIES_PLAN_DISPATCH_FIX' in flags.FLAGS)
    check('default off', flags.FLAGS['ARIES_PLAN_DISPATCH_FIX'][0] is False)


def test_off_reproduces_the_frozen_failure():
    packet = crowded()
    with patch.dict('os.environ', {'ARIES_PLAN_DISPATCH_FIX': '0'}):
        try:
            planner_context({'preferences': PREFERENCES}, packet)
            raised = None
        except ValueError as exc:
            raised = str(exc)
    check('the frozen error is raised', raised == 'Context metadata exceeds planner budget')


def test_on_compacts_the_metadata_and_fits():
    packet = crowded()
    original = json.dumps(packet, sort_keys=True)
    with patch.dict('os.environ', {'ARIES_PLAN_DISPATCH_FIX': '1'}):
        context = planner_context({'preferences': PREFERENCES}, packet)
    coverage = context['context_coverage']
    check('fits the budget', len(json.dumps(context, ensure_ascii=False)) <= 2500)
    check('omissions are still counted', coverage['omitted_items']['count'] >= 1
          and sum(coverage['omitted_items']['by_source_and_reason'].values()) == coverage['omitted_items']['count'])
    check('the compaction is recorded', coverage['compacted'][0] == 'omitted_items_counted')
    check('preferences survive when they fit', 'preferences' in context)
    check('saved packet unchanged', json.dumps(packet, sort_keys=True) == original)


def test_on_leaves_a_context_that_fits_unchanged():
    packet = select([Item('a', 'memory', 'project comet deadline', relevance=1)], 'project comet', max_chars=2000)
    with patch.dict('os.environ', {'ARIES_PLAN_DISPATCH_FIX': '0'}):
        off = planner_context({'preferences': []}, packet)
    with patch.dict('os.environ', {'ARIES_PLAN_DISPATCH_FIX': '1'}):
        on = planner_context({'preferences': []}, packet)
    check('identical when nothing overflows', on == off)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
