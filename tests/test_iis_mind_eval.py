"""MIND-small evaluation harness (IIS): metric definitions, ties, no leakage,
prequential learning and the Wilson rule, all on tiny synthetic data."""
from __future__ import annotations

import importlib.util
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, run_module  # noqa: E402

bootstrap("aries-iis-mind")

import numpy as np  # noqa: E402

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "experiments", "iis", "real-data", "mind", "mind_eval.py")
_spec = importlib.util.spec_from_file_location("mind_eval", _PATH)
me = importlib.util.module_from_spec(_spec)
sys.modules["mind_eval"] = me
_spec.loader.exec_module(me)

from aries.learning.statistics import wilson  # noqa: E402

close = lambda a, b: a is not None and abs(a - b) < 1e-9  # noqa: E731


def _news(nid, cat, sub, title, ents=()):
    return me.News(nid, cat, sub, title, list(ents))


def _imp(iid, user, t, history, cands, labels):
    return me.Impression(iid, user, float(t), list(history), list(cands), np.array(labels, dtype=np.int8))


# ── metrics ─────────────────────────────────────────────────────────────────

def test_metrics_match_hand_computed_values():
    labels = [1, 0, 0, 1]
    scores = [0.9, 0.8, 0.3, 0.1]
    # positive 0 beats both negatives, positive 3 beats neither: 2 of 4 pairs
    check("AUC 2/4", close(me.auc(labels, scores), 0.5))
    order = me.ranking(scores, [0, 1, 2, 3])
    y = np.array(labels)[order]
    check("ranking is by score, best first", list(order) == [0, 1, 2, 3])
    check("MRR is MIND's mean over clicked items: (1/1 + 1/4) / 2", close(me.mrr(y), 0.625))
    dcg5 = 1 / math.log2(2) + 1 / math.log2(5)
    ideal = 1 / math.log2(2) + 1 / math.log2(3)
    check("nDCG@5 = (1 + 1/log2 5) / (1 + 1/log2 3)", close(me.ndcg(y, 5), dcg5 / ideal))
    check("nDCG@1 counts only the top item", close(me.ndcg(y, 1), 1.0))
    check("nDCG@10 equals nDCG@5 when the list has 4 items", close(me.ndcg(y, 10), me.ndcg(y, 5)))
    check("a perfect ranking scores 1 everywhere",
          me.auc([1, 0, 0], [3, 2, 1]) == 1.0 and me.mrr([1, 0, 0]) == 1.0 and me.ndcg([1, 0, 0], 5) == 1.0)
    check("a reversed ranking has AUC 0", me.auc([0, 0, 1], [3, 2, 1]) == 0.0)


def test_undefined_impressions_are_excluded():
    check("no positive: AUC undefined", me.auc([0, 0], [1, 2]) is None)
    check("no negative: AUC undefined", me.auc([1, 1], [1, 2]) is None)
    check("no positive: MRR and nDCG undefined", me.mrr([0, 0]) is None and me.ndcg([0, 0], 5) is None)
    m = me.impression_metrics(np.array([1, 1]), np.array([0, 1]), [1.0, 2.0])
    check("no negative: MRR (MIND, all clicks) and nDCG still defined, AUC not",
          m["auc"] is None and m["mrr"] == 0.75 and m["ndcg5"] == 1.0)


def test_ties():
    check("average ranks", list(me.average_ranks([1, 1, 2])) == [1.5, 1.5, 3.0])
    check("average ranks of a three-way tie", list(me.average_ranks([5, 5, 5, 0])) == [3.0, 3.0, 3.0, 1.0])
    check("all-tied scores give AUC exactly 0.5", me.auc([1, 0, 0, 1], [0, 0, 0, 0]) == 0.5)
    check("a tie between a positive and a negative counts one half",
          close(me.auc([1, 0, 0], [1.0, 1.0, 0.0]), 0.75))
    check("ties are broken by the smaller tie-break value", list(me.ranking([1, 1, 0], [9, 3, 1])) == [1, 0, 2])
    tb1 = me.tiebreak_for(7, ["N1", "N2", "N3"])
    tb2 = me.tiebreak_for(7, ["N1", "N2", "N3"])
    check("the tie-break is deterministic", list(tb1) == list(tb2))
    check("and differs between impressions", list(me.tiebreak_for(8, ["N1", "N2", "N3"])) != list(tb1))


# ── ARIES profile and matching ──────────────────────────────────────────────

NEWS = {
    "H1": _news("H1", "sports", "tennis", "Final in Paris", ["Roland Garros"]),
    "H2": _news("H2", "politics", "elections", "Vote count", []),
    "S1": _news("S1", "sports", "golf", "Open round one"),
    "S2": _news("S2", "sports", "golf", "Open round two"),
    "S3": _news("S3", "sports", "golf", "Open round three"),
    "P1": _news("P1", "politics", "senate", "Senate vote"),
    "X1": _news("X1", "autos", "cars", "New sedan"),
    "R1": _news("R1", "travel", "places", "Roland Garros guide", ["Roland Garros"]),
}


