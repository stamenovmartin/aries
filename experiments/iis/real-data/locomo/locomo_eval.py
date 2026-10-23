"""LoCoMo, scored as RETRIEVAL against the annotated evidence turns.

WHAT THIS MEASURES
------------------
For each of LoCoMo's 10 conversations every dialogue turn is offered, in session
order, to one ARIES memory variant. For each QA item the question is used as the
retrieval request and the top 5 rows are taken. A row is a HIT for an item when
any of the dialogue ids it was built from (`D<session>:<turn>`) is among the
item's evidence ids. Scored: hit@1, hit@3, hit@5, MRR over the top 5, and
evidence recall@5 (the share of an item's evidence turns covered by the top 5).

WHY EVIDENCE AND NOT ANSWERS
----------------------------
`aries/workspace/memory_eval.py` explains why ARIES avoided LoCoMo: 6.4% of its
ANSWER key is wrong. No answer string is read here. The evidence annotations are
a different label (which turns support the question), and retrieval is the part
of memory that ARIES's semantic layer is responsible for; answer generation is
not evaluated at all.

VARIANTS
--------
    bm25                    every turn verbatim, Okapi BM25 (k1=1.2, b=0.75)
    verbatim-focused        every turn verbatim, ARIES `focused-v2` lexical scoring
    embedding-only-e5       stage 1 gate only, every permitted turn stored,
                            `semantic-v3` with e5-base-int8  (memory_eval's
                            `verbatim-gated-semantic`)
    embedding-only-bge-m3   the same with bge-m3 through ollama
    cascade-e5              the full three-stage cascade (`extraction.Cascade.run`)
                            then `semantic-v3`  (memory_eval's `extracted-semantic`)
    cascade-bge-m3          the same with bge-m3

The first two need no model. The other four load an embedder, and the cascade
variants call the local decision model through `InjectableCascade`, whose
classify function can be replaced (tests and `--dry-run-calls` do so).

Nothing is tuned on LoCoMo: every ARIES parameter is its shipped default
(`DEFAULTS` below records them in each result file).

Run from the repository root:

    OPENBLAS_NUM_THREADS=1 nice -n 19 .venv/bin/python \\
        experiments/iis/real-data/locomo/locomo_eval.py --variants bm25,verbatim-focused
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import types
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
for _p in (ROOT / "vendor" / "agentic-core", ROOT / "vendor", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
# Importing the memory package pulls in the ORM models. Point the engine at a
# throwaway file so that nothing here can ever touch a live database.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{tempfile.mkdtemp(prefix='locomo-')}/unused.db")
os.environ.setdefault("DRY_RUN", "true")

import numpy as np  # noqa: E402

from aries.workspace import retrieval  # noqa: E402
from aries.workspace.learning_eval import paired_statistics  # noqa: E402
from aries.workspace.memory import calibration, embedding, extraction, vectors  # noqa: E402
from aries.workspace.models import HALF_LIFE_HOURS, IMPORTANCE  # noqa: E402

DATA = Path(os.environ.get("LOCOMO_DATA", Path.home() / "data-ext" / "locomo" / "locomo10.json"))
DATA_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
RESULTS = HERE / "results"
K = 5
CUTS = (1, 3, 5)
BOOTSTRAP = 10000
SEED = 20261022

# LoCoMo stores the category as a number. The names follow the comments in the
# official scorer, snap-research/locomo task_eval/evaluation.py ("multi-hop" on
# the category-1 branch, "adversarial" on the category-5 branch, and
# "single-hop, temporal, open-domain" on the joint 2/3/4 branch). 2/3/4 were
# assigned by checking the data itself (see NOTES.md): category 1 has 3.1
# evidence turns per item and 96% span sessions (multi-hop); 77% of category-2
# questions begin "When" (temporal); category 4 is the largest set at 1.06
# evidence turns (single-hop); category 3 asks for inference ("would ... be
# likely to") (open-domain).
CATEGORIES = {1: "multi-hop", 2: "temporal", 3: "open-domain", 4: "single-hop", 5: "adversarial"}

# Every ARIES parameter the variants depend on, at its shipped default. Recorded
# in each result file; none is changed for LoCoMo.
DEFAULTS = {
    "retrieval_version": "semantic-v3 (setting workspace.memory_retrieval default)",
    "weights": {"similarity": retrieval.W_SIM, "recency": retrieval.W_RECENCY,
                "importance": retrieval.W_IMPORTANCE, "layer": retrieval.W_LAYER},
    "max_layer": retrieval.MAX_LAYER, "row_layer": 60,
    "importance_by_kind": IMPORTANCE, "half_life_hours_by_kind": HALF_LIFE_HOURS,
    "cascade": {"redundant_above": extraction.REDUNDANT_ABOVE, "novel_below": extraction.NOVEL_BELOW,
                "model": "qwen2.5:7b", "context": 4, "timeout_s": 30, "neighbours": 5},
    "gate": {"min_chars": extraction.MIN_CHARS, "max_chars": extraction.MAX_CHARS,
             "excluded_topics": [], "remember_conversations": True},
    "embedders": {"e5": "e5-base-int8 (max_tokens 256, threads 4)", "bge-m3": "bge-m3 via ollama"},
    "bm25": {"k1": 1.2, "b": 0.75, "idf": "ln(1 + (N - df + 0.5) / (df + 0.5))",
             "tokens": "casefolded \\w+, no stemming, no stop words"},
    "k": K,
}

VARIANTS = {
    "bm25":                  {"store": "all",     "rank": "bm25",        "embedder": None},
    "verbatim-focused":      {"store": "all",     "rank": "focused-v2",  "embedder": None},
    "embedding-only-e5":     {"store": "gated",   "rank": "semantic-v3", "embedder": "e5-base-int8"},
    "embedding-only-bge-m3": {"store": "gated",   "rank": "semantic-v3", "embedder": "bge-m3-ollama"},
    "cascade-e5":            {"store": "cascade", "rank": "semantic-v3", "embedder": "e5-base-int8"},
    "cascade-bge-m3":        {"store": "cascade", "rank": "semantic-v3", "embedder": "bge-m3-ollama"},
    # Added after the 2026-10-22 results (preregistration docs/preregistration/M1-information-layer-remedies.md).
    # Same store as embedding-only-e5, so only the ranking differs.
    "hybrid-rrf-e5":         {"store": "gated",   "rank": "semantic-v3", "embedder": "e5-base-int8",
                              "flags": {"ARIES_MEMORY_HYBRID_RRF": "1"}},
    "cosine-only-e5":        {"store": "gated",   "rank": "cosine",      "embedder": "e5-base-int8"},
    "rrf-only-e5":           {"store": "gated",   "rank": "rrf",         "embedder": "e5-base-int8"},
    # Added after the M1 run: the shipped flag pair whose ranking rrf-only-e5 approximated (exploratory).
    "hybrid-similarity-e5":  {"store": "gated",   "rank": "semantic-v3", "embedder": "e5-base-int8",
                              "flags": {"ARIES_MEMORY_HYBRID_RRF": "1", "ARIES_MEMORY_SIMILARITY_RANK": "1"}},
}
BASELINE = "bm25"
NO_MODEL = ("bm25", "verbatim-focused")


# ── data ─────────────────────────────────────────────────────────────────────

_SESSION = re.compile(r"session_(\d+)")
_EVIDENCE = re.compile(r"D:?(\d+):(\d+)")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_when(value):
    """'1:56 pm on 8 May, 2023' -> datetime. Every LoCoMo session uses this form."""
    return datetime.strptime(value.strip(), "%I:%M %p on %d %B, %Y")


def turn_content(turn):
    """What was said: the text, plus the BLIP caption of a shared photo.

    The caption is LoCoMo's own textual stand-in for the image and is what the
    LoCoMo RAG baselines index; it is applied identically to every variant.
    """
    text = turn.get("text") or ""
    caption = turn.get("blip_caption")
    return f"{text} [shares {caption}]" if caption else text


def parse_evidence(raw):
    """Evidence ids, normalised. Returns (ids, malformed_count).

    Six of 2,815 entries are malformed upstream ('D8:6; D9:17', 'D:11:26',
    'D9:1 D4:4 D4:6', a bare 'D'); every `D<s>:<t>` inside them is kept, and a
    string with none contributes nothing.
    """
    ids, malformed = [], 0
    for entry in raw or []:
        entry = str(entry)
        if not re.fullmatch(r"D\d+:\d+", entry.strip()):
            malformed += 1
        for s, t in _EVIDENCE.findall(entry):
            ident = f"D{int(s)}:{int(t)}"
            if ident not in ids:
                ids.append(ident)
    return ids, malformed


def load_conversations(raw):
    """LoCoMo JSON (already parsed) -> conversations with turns and QA items."""
    conversations = []
    for number, sample in enumerate(raw):
        conv = sample["conversation"]
        sessions = sorted((int(m.group(1)), key) for key in conv
                          if (m := _SESSION.fullmatch(key)) and isinstance(conv[key], list))
        turns = []
        for session, key in sessions:
            start = parse_when(conv[f"{key}_date_time"])
            for index, turn in enumerate(conv[key]):
                content = extraction.normalise(turn_content(turn))
                turns.append({
                    "dia_id": turn["dia_id"], "session": session, "index": index,
                    "speaker": turn.get("speaker", ""), "content": content,
                    # The store has one user; LoCoMo has two speakers. The name is
                    # kept in the stored text because the questions use it.
                    "text": extraction.normalise(f"{turn.get('speaker', '')}: {content}"),
                    # valid_at = the session's date and time; turns one second apart
                    # so the order inside a session is preserved.
                    "at": start + timedelta(seconds=index),
                })
        present = {t["dia_id"] for t in turns}
        items = []
        for qa_index, qa in enumerate(sample.get("qa", [])):
            ids, malformed = parse_evidence(qa.get("evidence"))
            valid = [i for i in ids if i in present]
            items.append({"conversation": number, "index": qa_index, "category": int(qa["category"]),
                          "question": qa["question"], "evidence": valid,
                          "evidence_parsed": len(ids), "evidence_absent": len(ids) - len(valid),
                          "malformed": malformed,
                          "excluded": None if valid else ("no-evidence" if not ids else "evidence-not-in-conversation")})
        conversations.append({"sample_id": sample.get("sample_id", str(number)), "number": number,
                              "turns": turns, "items": items,
                              # Questions are asked after the last session.
                              "now": max(t["at"] for t in turns)})
    return conversations


def load(path=DATA, *, verify=True):
    path = Path(path)
    if verify:
        actual = sha256(path)
        if actual != DATA_SHA256:
            raise SystemExit(f"{path}: sha256 {actual} != {DATA_SHA256}; run download.sh")
    return load_conversations(json.loads(path.read_text()))


# ── the cascade, with its model stage injectable ─────────────────────────────

class InjectableCascade(extraction.Cascade):
    """`extraction.Cascade`, unchanged, except that stage 3's classify call can be
    replaced. `decide` is the shipped method: the prompt, the few-shot examples
    and the Verdict all come from ARIES. Only the function it calls is swapped,
    by rebinding the `calibration` name `extraction` resolves at call time.

    classify=None means the real `calibration.classify` against local ollama.
    """

    def __init__(self, classify=None, **settings):
        super().__init__(**settings)
        self._classify = classify
        self.latencies = []

    def decide(self, text, neighbours, *, lang=""):
        started = perf_counter()
        if self._classify is None:
            try:
                return super().decide(text, neighbours, lang=lang)
            finally:
                self.latencies.append(perf_counter() - started)
        original = extraction.calibration
        extraction.calibration = types.SimpleNamespace(classify=self._classify,
                                                       ModelUnavailable=calibration.ModelUnavailable)
        try:
            return super().decide(text, neighbours, lang=lang)
        finally:
            extraction.calibration = original
            self.latencies.append(perf_counter() - started)


def constant_decision(label="APPEND"):
    """A fake stage-3 model that always answers `label`, for tests and dry runs."""
    def classify(prompt, labels, **_):
        others = [x for x in labels if x != label]
        return {"label": label, "confidence": 1., "margin": 1., "runner_up": others[0] if others else label,
                "probs": {x: float(x == label) for x in labels}, "emitted": label, "valid": True,
                "latency_s": 0.}
    return classify


class CachedEmbedder:
    """One embedder, memoised per (kind, text). Exact for e5 because ARIES embeds
    one sequence per graph call (see `embedding.OnnxE5.encode`), so a vector is a
    function of its text alone; it lets the gated and cascade variants share
    the embedding cost within a run."""

    def __init__(self, inner):
        self.inner, self.name, self._memo = inner, inner.name, {}
        self.seconds = 0.

    @property
    def dim(self):
        return self.inner.dim

    def _get(self, kind, text):
        key = (kind, text)
        if key not in self._memo:
            started = perf_counter()
            self._memo[key] = self.inner.encode([text], kind=kind)[0]
            self.seconds += perf_counter() - started
        return self._memo[key]

    def passages(self, texts):
        return np.stack([self._get("passage", t) for t in texts])

    def query(self, text):
        return self._get("query", text)


# ── storing a conversation ───────────────────────────────────────────────────

def build(variant, conversation, embedder=None, cascade=None, excluded=()):
    """Offer every turn to one variant. Returns (rows, statistics).

    Each row carries `sources`: the dialogue ids it stands for. A turn the
    cascade judges NOOP ("already stored") is merged into the neighbour it
    duplicated — its id is appended to that row's sources and the row's recency
    is refreshed, which is what `store.observe` does on NOOP.

    SUPERSEDE keeps both rows, as the current store does: `store.arbitrate`
    never expires a USER statement, and `withdrawn_sources` is empty, so the
    contradicted utterance stays retrievable. One row stands for the
    utterance/conclusion pair, as in `memory_eval.build`.
    """
    spec = VARIANTS[variant]
    semantic = spec["rank"] in ("semantic-v3", "cosine", "rrf")
    if semantic and embedder is None:
        raise ValueError(f"{variant} needs an embedder")
    if spec["store"] == "cascade" and cascade is None:
        raise ValueError(f"{variant} needs a cascade")
    cache = vectors.VectorCache(embedder.dim) if semantic else None
    rows, by_id = [], {}
    counts = Counter()
    calls_before = cascade.calls if cascade is not None else 0
    for turn in conversation["turns"]:
        counts["offered"] += 1
        if spec["store"] in ("gated", "cascade"):
            # Stage 1 judges what was SAID, without the speaker label LoCoMo adds,
            # because its command/question patterns are anchored at the start.
            refused = extraction.gate(turn["content"], excluded=excluded)
            if refused is not None:
                counts["gate_refused"] += 1
                counts[f"gate: {_reason(refused.reason)}"] += 1
                continue
        text = turn["text"]
        vector = embedder.passages([text])[0] if semantic else None
        kind = extraction.classify_kind(text)
        if spec["store"] == "cascade":
            neighbours = [(rid, score, by_id[rid]["text"]) for rid, score in cache.search(vector, limit=5)]
            verdict = cascade.run(text, neighbours, excluded=excluded)
            counts[f"{verdict.stage}: {verdict.action}"] += 1
            if verdict.stage == "novelty" and verdict.reason.startswith("no local model"):
                counts["model_unavailable_fallback"] += 1
            if verdict.action == "NOOP":
                target = by_id.get(verdict.related_to)
                if target is not None:
                    target["sources"].append(turn["dia_id"])
                    target["last_retrieved_at"] = turn["at"]
                    counts["merged"] += 1
                continue
            if verdict.action == "ABORT":
                continue
            if verdict.action == "SUPERSEDE":
                counts["supersede_kept_both"] += 1
            kind = verdict.kind
        row = {"id": f"r{len(rows)}", "sources": [turn["dia_id"]], "text": text, "kind": kind,
               "layer": 60, "importance": IMPORTANCE.get(kind, .5),
               "created_at": turn["at"], "valid_at": turn["at"], "last_retrieved_at": None,
               "vector": vector}
        rows.append(row)
        by_id[row["id"]] = row
        if cache is not None:
            cache.add(row["id"], vector)
    counts["stored"] = len(rows)
    if cascade is not None:
        counts["model_calls"] = cascade.calls - calls_before
    return rows, counts


def _reason(text):
    """Collapse a gate rationale to its class ('matches excluded topic X' -> 'excluded topic')."""
    for needle, label in (("shorter", "too short"), ("longer", "too long"), ("excluded", "excluded topic"),
                          ("credential", "credential"), ("instruction", "command"),
                          ("question", "question"), ("remember_conversations", "privacy off")):
        if needle in text:
            return label
    return text


# ── ranking ──────────────────────────────────────────────────────────────────

_WORD = re.compile(r"\w+")


def tokens(text):
    return _WORD.findall((text or "").casefold())


class BM25:
    """Okapi BM25 over the stored rows. Ties keep storage order."""

    def __init__(self, rows, k1=1.2, b=.75):
        self.rows, self.k1, self.b = rows, k1, b
        self.docs = [Counter(tokens(r["text"])) for r in rows]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avgdl = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {w: np.log(1 + (n - f + .5) / (f + .5)) for w, f in df.items()}

    def top(self, query, k=K):
        terms = tokens(query)
        scored = []
        for position, (doc, length) in enumerate(zip(self.docs, self.lengths)):
            score = 0.
            for w in terms:
                tf = doc.get(w)
                if tf:
                    score += self.idf[w] * tf * (self.k1 + 1) / (
                        tf + self.k1 * (1 - self.b + self.b * length / self.avgdl))
            if score > 0:
                scored.append((-score, position))
        scored.sort()
        return [self.rows[p] for _, p in scored[:k]]


def ranker(variant, rows, now, embedder=None):
    """A function question -> top-K rows for this variant."""
    rank = VARIANTS[variant]["rank"]
    if rank == "bm25":
        index = BM25(rows)
        return index.top
    if rank in ("semantic-v3", "cosine", "rrf") and any(r["vector"] is None for r in rows):
        raise ValueError("semantic-v3 over an unembedded row would silently degrade to focused-v2")
    if rank in ("cosine", "rrf"):
        # Ablations of semantic-v3: the similarity alone, with no recency, importance or layer term.
        matrix = np.stack([r["vector"] for r in rows]) if rows else None

        def top_similarity(question, k=K):
            cosine = (matrix @ embedder.query(question)).tolist()
            score = cosine if rank == "cosine" else retrieval.rrf(
                (cosine, False), (retrieval.bm25_scores(question, [r["text"] for r in rows]), True))
            order = sorted(range(len(rows)), key=lambda i: (-score[i], i))
            return [rows[i] for i in order[:k]]
        return top_similarity

    def top(question, k=K):
        query_vector = embedder.query(question) if rank == "semantic-v3" else None
        scored = retrieval.score_memories(rows, question, rank, now=now, query_vector=query_vector, limit=k)
        return [row for _, row, _ in scored]
    return top


# ── scoring ──────────────────────────────────────────────────────────────────

def score_item(selected, evidence):
    """hit@k, reciprocal rank and evidence recall for one item's top-K rows."""
    wanted = set(evidence)
    rank = next((i + 1 for i, row in enumerate(selected) if wanted & set(row["sources"])), None)
    covered = wanted & {s for row in selected for s in row["sources"]}
    outcome = {f"hit@{k}": float(rank is not None and rank <= k) for k in CUTS}
    outcome["mrr"] = 1. / rank if rank else 0.
    outcome["recall@5"] = len(covered) / len(wanted)
    return outcome


