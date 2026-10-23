"""MIND-small dev evaluation of ARIES's interest matching, diversity and learning.

Every system ranks the candidates of each dev impression; labels come from the
`-1`/`-0` suffixes. All design decisions are listed in NOTES.md and in the
PARAMS dict written into every result file. Nothing here is tuned on dev.

ARIES code is imported, not reimplemented:
  aries.interests.matching   Matchable.build, score, normalise
  aries.news.selection       diverse
  aries.learning.statistics  wilson, step_toward
  aries.learning.settings    default values of the learning.* settings
The decision rule of aries.learning.loop.propose() (ordinary path) is mirrored
in `LearningUser.update`, because propose() itself reads a database.

Usage:
  nice -n 19 .venv/bin/python experiments/iis/real-data/mind/mind_eval.py \
      --data ~/data-ext/mind [--limit N] [--out FILE] [--embedding --embedding-cache DIR]
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
for _p in (ROOT / "vendor" / "agentic-core", ROOT / "vendor", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from aries.interests.matching import Matchable, normalise, score  # noqa: E402
from aries.learning.statistics import step_toward, wilson  # noqa: E402
from aries.news.selection import diverse, mmr  # noqa: E402  (imports sqlalchemy + ORM models; no connection)
from aries.learning.statistics import relative_thresholds  # noqa: E402
import aries.learning.settings  # noqa: E402,F401  registers learning.* defaults
from aries.settings.schema import require as _setting  # noqa: E402
from aries.learning.history import LOOKBACK  # noqa: E402

ZIP_SHA256 = {
    "MINDsmall_train.zip": "6ef97a271580b98ccfc4301ada55cc639423cb0576a78b8dcfcf74a4dbcc3194",
    "MINDsmall_dev.zip": "d6ce515dcaa6b6d47ddf0a326eebc8a31b84735ae410285c9882ca2a06eec669",
}

LEARN = {k: _setting(f"learning.{k}").default for k in (
    "min_observations", "engaged_threshold", "ignored_threshold", "max_step",
    "max_reversals", "damping", "window_days", "interval_hours")}

SEED = 20261022
BOOTSTRAP_REPLICATES = 1000
BM25_K1, BM25_B = 1.2, 0.75
TIME_FMT = "%m/%d/%Y %I:%M:%S %p"
FIELD_SEP = " | "        # non-word, non-space: a phrase term cannot match across fields
METRICS = ("auc", "mrr", "ndcg5", "ndcg10")
TOKEN = re.compile(r"\w+")


# ── data ────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class News:
    nid: str
    category: str
    subcategory: str
    title: str
    entities: list[str]

    @property
    def text(self) -> str:
        """Candidate text for interest matching."""
        return FIELD_SEP.join([self.category, self.subcategory, self.title, *self.entities])

    def topics(self) -> list[str]:
        """Normalised topic keys this item carries, de-duplicated, in field order."""
        out, seen = [], set()
        for raw in (self.category, self.subcategory, *self.entities):
            k = normalise(raw)
            if k and k not in seen:
                seen.add(k)
                out.append(k)
        return out


@dataclasses.dataclass
class Impression:
    iid: int
    user: str
    time: float          # POSIX seconds (MIND times carry no zone; read as UTC)
    history: list[str]
    candidates: list[str]
    labels: np.ndarray   # int8


def parse_time(s: str) -> float:
    return datetime.strptime(s, TIME_FMT).replace(tzinfo=timezone.utc).timestamp()


def load_news(paths) -> tuple[dict[str, News], int]:
    """Union of news.tsv files. First occurrence wins; conflicting rows are counted."""
    news, conflicts = {}, 0
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                cols = line.rstrip("\n").split("\t")
                nid, cat, sub, title = cols[0], cols[1], cols[2], cols[3]
                ents = []
                if len(cols) > 6 and cols[6]:
                    try:
                        ents = [e["Label"] for e in json.loads(cols[6]) if e.get("Label")]
                    except (ValueError, TypeError):
                        ents = []
                item = News(nid, cat, sub, title, ents)
                if nid in news:
                    old = news[nid]
                    if (old.category, old.subcategory, old.title) != (cat, sub, title):
                        conflicts += 1
                    continue
                news[nid] = item
    return news, conflicts


def load_behaviors(path) -> list[Impression]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            iid, user, t, hist, imps = line.rstrip("\n").split("\t")
            cands, labels = [], []
            for tok in imps.split():
                nid, lab = tok.rsplit("-", 1)
                cands.append(nid)
                labels.append(int(lab))
            out.append(Impression(int(iid), user, parse_time(t), hist.split(),
                                  cands, np.array(labels, dtype=np.int8)))
    return out


# ── metrics (MIND definitions: msnews.github.io evaluate.py) ────────────────

def average_ranks(x: np.ndarray) -> np.ndarray:
    """1-based ranks, ties receive the mean of the ranks they span."""
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ranks = np.empty(len(x), dtype=float)
    i = 0
    n = len(x)
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def auc(labels, scores) -> float | None:
    """ROC AUC with ties counted as one half (Mann-Whitney with average ranks).
    None when the impression has no positive or no negative."""
    labels = np.asarray(labels)
    pos = int((labels == 1).sum())
    neg = len(labels) - pos
    if pos == 0 or neg == 0:
        return None
    r = average_ranks(scores)
    return float((r[labels == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def ranking(scores, tiebreak) -> np.ndarray:
    """Candidate indices best first: higher score first, ties by smaller tiebreak."""
    return np.lexsort((np.asarray(tiebreak), -np.asarray(scores, dtype=float)))


def mrr(labels_in_order) -> float | None:
    """MIND MRR: mean over ALL clicked items of 1/rank (sum(y/rank)/sum(y))."""
    y = np.asarray(labels_in_order, dtype=float)
    if y.sum() == 0:
        return None
    return float((y / np.arange(1, len(y) + 1)).sum() / y.sum())


def dcg(labels_in_order, k: int) -> float:
    y = np.asarray(labels_in_order, dtype=float)[:k]
    return float(((2 ** y - 1) / np.log2(np.arange(len(y)) + 2)).sum())


def ndcg(labels_in_order, k: int) -> float | None:
    y = np.asarray(labels_in_order, dtype=float)
    ideal = dcg(np.sort(y)[::-1], k)
    if ideal == 0:
        return None
    return dcg(y, k) / ideal


def impression_metrics(labels, order, auc_scores) -> dict:
    """`order` gives the ranked list for MRR/nDCG; `auc_scores` the scores for AUC."""
    y = np.asarray(labels)[order]
    return {"auc": auc(labels, auc_scores), "mrr": mrr(y), "ndcg5": ndcg(y, 5), "ndcg10": ndcg(y, 10)}


def tiebreak_for(iid: int, candidates) -> np.ndarray:
    """A fixed pseudo-random tie-break per (impression, item), identical for every system."""
    return np.array([zlib.crc32(f"{SEED}:{iid}:{nid}".encode()) for nid in candidates], dtype=np.int64)


# ── ARIES interest profile ──────────────────────────────────────────────────

_TEMPLATE: dict[str, Matchable] = {}


def _matchable(key: str, weight: float) -> Matchable:
    """Matchable.build once per topic key (regex compile), then a copy per user.
    The copy shares the immutable Term list and differs only in weight."""
    m = _TEMPLATE.get(key)
    if m is None:
        m = _TEMPLATE[key] = Matchable.build(key, [], 1.0, source="user")
    return dataclasses.replace(m, weight=weight)


def static_weights(history, news) -> dict[str, float]:
    """Weight of a topic = share of history items (found in news.tsv) carrying it."""
    counts = Counter()
    n = 0
    for nid in history:
        item = news.get(nid)
        if item is None:
            continue
        n += 1
        counts.update(item.topics())
    if n == 0:
        return {}
    return {k: c / n for k, c in counts.items()}


def term_tokens(m: Matchable) -> list[frozenset]:
    return [frozenset(TOKEN.findall(t.text)) for t in m.terms]


class Profile:
    """One user's interests as ARIES Matchables, plus an exact pre-filter.

    The pre-filter only decides which Matchables are PASSED to matching.score;
    score itself does all matching. It is exact: a word-boundary match of a term
    requires every \\w+ run of the term to be a whole \\w+ token of the text, so a
    Matchable whose term tokens are not all present cannot match and contributes
    nothing to the noisy-OR. Order is preserved, so `matched` is unchanged.
    """

    def __init__(self, weights: dict[str, float]):
        # Deterministic order: weight descending, then key. score() sorts matched
        # topics by weight with a stable sort, so this order decides the primary
        # topic among equal weights.
        keys = sorted(weights, key=lambda k: (-weights[k], k))
        self.matchables = [_matchable(k, weights[k]) for k in keys]
        self.index: dict[str, list[int]] = defaultdict(list)
        self.required: list[list[frozenset]] = []
        for i, m in enumerate(self.matchables):
            req = term_tokens(m)
            self.required.append(req)
            for toks in req:
                for tok in toks:
                    self.index[tok].append(i)

    def subset(self, text_tokens: frozenset) -> list[int]:
        hit = set()
        for tok in text_tokens:
            for i in self.index.get(tok, ()):
                if i not in hit and any(req <= text_tokens for req in self.required[i]):
                    hit.add(i)
        return sorted(hit)


def primary_topic(rel) -> list[str]:
    return [m["topic"] for m in rel.matched][:1]


# ── ARIES learning loop, ordinary path of loop.propose() ────────────────────

@dataclasses.dataclass
class TopicState:
    shown: int = 0
    clicked: int = 0
    learned: float | None = None
    changes: list = dataclasses.field(default_factory=list)   # [(direction, is_reversal)]

    def stability(self, max_reversals: int, damping_base: float):
        """As aries.learning.history.stability: the last LOOKBACK changes decide."""
        rows = self.changes[-LOOKBACK:]
        if not rows:
            return False, 1.0
        reversals = sum(1 for _, rev in rows if rev)
        return reversals >= max_reversals, damping_base ** reversals


def learning_step(state: TopicState, base: float, cfg=LEARN) -> dict | None:
    """One pass of the ordinary path for one topic. Returns the change or None.

    Mirrors loop.propose(): frozen -> skip; shown < min_observations -> skip;
    Wilson lower >= engaged -> toward 1 with confidence (lower-engaged)/(1-engaged);
    upper <= ignored -> toward 0 with confidence (ignored-upper)/ignored; step capped
    at max_step * damping**reversals; changes under 0.005 are dropped.
    """
    frozen, damping = state.stability(int(cfg["max_reversals"]), float(cfg["damping"]))
    if frozen or state.shown < int(cfg["min_observations"]):
        return None
    iv = wilson(state.clicked, state.shown)
    eng, ign = float(cfg["engaged_threshold"]), float(cfg["ignored_threshold"])
    if iv.lower >= eng:
        target, direction = 1.0, "up"
        confidence = min(1.0, (iv.lower - eng) / max(0.01, 1 - eng))
    elif iv.upper <= ign:
        target, direction = 0.0, "down"
        confidence = min(1.0, (ign - iv.upper) / max(0.01, ign))
    else:
        return None
    proposed = step_toward(base, target, confidence=confidence, max_step=float(cfg["max_step"]) * damping)
    if abs(proposed - base) < 0.005:
        return None
    last = state.changes[-1][0] if state.changes else None
    state.changes.append((direction, last is not None and last != direction))
    state.learned = proposed
    return {"direction": direction, "from": base, "to": proposed}


class LearningUser:
    """Per-user learned layer over the static profile."""

    def __init__(self, profile: Profile, static: dict[str, float], relative: bool = False):
        self.static, self.relative = static, relative
        self.profile = Profile.__new__(Profile)
        self.profile.index, self.profile.required = profile.index, profile.required
        self.profile.matchables = [dataclasses.replace(m) for m in profile.matchables]
        self.pos = {m.key: i for i, m in enumerate(self.profile.matchables)}
        self.state: dict[str, TopicState] = {}
        self.changes = 0

    def update(self, matched_per_candidate: list[list[str]], labels) -> None:
        """After the impression has been scored: count evidence, then one pass
        over the topics whose evidence changed (the source-digest guard in
        loop.apply refuses to re-apply unchanged evidence)."""
        touched = set()
        for topics, y in zip(matched_per_candidate, labels):
            for k in topics:
                st = self.state.setdefault(k, TopicState())
                st.shown += 1
                st.clicked += int(y)
                touched.add(k)
        cfg = LEARN
        if self.relative:
            # ARIES_LEARNING_RELATIVE_CTR, as loop.propose() applies it: bars from this user's pooled rate.
            eng, ign = relative_thresholds(sum(s.clicked for s in self.state.values()),
                                           sum(s.shown for s in self.state.values()),
                                           float(LEARN["engaged_threshold"]), float(LEARN["ignored_threshold"]))
            cfg = {**LEARN, "engaged_threshold": eng, "ignored_threshold": ign}
        for k in sorted(touched):
            st = self.state[k]
            base = st.learned if st.learned is not None else self.static[k]
            if learning_step(st, base, cfg) is not None:
                self.profile.matchables[self.pos[k]].weight = st.learned
                self.changes += 1


# ── text baselines ──────────────────────────────────────────────────────────

def tokens(text: str) -> list[str]:
    return TOKEN.findall(normalise(text))


class TextIndex:
    def __init__(self, news: dict[str, News]):
        self.tok = {nid: tokens(n.title) for nid, n in news.items()}
        df = Counter()
        for t in self.tok.values():
            df.update(set(t))
        self.N = len(self.tok)
        self.idf_tfidf = {w: math.log((1 + self.N) / (1 + d)) + 1 for w, d in df.items()}
        self.idf_bm25 = {w: math.log(1 + (self.N - d + 0.5) / (d + 0.5)) for w, d in df.items()}
        self.avgdl = None

    def user_doc(self, history) -> Counter:
        c = Counter()
        for nid in history:
            c.update(self.tok.get(nid, ()))
        return c

    def tfidf_vec(self, counts: Counter) -> dict:
        v = {w: tf * self.idf_tfidf.get(w, 0.0) for w, tf in counts.items()}
        n = math.sqrt(sum(x * x for x in v.values()))
        return {w: x / n for w, x in v.items()} if n else {}

    def tfidf(self, user_vec: dict, nid: str) -> float:
        cv = self.tfidf_vec(Counter(self.tok.get(nid, ())))
        return sum(x * user_vec.get(w, 0.0) for w, x in cv.items())

    def bm25(self, user_counts: Counter, user_len: int, nid: str) -> float:
        """Candidate title is the query, the user's concatenated history titles the document."""
        if not user_len:
            return 0.0
        norm = BM25_K1 * (1 - BM25_B + BM25_B * user_len / self.avgdl)
        s = 0.0
        for w in set(self.tok.get(nid, ())):
            tf = user_counts.get(w, 0)
            if tf:
                s += self.idf_bm25.get(w, 0.0) * tf * (BM25_K1 + 1) / (tf + norm)
        return s


