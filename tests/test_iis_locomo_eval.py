"""LoCoMo retrieval evaluation: id mapping, metric definitions, aggregation, exclusion.

Runs on a five-turn synthetic conversation in LoCoMo's JSON shape. No dataset,
no embedding model and no local model: the embedder is a lookup table and the
stage-3 model is a constant function, so this passes on a machine with neither.
"""
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
from tests._bootstrap import bootstrap, check, run_module  # noqa: E402

bootstrap("aries-iis-locomo")
import numpy as np  # noqa: E402

from aries.workspace.memory import calibration, extraction  # noqa: E402

_PATH = Path(__file__).resolve().parents[1] / "experiments" / "iis" / "real-data" / "locomo" / "locomo_eval.py"
_spec = importlib.util.spec_from_file_location("locomo_eval", _PATH)
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)


def _unit(*values):
    v = np.array(values, dtype=np.float32)
    return v / np.linalg.norm(v)


class TableEmbedder:
    """Text -> a chosen vector, by the first key the text contains."""
    name, dim = "table", 4
    TABLE = [("Rex", _unit(1, 0, 0, 0)), ("dog", _unit(1, 0, 0, 0)), ("Ohrid", _unit(0, .9, .436, 0)),
             ("Skopje", _unit(0, 1, 0, 0)), ("breed", _unit(0, 0, 0, 1))]

    def encode(self, texts, *, kind):
        out = []
        for text in texts:
            out.append(next((v for key, v in self.TABLE if key in text), _unit(0, 0, 1, 1)))
        return np.stack(out)

    def query(self, text):
        return self.encode([text], kind="query")[0]

    def passages(self, texts):
        return self.encode(list(texts), kind="passage")


RAW = [{
    "sample_id": "synthetic-1",
    "conversation": {
        "speaker_a": "Ana", "speaker_b": "Boris",
        "session_1_date_time": "1:00 pm on 1 May, 2023",
        "session_1": [
            {"speaker": "Ana", "dia_id": "D1:1", "text": "I adopted a dog named Rex."},
            {"speaker": "Boris", "dia_id": "D1:2", "text": "What is his breed?"},
            {"speaker": "Ana", "dia_id": "D1:3", "text": "I adopted a dog named Rex!"},
        ],
        "session_2_date_time": "9:30 am on 3 June, 2023",
        "session_2": [
            {"speaker": "Ana", "dia_id": "D2:1", "text": "I moved to Skopje last year."},
            {"speaker": "Ana", "dia_id": "D2:2", "text": "I now live in Ohrid, not Skopje."},
        ],
        "session_3_date_time": "9:30 am on 9 June, 2023",
    },
    "qa": [
        {"question": "What is the dog's name?", "answer": "Rex", "evidence": ["D1:3"], "category": 4},
        {"question": "Did Ana adopt a cat?", "adversarial_answer": "no", "evidence": [], "category": 5},
        {"question": "Where is the dog now?", "answer": "?", "evidence": ["D9:9"], "category": 4},
        {"question": "Where does Ana live, Ohrid?", "answer": "Ohrid", "evidence": ["D:2:2"], "category": 2},
        {"question": "What breed?", "answer": "?", "evidence": ["D1:2"], "category": 1},
    ],
}]


def conversations():
    return L.load_conversations(json.loads(json.dumps(RAW)))


def supersede_model():
    seen = []

    def classify(prompt, labels, **_):
        seen.append(prompt)
        return L.constant_decision("SUPERSEDE")(prompt, labels)
    return classify, seen


def test_loading_keeps_session_order_and_dates():
    conv = conversations()[0]
    turns = conv["turns"]
    check("turns arrive in session order", [t["dia_id"] for t in turns] == ["D1:1", "D1:2", "D1:3", "D2:1", "D2:2"])
    check("valid_at is the session's date and time", str(turns[0]["at"]) == "2023-05-01 13:00:00"
          and str(turns[3]["at"]) == "2023-06-03 09:30:00")
    check("turns inside a session stay ordered", turns[0]["at"] < turns[1]["at"] < turns[2]["at"])
    check("a session with a date but no turns does not move 'now'", str(conv["now"]) == "2023-06-03 09:30:01")
    check("speaker is kept in the stored text but not in what the gate judges",
          turns[1]["text"] == "Boris: What is his breed?" and turns[1]["content"] == "What is his breed?")
    with_caption = L.turn_content({"text": "Look!", "blip_caption": "a photo of a dog"})
    check("a shared photo's caption is part of the turn", with_caption == "Look! [shares a photo of a dog]")