METRICS = tuple(f"hit@{k}" for k in CUTS) + ("mrr", "recall@5")


def evaluate_conversation(variant, conversation, embedder=None, cascade=None):
    started = perf_counter()
    rows, counts = build(variant, conversation, embedder=embedder, cascade=cascade)
    built = perf_counter() - started
    top = ranker(variant, rows, conversation["now"], embedder=embedder)
    stored_ids = {s for r in rows for s in r["sources"]}
    outcomes = []
    for item in conversation["items"]:
        if item["excluded"]:
            continue
        result = score_item(top(item["question"]), item["evidence"])
        result.update(conversation=item["conversation"], index=item["index"], category=item["category"],
                      gold_storable=float(bool(set(item["evidence"]) & stored_ids)))
        outcomes.append(result)
    counts["evidence_turns_not_stored"] = len(
        {e for i in conversation["items"] if not i["excluded"] for e in i["evidence"]} - stored_ids)
    return outcomes, counts, {"build_s": built, "total_s": perf_counter() - started}


def _arrays(outcomes, metric):
    return (np.array([o[metric] for o in outcomes], dtype=float),
            np.array([o["conversation"] for o in outcomes]))


def bootstrap_item(values, groups, b=BOOTSTRAP, seed=SEED):
    """Resample items with replacement WITHIN each conversation (stratified)."""
    rng = np.random.default_rng(seed)
    total = np.zeros(b)
    for g in np.unique(groups):
        v = values[groups == g]
        total += v[rng.integers(0, len(v), (b, len(v)))].sum(axis=1)
    return total / len(values)