# ── embedding baseline (not run by default) ─────────────────────────────────

class EmbeddingCache:
    """Title embeddings on disk, keyed by news id, OUTSIDE the repository.

    `embedder` needs `.name` and `.encode(texts, kind=...)` returning L2-normalised
    rows, which is the interface of aries.workspace.memory.embedding.
    """

    def __init__(self, directory, embedder, news: dict[str, News]):
        self.dir = Path(directory).expanduser()
        if ROOT in self.dir.resolve().parents or self.dir.resolve() == ROOT:
            raise ValueError("embedding cache must live outside the repository")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.embedder, self.news = embedder, news
        stem = re.sub(r"[^\w.-]", "_", embedder.name)
        self.ids_path, self.vec_path = self.dir / f"{stem}.ids.json", self.dir / f"{stem}.npy"
        self.row: dict[str, int] = {}
        self.mat = np.zeros((0, 0), dtype=np.float32)
        if self.ids_path.exists() and self.vec_path.exists():
            ids = json.loads(self.ids_path.read_text())
            self.mat = np.load(self.vec_path)
            self.row = {nid: i for i, nid in enumerate(ids)}

    def ensure(self, nids, *, batch=256, progress=None) -> None:
        missing = sorted({n for n in nids if n not in self.row and n in self.news})
        ids = [None] * len(self.row)
        for nid, i in self.row.items():
            ids[i] = nid
        parts = [self.mat] if len(self.row) else []
        for s in range(0, len(missing), batch):
            chunk = missing[s:s + batch]
            vec = np.asarray(self.embedder.encode([self.news[n].title for n in chunk], kind="query"),
                             dtype=np.float32)
            parts.append(vec)
            for n in chunk:
                self.row[n] = len(ids)
                ids.append(n)
            if progress:
                progress(len(ids))
        if missing:
            self.mat = np.vstack(parts)
            np.save(self.vec_path, self.mat)
            self.ids_path.write_text(json.dumps(ids))

    def vectors(self, nids) -> np.ndarray:
        return self.mat[[self.row[n] for n in nids if n in self.row]]