def test_static_profile_weights_are_history_shares():
    w = me.static_weights(["H1", "H2", "MISSING"], NEWS)
    check("weights are shares of history items found in news.tsv",
          w == {"sports": 0.5, "tennis": 0.5, "roland garros": 0.5, "politics": 0.5, "elections": 0.5})
    check("empty history gives an empty profile", me.static_weights([], NEWS) == {})


def test_prefilter_is_exact():
    w = me.static_weights(["H1", "H2"], NEWS)
    prof = me.Profile(w)
    for nid, item in NEWS.items():
        toks = frozenset(me.TOKEN.findall(me.normalise(item.text)))
        sub = me.score(item.text, [prof.matchables[i] for i in prof.subset(toks)])
        full = me.score(item.text, prof.matchables)
        check(f"pre-filtered score equals full score for {nid}",
              sub.score == full.score and sub.matched == full.matched)
    r = me.score(NEWS["R1"].text, prof.matchables)
    check("a multi-word entity label matches as a phrase", r.score == 0.5 and r.matched[0]["topic"] == "roland garros")


# ── leakage and prequential order through the full pipeline ─────────────────

def _run(train, dev, news=NEWS):
    recs, extra = me.evaluate(train, dev, news, log=None, keep_scores=True, validate_pairs=10 ** 6)
    return {r["iid"]: r for r in recs}, extra


def test_popularity_does_not_leak():
    train = [_imp(1, "T", 100, [], ["S1", "S2"], [1, 0])]
    dev = [_imp(10, "U", 200, ["H1"], ["S1", "S2", "S3"], [0, 1, 0]),
           _imp(11, "V", 200, ["H1"], ["S1", "S2", "S3"], [0, 0, 1]),
           _imp(12, "W", 300, ["H1"], ["S1", "S2", "S3"], [1, 0, 0])]
    by, _ = _run(train, dev)
    check("earlier train clicks count", by[10]["scores"]["popular"] == [1.0, 0.0, 0.0])
    check("an impression's own clicks and same-time clicks do not count",
          by[11]["scores"]["popular"] == [1.0, 0.0, 0.0])
    check("strictly earlier dev clicks count", by[12]["scores"]["popular"] == [1.0, 1.0, 1.0])
    check("future clicks never count (impression 10 does not see 12's click on S1)",
          by[10]["scores"]["popular"][0] == 1.0)
    check("recent = first time listed in any impression",
          by[12]["scores"]["recent"] == [100.0, 100.0, 200.0])


def test_learning_is_prequential():
    golf = [f"G{i}" for i in range(10)]
    news = dict(NEWS)
    for g in golf:
        news[g] = _news(g, "sports", "golf", f"Golf story {g}")
    dev = [_imp(20, "U", 100, ["H1", "H2"], [*golf, "P1"], [1] * 10 + [0]),
           _imp(21, "U", 200, ["H1", "H2"], ["S1", "P1", "X1"], [1, 0, 0])]
    by, extra = _run([], dev, news)
    first, second = by[20]["scores"], by[21]["scores"]
    check("the first impression is scored before any update",
          first["aries-learning"] == first["aries-interests"])
    check("static weight of 'sports' is 0.5", second["aries-interests"][0] == 0.5)
    # 10 of 10 golf items (all 'sports') clicked: Wilson lower ~0.72 >= 0.4 -> up,
    # confidence (lower-0.4)/0.6 ~0.54, raw step 0.27, capped at max_step 0.15.
    check("the second impression sees the update from the first", second["aries-learning"][0] == 0.65)
    check("a topic with one observation is not changed", second["aries-learning"][1] == 0.5)
    check("an unmatched candidate stays at zero", second["aries-learning"][2] == 0.0)
    check("each impression is followed by a pass (sports rises twice)", extra["learning_changes"] == 2)


def test_diverse_reorders_by_primary_topic():
    news = dict(NEWS)
    news["Q1"] = _news("Q1", "sports", "tennis", "Tennis A")
    news["Q2"] = _news("Q2", "sports", "tennis", "Tennis B")
    dev = [_imp(30, "U", 100, ["H1", "H1", "H2"], ["Q1", "Q2", "P1"], [0, 0, 1])]
    by, _ = _run([], dev, news)
    s = by[30]["scores"]["aries-interests"]
    check("both tennis items outscore the politics item", s[0] > s[2] and s[1] > s[2])
    check("diverse puts the politics item second (round-robin over primary topics)",
          by[30]["diverse_order"][1] == "P1")
    check("diverse ordering changes the metric",
          by[30]["aries-interests+diverse"]["mrr"] == 0.5 and by[30]["aries-interests"]["mrr"] == 1 / 3)


def test_empty_history_is_all_ties():
    dev = [_imp(40, "E", 100, [], ["S1", "P1", "X1"], [0, 1, 0])]
    by, _ = _run([], dev)
    check("empty history: ARIES scores all zero", by[40]["scores"]["aries-interests"] == [0.0, 0.0, 0.0])
    check("and AUC is exactly 0.5", by[40]["aries-interests"]["auc"] == 0.5)
    check("and is flagged", by[40]["empty_history"] is True)