def bootstrap_cluster(values, groups, b=BOOTSTRAP, seed=SEED):
    """Resample whole conversations with replacement; ratio of sums."""
    rng = np.random.default_rng(seed)
    labels = np.unique(groups)
    sums = np.array([values[groups == g].sum() for g in labels])
    sizes = np.array([(groups == g).sum() for g in labels], dtype=float)
    pick = rng.integers(0, len(labels), (b, len(labels)))
    return sums[pick].sum(axis=1) / sizes[pick].sum(axis=1)


def interval(draws):
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return [round(float(lo), 4), round(float(hi), 4)]


def summarise(values, groups, b=BOOTSTRAP, seed=SEED):
    return {"mean": round(float(values.mean()), 4),
            "ci95_item_within_conversation": interval(bootstrap_item(values, groups, b, seed)),
            "ci95_conversation_cluster": interval(bootstrap_cluster(values, groups, b, seed))}


GROUPS = {"all": (1, 2, 3, 4, 5), "non-adversarial (1-4)": (1, 2, 3, 4),
          **{f"{c} {name}": (c,) for c, name in CATEGORIES.items()}}


def aggregate(outcomes, b=BOOTSTRAP, seed=SEED):
    """Every metric, overall and per category, with both bootstrap intervals."""
    report = {}
    for name, cats in GROUPS.items():
        subset = [o for o in outcomes if o["category"] in cats]
        if not subset:
            continue
        entry = {"n": len(subset), "conversations": len({o["conversation"] for o in subset})}
        for metric in METRICS + ("gold_storable",):
            entry[metric] = summarise(*_arrays(subset, metric), b=b, seed=seed)
        report[name] = entry
    return report