def embedding_scores(cache: EmbeddingCache, history, candidates) -> np.ndarray:
    """Cosine of the mean history-title embedding with each candidate title."""
    h = cache.vectors(history)
    if len(h) == 0:
        return np.zeros(len(candidates))
    u = h.mean(axis=0)
    n = np.linalg.norm(u)
    if n == 0:
        return np.zeros(len(candidates))
    c = cache.vectors(candidates)
    if len(c) != len(candidates):
        raise KeyError("candidate without a cached embedding")
    return (c @ (u / n)).astype(float)


# ── the run ─────────────────────────────────────────────────────────────────

SYSTEMS = ("aries-interests", "aries-interests+diverse", "aries-learning",
           "aries-interests+mmr", "aries-learning-relative",
           "random", "popular", "recent", "tfidf", "bm25")
# The +mmr and -relative systems were added after the 2026-10-22 results (ARIES_NEWS_DIVERSE_TOPK,
# ARIES_LEARNING_RELATIVE_CTR); they are exploratory and named as such in NOTES.md.
ARIES = ("aries-interests", "aries-interests+diverse", "aries-learning",
         "aries-interests+mmr", "aries-learning-relative")
BASELINES = ("random", "popular", "recent", "tfidf", "bm25")


def evaluate(train_beh, dev_beh, news, *, embed_cache=None, validate_pairs=20000, log=print,
             keep_scores=False):
    """Run every system over `dev_beh` in time order. Returns per-impression records."""
    systems = list(SYSTEMS) + (["embedding"] if embed_cache is not None else [])

    # popularity: click events from every impression log, consumed strictly before t
    clicks = sorted((imp.time, nid) for imp in (*train_beh, *dev_beh)
                    for nid, y in zip(imp.candidates, imp.labels) if y == 1)
    first_seen: dict[str, float] = {}
    for imp in (*train_beh, *dev_beh):
        for nid in imp.candidates:
            if imp.time < first_seen.get(nid, math.inf):
                first_seen[nid] = imp.time

    text = TextIndex(news)
    users_hist = {}
    for imp in dev_beh:
        users_hist.setdefault(imp.user, imp.history)
    lens = [sum(len(text.tok.get(n, ())) for n in h) for h in users_hist.values()]
    lens = [x for x in lens if x]
    text.avgdl = float(np.mean(lens)) if lens else 1.0

    cand_text, cand_tokens = {}, {}

    def ctext(nid):
        if nid not in cand_text:
            item = news.get(nid)
            cand_text[nid] = item.text if item else ""
            cand_tokens[nid] = frozenset(TOKEN.findall(normalise(cand_text[nid])))
        return cand_text[nid]

    order = sorted(dev_beh, key=lambda i: (i.time, i.iid))
    profiles, learners, relatives, user_docs = {}, {}, {}, {}
    pop, ptr = Counter(), 0
    records = []
    validation = {"pairs": 0, "mismatches": 0}
    history_variants = 0
    t0 = time.time()

    for n_imp, imp in enumerate(order):
        while ptr < len(clicks) and clicks[ptr][0] < imp.time:
            pop[clicks[ptr][1]] += 1
            ptr += 1

        key = (imp.user, tuple(imp.history))
        if key not in profiles:
            w = static_weights(imp.history, news)
            profiles[key] = (Profile(w), w)
        prof, w = profiles[key]
        if imp.user not in learners:
            learners[imp.user] = (LearningUser(prof, w), key)
            relatives[imp.user] = LearningUser(prof, w, relative=True)
        learner, lkey = learners[imp.user]
        relative = relatives[imp.user]
        if lkey != key:
            history_variants += 1      # never happens in MIND-small dev; counted to be sure

        tb = tiebreak_for(imp.iid, imp.candidates)
        nc = len(imp.candidates)
        s_static = np.zeros(nc)
        s_learn = np.zeros(nc)
        s_relative = np.zeros(nc)
        primary, matched_keys = [], []
        for j, nid in enumerate(imp.candidates):
            txt = ctext(nid)
            sub = prof.subset(cand_tokens[nid])
            rel = score(txt, [prof.matchables[i] for i in sub])
            s_static[j] = rel.score
            primary.append(primary_topic(rel))
            matched_keys.append([m["topic"] for m in rel.matched])
            s_learn[j] = score(txt, [learner.profile.matchables[i] for i in sub]).score
            s_relative[j] = score(txt, [relative.profile.matchables[i] for i in sub]).score
            if validation["pairs"] < validate_pairs:
                full = score(txt, prof.matchables)
                validation["pairs"] += 1
                if (full.score != rel.score or [m["topic"] for m in full.matched]
                        != [m["topic"] for m in rel.matched]):
                    validation["mismatches"] += 1

        rank_static = ranking(s_static, tb)
        div = diverse(list(rank_static), topics=lambda j: primary[j], source=lambda j: None,
                      limit=nc, per_source=0)
        div_order = np.array(div, dtype=np.int64)
        div_scores = np.empty(nc)
        div_scores[div_order] = -np.arange(nc, dtype=float)
        mmr_order = np.array(mmr(list(rank_static), relevance=lambda j: s_static[j], topics=lambda j: primary[j],
                                 source=lambda j: None, limit=nc, per_source=0), dtype=np.int64)
        mmr_scores = np.empty(nc)
        mmr_scores[mmr_order] = -np.arange(nc, dtype=float)

        rng = np.random.default_rng([SEED, imp.iid])
        s_rand = rng.random(nc)
        s_pop = np.array([pop.get(nid, 0) for nid in imp.candidates], dtype=float)
        s_rec = np.array([first_seen[nid] for nid in imp.candidates], dtype=float)

        if imp.user not in user_docs:
            c = text.user_doc(imp.history)
            user_docs[imp.user] = (c, sum(c.values()), text.tfidf_vec(c))
        ucounts, ulen, uvec = user_docs[imp.user]
        s_tfidf = np.array([text.tfidf(uvec, nid) for nid in imp.candidates])
        s_bm25 = np.array([text.bm25(ucounts, ulen, nid) for nid in imp.candidates])

        scores = {"aries-interests": s_static, "aries-learning": s_learn,
                  "aries-learning-relative": s_relative, "random": s_rand,
                  "popular": s_pop, "recent": s_rec, "tfidf": s_tfidf, "bm25": s_bm25}
        if embed_cache is not None:
            scores["embedding"] = embedding_scores(embed_cache, imp.history, imp.candidates)
        rec = {"iid": imp.iid, "user": imp.user, "time": imp.time,
               "empty_history": len(imp.history) == 0,
               "n_cand": nc, "n_pos": int(imp.labels.sum())}
        for name, s in scores.items():
            rec[name] = impression_metrics(imp.labels, rank_static if name == "aries-interests"
                                           else ranking(s, tb), s)
        rec["aries-interests+diverse"] = impression_metrics(imp.labels, div_order, div_scores)
        rec["aries-interests+mmr"] = impression_metrics(imp.labels, mmr_order, mmr_scores)
        if keep_scores:     # tests only; never written to a result file
            rec["scores"] = {k: [float(x) for x in v] for k, v in scores.items()}
            rec["diverse_order"] = [imp.candidates[j] for j in div_order]
        records.append(rec)

        # prequential: the learner sees this impression's outcome only now
        learner.update(matched_keys, imp.labels)
        relative.update(matched_keys, imp.labels)

        if log and (n_imp + 1) % 5000 == 0:
            log(f"  {n_imp + 1}/{len(order)} impressions, {time.time() - t0:.0f}s")

    extra = {"prefilter_validation": validation, "history_variants": history_variants,
             "learning_changes": int(sum(l.changes for l, _ in learners.values())),
             "learning_relative_changes": int(sum(l.changes for l in relatives.values())),
             "learning_relative_users_changed": int(sum(1 for l in relatives.values() if l.changes)),
             "learning_users_changed": int(sum(1 for l, _ in learners.values() if l.changes)),
             "profile_topics_mean": float(np.mean([len(p.matchables) for p, _ in profiles.values()])),
             "bm25_avgdl": text.avgdl, "news_items": len(news), "systems": systems}
    return records, extra