# ── the Wilson rule ─────────────────────────────────────────────────────────

def test_wilson_rule_fires_as_expected():
    st = me.TopicState(shown=10, clicked=10)
    ch = me.learning_step(st, 0.5)
    check("10 of 10 raises the weight by the capped step", ch is not None and ch["to"] == 0.65)
    check("9 of 9 is below min_observations", me.learning_step(me.TopicState(9, 9), 0.5) is None)
    check("1 of 3 is not decisive", me.learning_step(me.TopicState(3, 1), 0.5) is None)
    check("5 of 20 is not decisive (interval straddles both thresholds)",
          me.learning_step(me.TopicState(20, 5), 0.5) is None)
    iv = wilson(0, 40)
    st = me.TopicState(shown=40, clicked=0)
    ch = me.learning_step(st, 0.5)
    expected = round(0.5 - 0.5 * (0.1 - iv.upper) / 0.1, 3)
    check("0 of 40: upper <= 0.1, lowered with confidence (0.1-upper)/0.1",
          iv.upper <= 0.1 and ch is not None and ch["direction"] == "down" and ch["to"] == expected)
    check("0 of 20 is not decisive (upper above 0.1)", me.learning_step(me.TopicState(20, 0), 0.5) is None)


def test_reversal_damping_and_freeze():
    st = me.TopicState(shown=10, clicked=10)
    me.learning_step(st, 0.5)                          # up, 0.65
    st.shown, st.clicked = 400, 10                     # now clearly ignored
    ch = me.learning_step(st, st.learned)
    check("a turn-around is recorded as a reversal", ch["direction"] == "down" and st.changes[-1][1])
    st.shown, st.clicked = 400, 400
    before = st.learned
    ch = me.learning_step(st, st.learned)
    check("after one reversal the step is halved (<= 0.075)", ch is not None and ch["to"] - before <= 0.075 + 1e-9)
    st.shown, st.clicked = 400, 0
    me.learning_step(st, st.learned)                   # third reversal
    check("three reversals freeze the topic", me.learning_step(me.TopicState(400, 400, st.learned,
                                                                              list(st.changes)), st.learned) is None)


# ── embedding baseline, with a fake embedder ────────────────────────────────

class _FakeEmbedder:
    name = "fake/v1"
    calls = 0
    VEC = {"Final in Paris": [1, 0], "Vote count": [1, 0], "Open round one": [1, 0],
           "Senate vote": [0, 1], "New sedan": [1, 1]}

    def encode(self, texts, *, kind):
        _FakeEmbedder.calls += len(texts)
        m = np.array([self.VEC.get(t, [0.5, 0.5]) for t in texts], dtype=np.float32)
        return m / np.linalg.norm(m, axis=1, keepdims=True)


def test_embedding_baseline_with_fake_embedder():
    with tempfile.TemporaryDirectory() as d:
        cache = me.EmbeddingCache(d, _FakeEmbedder(), NEWS)
        cache.ensure(["H1", "H2", "S1", "P1", "X1"])
        s = me.embedding_scores(cache, ["H1", "H2"], ["S1", "P1", "X1"])
        check("cosine of mean history vector with candidates",
              np.allclose(s, [1.0, 0.0, 1 / math.sqrt(2)], atol=1e-6))
        check("empty history scores zero", list(me.embedding_scores(cache, [], ["S1"])) == [0.0])
        calls = _FakeEmbedder.calls
        again = me.EmbeddingCache(d, _FakeEmbedder(), NEWS)
        again.ensure(["H1", "S1"])
        check("the on-disk cache is reused without re-embedding", _FakeEmbedder.calls == calls)
    try:
        me.EmbeddingCache(os.path.join(me.ROOT, "var", "x"), _FakeEmbedder(), NEWS)
        check("a cache inside the repository is refused", False)
    except ValueError:
        check("a cache inside the repository is refused", True)


def test_bootstrap_is_paired_and_seeded():
    recs = []
    for i in range(40):
        u = f"U{i % 10}"
        a = {"auc": 0.6 + 0.01 * (i % 3), "mrr": 0.3, "ndcg5": 0.3, "ndcg10": 0.4}
        b = {k: v - 0.1 for k, v in a.items()}
        recs.append({"user": u, "x": a, "y": b})
    r1 = me.bootstrap(recs, ["x", "y"], [("x", "y")], replicates=200)
    r2 = me.bootstrap(recs, ["x", "y"], [("x", "y")], replicates=200)
    check("the bootstrap is reproducible", r1 == r2)
    d = r1["paired"]["x - y"]["auc"]
    check("a constant paired difference has a degenerate interval",
          close(d["diff"], 0.1) and abs(d["ci95"][0] - 0.1) < 1e-9 and abs(d["ci95"][1] - 0.1) < 1e-9)
    check("users are the resampling unit", r1["users"] == 10 and r1["impressions"] == 40)


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