def test_exclusion_rule_and_evidence_normalisation():
    items = conversations()[0]["items"]
    check("an item with no evidence is excluded as no-evidence", items[1]["excluded"] == "no-evidence")
    check("an item whose evidence is not in the conversation is excluded",
          items[2]["excluded"] == "evidence-not-in-conversation" and items[2]["evidence_absent"] == 1)
    check("a malformed id 'D:2:2' is normalised and counted",
          items[3]["evidence"] == ["D2:2"] and items[3]["malformed"] == 1)
    ids, bad = L.parse_evidence(["D8:6; D9:17", "D", "D1:1"])
    check("several ids in one string are all kept, a bare 'D' contributes none",
          ids == ["D8:6", "D9:17", "D1:1"] and bad == 2)
    outcomes, _, _ = L.evaluate_conversation("bm25", conversations()[0])
    check("excluded items are not scored", sorted(o["index"] for o in outcomes) == [0, 3, 4])
    census = L.census(conversations())
    check("the census counts each exclusion reason",
          census["qa_excluded"] == {"no-evidence": 1, "evidence-not-in-conversation": 1})


def test_merge_keeps_every_source_id_and_counts_as_a_hit():
    classify, seen = supersede_model()
    cascade = L.InjectableCascade(classify=classify)
    conv = conversations()[0]
    rows, counts = L.build("cascade-e5", conv, embedder=TableEmbedder(), cascade=cascade)
    sources = [r["sources"] for r in rows]
    check("the gate refused the question turn", counts["gate_refused"] == 1)
    check("the verbatim restatement was merged, not stored", ["D1:1", "D1:3"] in sources and counts["merged"] == 1)
    merged = next(r for r in rows if r["sources"] == ["D1:1", "D1:3"])
    check("a merge refreshes the neighbour's recency to the restating turn's time",
          str(merged["last_retrieved_at"]) == "2023-05-01 13:00:02")
    check("the uncertain-band turn reached the injected model exactly once",
          counts["model_calls"] == 1 and len(seen) == 1 and "Ohrid" in seen[0])
    check("SUPERSEDE keeps both rows, as the store does", ["D2:1"] in sources and ["D2:2"] in sources
          and counts["supersede_kept_both"] == 1)
    check("three rows stored from five turns", counts["stored"] == 3 and counts["offered"] == 5)
    top = L.ranker("cascade-e5", rows, conv["now"], embedder=TableEmbedder())
    outcome = L.score_item(top("What is the dog's name?"), ["D1:3"])
    check("a merged row is a hit for an item citing its SECOND source", outcome["hit@1"] == 1. and outcome["mrr"] == 1.)


def test_the_real_model_is_never_called_when_a_fake_is_injected():
    original = calibration.classify

    def forbidden(*_, **__):
        raise AssertionError("the real local model was called")
    calibration.classify = forbidden
    try:
        classify, _ = supersede_model()
        cascade = L.InjectableCascade(classify=classify)
        L.build("cascade-e5", conversations()[0], embedder=TableEmbedder(), cascade=cascade)
        check("the injected classify answered", cascade.calls == 1)
        check("the module binding is restored afterwards", extraction.calibration is calibration)
    finally:
        calibration.classify = original
    check("a cascade with no injection would use the shipped classify",
          L.InjectableCascade()._classify is None)


def test_gate_only_variant_loses_refused_evidence_and_bm25_does_not():
    conv = conversations()[0]
    gated, _, _ = L.evaluate_conversation("embedding-only-e5", conv, embedder=TableEmbedder())
    lexical, _, _ = L.evaluate_conversation("bm25", conv)
    g = next(o for o in gated if o["index"] == 4)
    b = next(o for o in lexical if o["index"] == 4)
    check("evidence refused by stage 1 is unstorable for the gated variant",
          g["gold_storable"] == 0. and g["hit@5"] == 0.)
    check("bm25 stores every turn, so the same item is storable", b["gold_storable"] == 1.)
    rows, _ = L.build("embedding-only-e5", conv, embedder=TableEmbedder())
    check("embedding-only stores every permitted turn without merging", [r["sources"] for r in rows]
          == [["D1:1"], ["D1:3"], ["D2:1"], ["D2:2"]])


