"""Paired review-retrieval evaluation, without executing any benchmark task."""
import hashlib
import json
from math import comb, sqrt
from pathlib import Path
from time import perf_counter
from aries.workspace import retrieval


def paired_statistics(baseline, candidate):
    """Descriptive paired binary analysis; labels are not held-out evidence."""
    if len(baseline) != len(candidate) or not baseline:
        raise ValueError('Paired nonempty outcomes required')
    n = len(baseline)
    improved = sum(not a and b for a, b in zip(baseline, candidate))
    regressed = sum(a and not b for a, b in zip(baseline, candidate))
    discordant = improved + regressed
    p = min(1., 2 * sum(comb(discordant, k) for k in range(min(improved, regressed) + 1)) / 2**discordant) if discordant else 1.

    def wilson(values):
        rate, z = sum(values) / n, 1.959963984540054
        scale = 1 + z*z/n
        center = (rate + z*z/(2*n)) / scale
        radius = z * sqrt(rate*(1-rate)/n + z*z/(4*n*n)) / scale
        return [max(0., center-radius), min(1., center+radius)]

    return {'pairs': n, 'improved': improved, 'regressed': regressed,
            'accuracy_difference': (sum(candidate)-sum(baseline))/n,
            'exact_mcnemar_two_sided_p': p,
            'baseline_wilson_95': wilson(baseline), 'candidate_wilson_95': wilson(candidate),
            'interpretation': 'Exploratory developer-labelled fixture; dependent topics and development reuse prevent population or causal claims.'}


# WHICH TWO ARMS THE HEADLINE STATISTICS DESCRIBE
# ----------------------------------------------
# `retrieval.VERSIONS` gained a third member when semantic memory landed, and a
# paired test compares two things. Rather than silently re-point the comparison,
# the pair is named here: `overlap-v1` is the baseline and stays the baseline,
# and `focused-v2` remains the promotion candidate for TASK-REVIEW retrieval, so
# every comparison already recorded under `experiments/learning/` keeps meaning
# what it meant. Each further version is compared against the same baseline in
# `against_baseline`, so nothing is hidden and nothing is overwritten.
#
# `semantic-v3` is evaluated here for completeness. It is proposed for MEMORY
# retrieval, where it is measured against its own baseline with its own fixture
# in `experiments/memory/`; a twenty-case review fixture is not the evidence
# that would promote it, and this file does not promote anything.
BASELINE = 'overlap-v1'
PROMOTION_CANDIDATE = 'focused-v2'


def compare():
    path = Path(__file__).with_name('fixtures')/'retrieval_v1.json'
    payload = path.read_bytes()
    fixture = json.loads(payload)
    rows = [{'id':r['id'], 'episode':{'request':r['request']}} for r in fixture['reviews']]
    comparisons = {}
    for version in retrieval.VERSIONS:
        cases, true, extra, missed = [], 0, 0, 0
        for case in fixture['cases']:
            started = perf_counter()
            selected = [r['id'] for r in retrieval.rank(rows, case['query'], version)]
            elapsed = (perf_counter()-started)*1000
            expected, actual = set(case['expected']), set(selected)
            true += len(expected & actual); extra += len(actual - expected); missed += len(expected - actual)
            cases.append({'id':case['id'], 'query':case['query'], 'expected':case['expected'],
                          'selected':selected, 'passed':expected==actual, 'elapsed_ms':round(elapsed,4)})
        comparisons[version] = {'passed':sum(c['passed'] for c in cases), 'total':len(cases),
            'precision':true/(true+extra) if true+extra else None,
            'recall':true/(true+missed) if true+missed else None,
            'extra_retrievals':extra, 'missed_retrievals':missed, 'cases':cases}
    baseline = comparisons[BASELINE]

    def against(name):
        other = comparisons[name]
        return {'regressions':[a['id'] for a,b in zip(baseline['cases'],other['cases']) if a['passed'] and not b['passed']],
                'improvements':[a['id'] for a,b in zip(baseline['cases'],other['cases']) if not a['passed'] and b['passed']],
                'statistics':paired_statistics([c['passed'] for c in baseline['cases']], [c['passed'] for c in other['cases']])}

    pairs = {name: against(name) for name in retrieval.VERSIONS if name != BASELINE}
    headline = pairs[PROMOTION_CANDIDATE]
    from aries.workspace import reviews
    implementation = Path(retrieval.__file__).read_bytes() + b'\0' + Path(reviews.__file__).read_bytes()
    return {'fixture_version':fixture['version'], 'fixture_sha256':hashlib.sha256(payload).hexdigest(),
        'implementation_sha256':hashlib.sha256(implementation).hexdigest(),
        'scope':fixture['scope'], 'versions':comparisons,
        'baseline':BASELINE, 'candidate':PROMOTION_CANDIDATE,
        'regressions':headline['regressions'], 'improvements':headline['improvements'],
        'recommendation':'candidate_on_this_fixture' if headline['improvements'] and not headline['regressions'] else 'keep_baseline',
        'promoted':False,
        'semantic_retrieval_available':retrieval.semantic_available(),
        'against_baseline':pairs,
        'statistics':headline['statistics']}


async def report(db):
    from aries.settings import SettingsService
    result = compare()
    active = await SettingsService(db).get('workspace.review_retrieval')
    cards = [{'title':'Review experience comparison',
              'text':f"Active version: {active}. Headline pair: {result['baseline']} vs {result['candidate']}. No version changed by this run.",
              'evidence':result['scope']}]
    for version, score in result['versions'].items():
        cards.append({'title':version, 'text':f"{score['passed']}/{score['total']} relevance cases matched exactly · {score['extra_retrievals']} unrelated inclusions · {score['missed_retrievals']} misses",
                      'evidence':'Same frozen corpus and queries for all versions; expected labels authored before this comparison.'})
    cards.append({'title':'Changes by case', 'text':f"{len(result['improvements'])} improvements · {len(result['regressions'])} regressions",
                  'evidence':'A narrow offline result, not evidence of better general task execution or model training.'})
    for name, pair in result['against_baseline'].items():
        stats = pair['statistics']
        note = stats['interpretation']
        if name == 'semantic-v3' and not result['semantic_retrieval_available']:
            note = ('No embedder is installed, so semantic-v3 degraded to focused-v2 and this row '
                    'measures that fallback. Run ./scripts/aries-fetch-embedder. ') + note
        cards.append({'title':f"Paired statistical comparison — {result['baseline']} vs {name}",
                      'text': f"Accuracy difference {stats['accuracy_difference']:+.0%} · exact two-sided McNemar p={stats['exact_mcnemar_two_sided_p']:.3f}",
                      'evidence': note})
    for case in result['versions']['focused-v2']['cases']:
        baseline = next(c for c in result['versions']['overlap-v1']['cases'] if c['id']==case['id'])
        cards.append({'title':case['id'], 'text':case['query'] or '(empty request)',
                      'evidence':f"Expected {case['expected']} · baseline {baseline['selected']} · candidate {case['selected']}"})
    total = result['versions'][result['baseline']]['total']
    return {'state':'done', 'summary':f"Compared {len(result['versions'])} retrieval versions on the same {total} labelled relevance cases",
            'cards':cards, 'comparison':result, 'active_version':active}