# ── aggregation and bootstrap ───────────────────────────────────────────────

def per_user_sums(records, systems, users):
    """S[sys][metric]: (U,) sums; N[metric]: (U,) counts (labels decide validity)."""
    uidx = {u: i for i, u in enumerate(users)}
    U = len(users)
    S = {s: {m: np.zeros(U) for m in METRICS} for s in systems}
    N = {m: np.zeros(U) for m in METRICS}
    for r in records:
        i = uidx[r["user"]]
        ref = r[systems[0]]
        for m in METRICS:
            if ref[m] is None:
                continue
            N[m][i] += 1
            for s in systems:
                S[s][m][i] += r[s][m]
    return S, N


def bootstrap(records, systems, pairs, *, replicates=BOOTSTRAP_REPLICATES, seed=SEED, chunk=50):
    users = sorted({r["user"] for r in records})
    S, N = per_user_sums(records, systems, users)
    U = len(users)
    rng = np.random.default_rng(seed)
    reps = {s: {m: [] for m in METRICS} for s in systems}
    for start in range(0, replicates, chunk):
        k = min(chunk, replicates - start)
        W = np.stack([np.bincount(rng.integers(0, U, U), minlength=U) for _ in range(k)]).astype(float)
        for m in METRICS:
            den = W @ N[m]
            for s in systems:
                reps[s][m].append((W @ S[s][m]) / den)
    out = {"users": U, "impressions": len(records), "systems": {}, "paired": {}}
    for s in systems:
        out["systems"][s] = {}
        for m in METRICS:
            r = np.concatenate(reps[s][m])
            mean = float(S[s][m].sum() / N[m].sum()) if N[m].sum() else None
            out["systems"][s][m] = {"mean": mean, "ci95": [float(np.percentile(r, 2.5)),
                                                         float(np.percentile(r, 97.5))],
                                    "n": int(N[m].sum())}
    for a, b in pairs:
        key = f"{a} - {b}"
        out["paired"][key] = {}
        for m in METRICS:
            d = np.concatenate(reps[a][m]) - np.concatenate(reps[b][m])
            point = (S[a][m].sum() - S[b][m].sum()) / N[m].sum()
            out["paired"][key][m] = {"diff": float(point),
                                     "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
                                     "share_replicates_above_zero": float((d > 0).mean())}
    return out