def test_hit_and_mrr_definitions():
    rows = [{"sources": ["D1:1"]}, {"sources": ["D1:2", "D1:9"]}, {"sources": ["D2:1"]},
            {"sources": ["D2:2"]}, {"sources": ["D3:3"]}]
    second = L.score_item(rows, ["D1:9"])
    check("first hit at rank 2: hit@1=0, hit@3=1, hit@5=1, rr=1/2",
          (second["hit@1"], second["hit@3"], second["hit@5"], second["mrr"]) == (0., 1., 1., .5))
    fifth = L.score_item(rows, ["D3:3", "D7:7"])
    check("first hit at rank 5: hit@3=0, hit@5=1, rr=1/5, recall 1/2",
          (fifth["hit@3"], fifth["hit@5"], fifth["mrr"], fifth["recall@5"]) == (0., 1., .2, .5))
    none = L.score_item(rows, ["D9:9"])
    check("no hit in the top five: everything zero", all(v == 0. for v in none.values()))
    first = L.score_item(rows, ["D2:2", "D1:1"])
    check("the FIRST matching rank defines RR even with several evidence turns",
          first["mrr"] == 1. and first["recall@5"] == 1.)


def test_bm25_ranks_and_breaks_ties_by_storage_order():
    rows = [{"text": "Ana: I like tea"}, {"text": "Boris: Rex is a dog"}, {"text": "Ana: Rex is a dog"},
            {"text": "Ana: nothing"}]
    top = L.BM25(rows).top("Who has a dog named Rex?")
    check("only rows sharing a term are returned", len(top) == 2)
    check("equal scores keep storage order", top[0] is rows[1] and top[1] is rows[2])


def test_category_aggregation():
    outcomes = []
    for conv, category, hit in [(0, 1, 1.), (0, 1, 0.), (0, 4, 1.), (1, 4, 1.), (1, 5, 0.), (1, 5, 0.)]:
        o = {f"hit@{k}": hit for k in L.CUTS}
        o.update(mrr=hit, **{"recall@5": hit}, conversation=conv, index=len(outcomes), category=category,
                 gold_storable=1.)
        outcomes.append(o)
    report = L.aggregate(outcomes, b=200)
    check("overall counts every scored item", report["all"]["n"] == 6 and report["all"]["hit@5"]["mean"] == .5)
    check("non-adversarial leaves out category 5", report["non-adversarial (1-4)"]["n"] == 4
          and report["non-adversarial (1-4)"]["hit@5"]["mean"] == .75)
    check("categories carry the LoCoMo names", report["1 multi-hop"]["hit@5"]["mean"] == .5
          and report["4 single-hop"]["n"] == 2 and report["5 adversarial"]["hit@5"]["mean"] == 0.)
    check("categories with no items are absent", "2 temporal" not in report and "3 open-domain" not in report)
    check("a single-conversation category has a degenerate cluster interval",
          report["1 multi-hop"]["conversations"] == 1
          and report["1 multi-hop"]["hit@5"]["ci95_conversation_cluster"] == [.5, .5])
    flipped = [{**o, **{k: 1. - o[k] for k in L.METRICS}} for o in outcomes]
    diff = L.paired(flipped, outcomes, b=200)
    check("paired differences are candidate minus baseline", diff["all"]["hit@5"]["mean"] == 0.
          and diff["5 adversarial"]["hit@5"]["mean"] == 1.)


def test_bootstrap_intervals_are_seeded_and_cover_the_mean():
    values = np.array([1., 0., 1., 1., 0., 1., 0., 0.])
    groups = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    a = L.bootstrap_item(values, groups, b=500, seed=7)
    b = L.bootstrap_item(values, groups, b=500, seed=7)
    check("the same seed gives the same draws", np.array_equal(a, b))
    lo, hi = L.interval(L.bootstrap_cluster(values, groups, b=500, seed=7))
    check("the cluster interval spans the two conversation means", lo == .25 and hi == .75)


def test_results_are_never_overwritten():
    directory = tempfile.mkdtemp()
    first, second = L.output_path(directory), L.output_path(directory)
    check("two runs in the same second get two files", first != second and first.exists() and second.exists())


def test_run_always_includes_the_baseline_and_both_comparisons():
    classify, _ = supersede_model()
    result = L.run(conversations(), ["embedding-only-e5", "cascade-e5"],
                   embedder_factory=lambda name: TableEmbedder(), classify=classify, b=100, log=lambda *_: None)
    check("bm25 is added to every run", list(result["variants"]) == ["bm25", "embedding-only-e5", "cascade-e5"])
    check("each variant is paired with bm25 and the cascade with embedding-only",
          set(result["comparisons"]) == {"embedding-only-e5 - bm25", "cascade-e5 - bm25",
                                         "cascade-e5 - embedding-only-e5"})
    cascade = result["variants"]["cascade-e5"]
    check("LLM calls, stored rows and wall time are reported", cascade["llm_calls"] == 1
          and cascade["stored_rows"] == 3 and cascade["wall_s"] >= 0 and "INVALID" not in cascade)


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
