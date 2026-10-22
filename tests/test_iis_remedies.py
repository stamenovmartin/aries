"""The information-layer remedies designed after the MIND and LoCoMo results, each behind its own flag.

ARIES_MEMORY_HYBRID_RRF       retrieval.score_memories: BM25 and cosine fused by Reciprocal Rank Fusion.
ARIES_LEARNING_RELATIVE_CTR   statistics.relative_thresholds: the learning bars follow the user's own rate.
ARIES_NEWS_DIVERSE_TOPK       selection.mmr: Maximal Marginal Relevance instead of round-robin over topics.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import check, run_module

import numpy as np


def test_bm25_and_rrf():
    from aries.workspace import retrieval as R
    s = R.bm25_scores('budget meeting', ['the budget meeting is friday', 'lunch at noon', 'budget'])
    check('BM25 ranks the row with both words first', s[0] > s[2] > s[1] == 0)
    fused = R.rrf(([0.9, 0.8, 0.1], False), ([0., 5., 1.], True))
    check('a row first in one list and second in the other beats one first in only one',
          fused[1] > fused[0] and fused[1] > fused[2])
    check('a row with BM25 score 0 gets nothing from the lexical list', abs(fused[0] - 1 / 61) < 1e-12)


def rows():
    vec = lambda *x: np.array(x, dtype=np.float32) / np.linalg.norm(x)
    base = {'kind': 'fact', 'layer': 60, 'importance': .5, 'created_at': '2026-01-01T00:00:00',
            'last_retrieved_at': None}
    return [{**base, 'id': 'a', 'text': 'we talked about the weather', 'vector': vec(1, 0.1)},
            {**base, 'id': 'b', 'text': 'Caroline adopted a dog named Max', 'vector': vec(0.7, 0.7)},
            {**base, 'id': 'c', 'text': 'nothing relevant here', 'vector': vec(0.2, 1)}]


def test_hybrid_flag():
    from datetime import datetime
    from aries.workspace import retrieval as R
    q = np.array([1, 0.05], dtype=np.float32) / np.linalg.norm([1, 0.05])
    now = datetime(2026, 1, 2)
    with patch.dict(os.environ, {'ARIES_MEMORY_HYBRID_RRF': '0'}):
        off = [r['id'] for _, r, _ in R.score_memories(rows(), 'which dog did Caroline adopt',
                                                       'semantic-v3', now=now, query_vector=q)]
    with patch.dict(os.environ, {'ARIES_MEMORY_HYBRID_RRF': '1'}):
        on = [r['id'] for _, r, _ in R.score_memories(rows(), 'which dog did Caroline adopt',
                                                      'semantic-v3', now=now, query_vector=q)]
        lexical = [r['id'] for _, r, _ in R.score_memories(rows(), 'dog', 'focused-v2', now=now)]
    check('flag off: cosine alone puts the near vector first', off[0] == 'a')
    check('flag on: the row sharing the question\'s words comes first', on[0] == 'b')
    check('flag on: focused-v2 is not affected', lexical[0] == 'b')


def test_similarity_rank_flag():
    from datetime import datetime
    from aries.workspace import retrieval as R
    vec = lambda *x: np.array(x, dtype=np.float32) / np.linalg.norm(x)
    base = {**rows()[0], 'kind': 'utterance', 'text': 'x'}
    old = {**base, 'id': 'old', 'vector': vec(1, 0), 'created_at': '2025-01-01T00:00:00'}
    new = {**base, 'id': 'new', 'vector': vec(1, 0.4), 'created_at': '2026-01-01T23:00:00'}
    far = {**base, 'id': 'far', 'vector': vec(0, 1), 'created_at': '2025-01-01T00:00:00'}
    q, now = vec(1, 0), datetime(2026, 1, 2)
    with patch.dict(os.environ, {'ARIES_MEMORY_SIMILARITY_RANK': '0', 'ARIES_MEMORY_HYBRID_RRF': '0'}):
        off = [r['id'] for _, r, _ in R.score_memories([old, new, far], 'x', 'semantic-v3', now=now, query_vector=q)]
    with patch.dict(os.environ, {'ARIES_MEMORY_SIMILARITY_RANK': '1', 'ARIES_MEMORY_HYBRID_RRF': '0'}):
        on = [r['id'] for _, r, _ in R.score_memories([old, new, far], 'x', 'semantic-v3', now=now, query_vector=q)]
    check('flag off: recency lifts the newer, less similar row', off[0] == 'new')
    check('flag on: the more similar old row comes first', on[0] == 'old')


def test_relative_thresholds():
    from aries.learning.statistics import relative_thresholds
    check('a 4% user: bars at 8% and 2%', relative_thresholds(4, 100, .4, .1) == (0.08, 0.02))
    check('a 40% user: the settings are unchanged', relative_thresholds(40, 100, .4, .1) == (.4, .1))
    check('no evidence: the settings', relative_thresholds(0, 0, .4, .1) == (.4, .1))


def test_mmr():
    from aries.news.selection import diverse, mmr
    items = [('a1', 'sport', 1.0), ('a2', 'sport', .95), ('a3', 'sport', .9), ('b1', 'news', .2), ('c1', 'tv', .1)]
    pick = lambda f: [i[0] for i in f(items, topics=lambda i: [i[1]], source=lambda i: None, limit=5, per_source=0)]
    rr = pick(diverse)
    m = [i[0] for i in mmr(items, relevance=lambda i: i[2], topics=lambda i: [i[1]], source=lambda i: None,
                           limit=5, per_source=0)]
    check('round-robin puts the weak other topics second and third', rr[:3] == ['a1', 'b1', 'c1'])
    check('MMR keeps the clearly more relevant items first', m[:3] == ['a1', 'a2', 'a3'])
    close = [('a1', 'sport', 1.0), ('a2', 'sport', .8), ('b1', 'news', .95)]
    m = [i[0] for i in mmr(close, relevance=lambda i: i[2], topics=lambda i: [i[1]], source=lambda i: None,
                           limit=3, per_source=0)]
    check('MMR still prefers a nearly as relevant new topic', m == ['a1', 'b1', 'a2'])
    check('MMR respects the per-source cap', len(mmr(items, relevance=lambda i: i[2], topics=lambda i: [i[1]],
                                                     source=lambda i: 's', limit=5, per_source=2)) == 2)


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