def pairs_for(systems):
    base = [b for b in (*BASELINES, "embedding") if b in systems]
    p = [(a, b) for a in ARIES for b in base]
    p += [("aries-learning", "aries-interests"), ("aries-interests+diverse", "aries-interests"),
          ("aries-learning-relative", "aries-interests"), ("aries-learning-relative", "aries-learning"),
          ("aries-interests+mmr", "aries-interests"), ("aries-interests+mmr", "aries-interests+diverse")]
    return p


def counts(records, dev_beh):
    return {
        "impressions": len(records),
        "users": len({r["user"] for r in records}),
        "candidates": int(sum(r["n_cand"] for r in records)),
        "impressions_no_positive": sum(1 for r in records if r["n_pos"] == 0),
        "impressions_no_negative": sum(1 for r in records if r["n_pos"] == r["n_cand"]),
        "impressions_excluded_from_auc": sum(1 for r in records if r["aries-interests"]["auc"] is None),
        "impressions_excluded_from_mrr_ndcg": sum(1 for r in records if r["aries-interests"]["mrr"] is None),
        "impressions_empty_history": sum(1 for r in records if r["empty_history"]),
        "users_empty_history": len({r["user"] for r in records if r["empty_history"]}),
        "dev_impressions_in_file": len(dev_beh),
    }