def paired(candidate, baseline, b=BOOTSTRAP, seed=SEED):
    """candidate minus baseline, item by item, for every metric and group."""
    base = {(o["conversation"], o["index"]): o for o in baseline}
    pairs = [(o, base[(o["conversation"], o["index"])]) for o in candidate
             if (o["conversation"], o["index"]) in base]
    report = {}
    for name, cats in GROUPS.items():
        subset = [(c, a) for c, a in pairs if c["category"] in cats]
        if not subset:
            continue
        groups = np.array([c["conversation"] for c, _ in subset])
        entry = {"n": len(subset)}
        for metric in METRICS:
            diff = np.array([c[metric] - a[metric] for c, a in subset])
            entry[metric] = summarise(diff, groups, b=b, seed=seed)
        mc = paired_statistics([bool(a["hit@5"]) for _, a in subset], [bool(c["hit@5"]) for c, _ in subset])
        entry["hit@5_mcnemar"] = {k: mc[k] for k in ("improved", "regressed", "exact_mcnemar_two_sided_p")}
        report[name] = entry
    return report


# ── census: what reaches each stage, without any model ───────────────────────

def census(conversations):
    """Turns offered, refused by stage 1, and passed on — no embedder needed.

    Every gate-passed turn except the first of each conversation has at least
    one neighbour, so (passed - conversations) is a hard UPPER bound on how
    many stage-3 calls the cascade could make.
    """
    total, reasons, passed, evidence_refused = 0, Counter(), 0, 0
    evidence = {(c["number"], e) for c in conversations for i in c["items"] if not i["excluded"]
                for e in i["evidence"]}
    for c in conversations:
        for turn in c["turns"]:
            total += 1
            refused = extraction.gate(turn["content"])
            if refused is None:
                passed += 1
            else:
                reasons[_reason(refused.reason)] += 1
                evidence_refused += (c["number"], turn["dia_id"]) in evidence
    items = [i for c in conversations for i in c["items"]]
    return {"conversations": len(conversations), "turns": total, "gate_passed": passed,
            "gate_refused": dict(reasons), "stage3_call_upper_bound": passed - len(conversations),
            "evidence_turns": len(evidence), "evidence_turns_refused_by_gate": evidence_refused,
            "qa_items": len(items),
            "qa_excluded": dict(Counter(i["excluded"] for i in items if i["excluded"])),
            "qa_by_category": {CATEGORIES[k]: v for k, v in sorted(Counter(i["category"] for i in items).items())},
            "evidence_ids_malformed_entries": sum(i["malformed"] for i in items),
            "evidence_ids_absent_from_conversation": sum(i["evidence_absent"] for i in items)}