def sha256(path) -> str | None:
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def git_state():
    try:
        commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        dirty = bool(subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain", "--",
                                              str(HERE.relative_to(ROOT))], text=True).strip())
        return commit, dirty
    except Exception:  # noqa: BLE001
        return None, None


PARAMS = {
    "seed": SEED,
    "bootstrap_replicates": BOOTSTRAP_REPLICATES,
    "bootstrap_unit": "user (resampled with replacement; mean over the resampled users' impressions)",
    "interval": "percentile 2.5/97.5",
    "tie_break": "crc32('<seed>:<impression id>:<news id>') ascending, same for every system; "
                 "AUC uses average ranks instead",
    "mrr_definition": "MIND: sum over clicked items of 1/rank divided by number of clicked items",
    "ndcg_gain": "2^y - 1, discount log2(rank + 1)",
    "aries_topics": "normalised category, subcategory and TitleEntities Label of each history item",
    "aries_weight": "share of the user's history items (present in news.tsv) carrying the topic",
    "aries_candidate_text": f"category{FIELD_SEP}subcategory{FIELD_SEP}title{FIELD_SEP}entity labels",
    "aries_synonyms": "none",
    "diverse": "aries.news.selection.diverse over the static ranking; topics = primary matched topic "
               "(highest weight, profile order on ties), unmatched -> 'other'; per_source=0; limit = all",
    "learning": {**LEARN, "lookback_changes": LOOKBACK, "path": "ordinary path of loop.propose() only",
                 "cadence": "one pass after every dev impression, topics with new evidence only",
                 "evidence": "every candidate of the impression counts as shown for each topic it matches; "
                             "clicked = label 1"},
    "popular": "clicks on the item in train+dev impressions with timestamp strictly before the impression",
    "recent": "earliest timestamp of any train+dev impression listing the item (no publish time in MIND)",
    "text_tokens": "\\w+ over aries.interests.matching.normalise(title); no stop words, no stemming",
    "tfidf": "tf raw count, idf = ln((1+N)/(1+df))+1 over all train+dev news titles, L2, cosine",
    "bm25": {"k1": BM25_K1, "b": BM25_B, "idf": "ln(1+(N-df+0.5)/(df+0.5)) over train+dev news titles",
             "query": "candidate title (unique terms)", "document": "concatenated history titles",
             "avgdl": "mean over dev users with non-empty history"},
    "embedding": "mean of e5-base-int8 'query:' history-title embeddings vs candidate title, cosine "
                 "(not run in this result unless listed in systems)",
    "empty_history": "ARIES systems score all candidates 0 (tie-break decides MRR/nDCG, AUC = 0.5); included",
}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="~/data-ext/mind")
    ap.add_argument("--limit", type=int, default=0, help="first N dev impressions in file order (smoke runs)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--replicates", type=int, default=BOOTSTRAP_REPLICATES)
    ap.add_argument("--embedding", action="store_true", help="also run the embedding baseline")
    ap.add_argument("--embedding-model", default="e5-base-int8")
    ap.add_argument("--embedding-cache", default="~/data-ext/mind/embedding-cache")
    a = ap.parse_args(argv)
    data = Path(a.data).expanduser()
    started = time.time()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    news, conflicts = load_news([data / "train" / "news.tsv", data / "dev" / "news.tsv"])
    train = load_behaviors(data / "train" / "behaviors.tsv")
    dev = load_behaviors(data / "dev" / "behaviors.tsv")
    if a.limit:
        dev = dev[:a.limit]
    print(f"loaded {len(news)} news ({conflicts} conflicting duplicates), {len(train)} train, "
          f"{len(dev)} dev impressions in {time.time() - started:.0f}s", flush=True)

    cache = None
    if a.embedding:
        from aries.workspace.memory import embedding as emb
        cache = EmbeddingCache(a.embedding_cache, emb.get(a.embedding_model), news)
        need = {n for imp in dev for n in (*imp.history, *imp.candidates)}
        cache.ensure(need, progress=lambda k: print(f"  embedded {k}", flush=True))

    records, extra = evaluate(train, dev, news, embed_cache=cache,
                              log=lambda s: print(s, flush=True))
    eval_s = time.time() - started
    systems = extra["systems"]
    full = bootstrap(records, systems, pairs_for(systems), replicates=a.replicates)
    nonempty = bootstrap([r for r in records if not r["empty_history"]], systems,
                         pairs_for(systems), replicates=a.replicates)
    commit, dirty = git_state()
    result = {
        "experiment": "MIND-small dev, ARIES interests/diversity/learning vs baselines",
        "created_utc": stamp,
        "commit": commit, "code_dirty": dirty,
        "dataset": {"name": "MIND-small", "split_evaluated": "dev",
                    "source": "https://huggingface.co/datasets/Recommenders/MIND/resolve/main/",
                    "license": "Microsoft Research License Terms (research use)",
                    "citation": "Wu et al., MIND: A Large-scale Dataset for News Recommendation, ACL 2020",
                    "zip_sha256_expected": ZIP_SHA256,
                    "zip_sha256_observed": {k: sha256(data / k) for k in ZIP_SHA256},
                    "tsv_sha256": {f"{s}/{f}": sha256(data / s / f)
                                   for s in ("train", "dev") for f in ("behaviors.tsv", "news.tsv")},
                    "news_conflicting_duplicates": conflicts,
                    "limit": a.limit or None},
        "parameters": PARAMS,
        "counts": counts(records, dev),
        "diagnostics": extra,
        "all_impressions": full,
        "nonempty_history": nonempty,
        "runtime_seconds": {"load_and_evaluate": round(eval_s, 1),
                            "total": round(time.time() - started, 1)},
        "python": sys.version.split()[0], "numpy": np.__version__,
    }
    out = Path(a.out) if a.out else HERE / "results" / f"mind-dev-{stamp}.json"
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(f"wrote {out} in {time.time() - started:.0f}s")
    for s in systems:
        row = full["systems"][s]
        print(f"{s:26s} " + "  ".join(f"{m} {row[m]['mean']:.4f} [{row[m]['ci95'][0]:.4f},{row[m]['ci95'][1]:.4f}]"
                                         for m in METRICS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