# ── the run ──────────────────────────────────────────────────────────────────

def implementation_sha256():
    from aries.workspace.memory import store
    files = [Path(__file__)] + [Path(m.__file__) for m in (retrieval, extraction, vectors, embedding,
                                                           calibration, store)]
    return hashlib.sha256(b"\0".join(f.read_bytes() for f in files)).hexdigest()


def run(conversations, variants, *, embedder_factory=None, classify=None, b=BOOTSTRAP, seed=SEED,
        log=print):
    """Evaluate `variants` on `conversations`. bm25 is always included, because
    every paired difference is against it and no per-item outcome is written to
    disk to pair with later."""
    variants = list(dict.fromkeys([BASELINE] + list(variants)))
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        raise SystemExit(f"unknown variant(s) {unknown}; have {sorted(VARIANTS)}")
    embedder_factory = embedder_factory or embedding.get
    embedders, outcomes, results = {}, {}, {}
    for variant in variants:
        spec = VARIANTS[variant]
        embedder = None
        if spec["embedder"]:
            if spec["embedder"] not in embedders:
                started = perf_counter()
                embedders[spec["embedder"]] = CachedEmbedder(embedder_factory(spec["embedder"]))
                log(f"loaded {spec['embedder']} in {perf_counter() - started:.1f}s")
            embedder = embedders[spec["embedder"]]
        started, embed_before = perf_counter(), embedder.seconds if embedder else 0.
        counts, per, latencies = Counter(), [], []
        saved = {k: os.environ.get(k) for k in spec.get("flags", {})}
        os.environ.update(spec.get("flags", {}))
        for conversation in conversations:
            cascade = InjectableCascade(classify=classify) if spec["store"] == "cascade" else None
            got, c, timing = evaluate_conversation(variant, conversation, embedder=embedder, cascade=cascade)
            per.extend(got)
            counts.update(c)
            if cascade is not None:
                latencies.extend(cascade.latencies)
            log(f"{variant:24s} conv {conversation['sample_id']:>8s}  stored {c['stored']:4d}  "
                f"items {len(got):4d}  calls {c.get('model_calls', 0):4d}  {timing['total_s']:.1f}s")
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        wall = perf_counter() - started
        outcomes[variant] = per
        results[variant] = {
            "spec": spec, "embedder": embedder.name if embedder else None,
            "metrics": aggregate(per, b=b, seed=seed),
            "per_conversation_hit@5": {conversations[i]["sample_id"]: round(float(np.mean(
                [o["hit@5"] for o in per if o["conversation"] == conversations[i]["number"]])), 4)
                for i in range(len(conversations))
                if any(o["conversation"] == conversations[i]["number"] for o in per)},
            "counts": dict(sorted(counts.items())),
            "stored_rows": counts["stored"], "offered_turns": counts["offered"],
            "llm_calls": counts.get("model_calls", 0) if spec["store"] == "cascade" else 0,
            "model_unavailable_fallbacks": counts.get("model_unavailable_fallback", 0),
            "decision_latency_median_s": round(float(np.median(latencies)), 4) if latencies else None,
            "embedding_s": round((embedder.seconds - embed_before) if embedder else 0., 2),
            "wall_s": round(wall, 2),
        }
        if results[variant]["model_unavailable_fallbacks"]:
            results[variant]["INVALID"] = ("the local model did not answer for some stage-3 calls; "
                                           "those turns were kept on cosine alone — this is not the cascade")
    comparisons = {f"{v} - {BASELINE}": paired(outcomes[v], outcomes[BASELINE], b=b, seed=seed)
                   for v in variants if v != BASELINE}
    for v in ("hybrid-rrf-e5", "cosine-only-e5", "rrf-only-e5", "hybrid-similarity-e5"):
        if v in outcomes and "embedding-only-e5" in outcomes:
            comparisons[f"{v} - embedding-only-e5"] = paired(outcomes[v], outcomes["embedding-only-e5"], b=b, seed=seed)
    for v in variants:
        if v.startswith("cascade-"):
            other = "embedding-only-" + v.split("-", 1)[1]
            if other in outcomes:
                comparisons[f"{v} - {other}"] = paired(outcomes[v], outcomes[other], b=b, seed=seed)
    return {"variants": results, "comparisons": comparisons}


def output_path(directory=RESULTS, stem="locomo"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for n in range(1000):
        path = directory / (f"{stem}-{stamp}.json" if n == 0 else f"{stem}-{stamp}-{n}.json")
        try:
            with open(path, "x"):
                return path
        except FileExistsError:
            continue
    raise SystemExit("could not find a fresh result filename")


class HashEmbedder:
    """Deterministic bag-of-words hashing into unit vectors. NOT a model: it
    exists so the semantic code path can be exercised without loading one."""

    def __init__(self, dim=256):
        self.dim, self.name = dim, f"hash-bow-{dim}"

    def encode(self, texts, *, kind):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for w in tokens(text):
                out[row, int(hashlib.md5(w.encode()).hexdigest()[:8], 16) % self.dim] += 1.
            out[row, 0] += 1e-3                      # never the zero vector
        return out / np.linalg.norm(out, axis=1, keepdims=True)

    def query(self, text):
        return self.encode([text], kind="query")[0]

    def passages(self, texts):
        return self.encode(list(texts), kind="passage")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--variants", default="bm25",
                        help=f"comma-separated, from {','.join(VARIANTS)} (bm25 is always added)")
    parser.add_argument("--data", default=str(DATA))
    parser.add_argument("--out-dir", default=str(RESULTS))
    parser.add_argument("--conversations", default="", help="comma-separated indices 0-9; default all")
    parser.add_argument("--bootstrap", type=int, default=BOOTSTRAP)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--dry-run-calls", action="store_true",
                        help="replace the stage-3 model with a constant APPEND and count the calls it "
                             "WOULD have received; the embedder is still the real one")
    parser.add_argument("--fake-embedder", action="store_true",
                        help="hashing bag-of-words instead of a model (smoke tests only; results are "
                             "marked synthetic)")
    args = parser.parse_args(argv)

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    conversations = load(args.data)
    if args.conversations:
        keep = {int(x) for x in args.conversations.split(",")}
        conversations = [c for c in conversations if c["number"] in keep]
    classify = constant_decision("APPEND") if (args.dry_run_calls or args.fake_embedder) else None
    factory = (lambda name: HashEmbedder()) if args.fake_embedder else None
    synthetic = args.dry_run_calls or args.fake_embedder

    started = datetime.now(timezone.utc)
    clock = perf_counter()
    result = run(conversations, variants, embedder_factory=factory, classify=classify,
                 b=args.bootstrap, seed=args.seed)
    payload = {
        "benchmark": "LoCoMo (locomo10.json), retrieval scored against annotated evidence turns",
        "citation": 'Maharana et al., "Evaluating Very Long-Term Conversational Memory of LLM Agents", ACL 2024',
        "license": "CC BY-NC 4.0", "data_sha256": DATA_SHA256,
        "implementation_sha256": implementation_sha256(),
        "synthetic": {"fake_embedder": args.fake_embedder, "constant_decision": classify is not None}
                     if synthetic else False,
        "started_utc": started.isoformat(), "wall_s": round(perf_counter() - clock, 2),
        "environment": {"openblas_num_threads": os.environ.get("OPENBLAS_NUM_THREADS"),
                        "python": sys.version.split()[0], "numpy": np.__version__,
                        "nice": os.nice(0)},
        "bootstrap": {"replicates": args.bootstrap, "seed": args.seed,
                      "item": "items resampled with replacement within each conversation",
                      "cluster": "conversations resampled with replacement (ratio of sums)"},
        "category_names": {str(k): v for k, v in CATEGORIES.items()},
        "census": census(conversations), "parameters": DEFAULTS, "k": K,
        **result,
    }
    path = output_path(args.out_dir, "locomo-dryrun" if args.dry_run_calls else
                       ("locomo-synthetic" if args.fake_embedder else "locomo"))
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str) + "\n")
    print(f"wrote {path}")
    return payload


if __name__ == "__main__":
    main()
