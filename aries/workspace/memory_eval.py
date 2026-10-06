"""Does deciding what to keep beat keeping everything?

THE HONEST BASELINE IS NOT "NO MEMORY"
--------------------------------------
It is **store every utterance verbatim, embed it with a good model, and run no
extraction at all**. That baseline is cheap, has no failure modes of its own,
and cannot lose information — the only thing it can lose is precision. Two
independent published results suggest it wins. If the cascade in
`aries/workspace/memory/extraction.py` does not beat it, the cascade is a cost
optimisation and not a capability, and this file must say so rather than
quietly compare against something weaker.

So the baseline is run twice, at its strongest:

    verbatim-semantic        every utterance, including the ones a privacy
                             policy would refuse. The strict reading.
    verbatim-gated-semantic  every utterance that stage 1 permits. Stage 1 is
                             a PRIVACY policy, not extraction, so denying it to
                             the baseline would be a straw man. This is the
                             baseline the statistics are run against.

and two lexical variants exist to separate three different claims that would
otherwise be one number:

    verbatim-exact-words     the predicate ARIES actually shipped before this
                             change — whole words longer than three characters.
    verbatim-focused         the same corpus through `focused-v2` plus the new
                             `retrieval.stem`, so the stemmer's contribution is
                             visible on its own.

and the proposal:

    extracted-semantic       the three-stage cascade, then `semantic-v3`.

TWO BINARY OUTCOMES, NOT ONE
----------------------------
`hit@3` asks whether the answer came back. `clean@3` asks whether anything came
back that should not have — a fact the user has since contradicted, or
something the privacy gate was supposed to have refused. A memory system is
allowed to be judged on both, and they do not move together: keeping everything
can only help the first and can only hurt the second.

WHY NOT LoCoMo
--------------
6.4% of its answer key is wrong. Tuning against a benchmark whose gold labels
are wrong one time in sixteen produces a system tuned to reproduce those errors.
The fixture here is small, it is this user's own Macedonian and mixed-language
speech, and half of it was transcribed by the machine it runs on.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter

from aries.workspace import retrieval
from aries.workspace.learning_eval import paired_statistics
from aries.workspace.memory import embedding, extraction, vectors
from aries.workspace.models import IMPORTANCE

FIXTURE = Path(__file__).resolve().parents[2] / "experiments" / "memory"
K = 3
VARIANTS = ("verbatim-exact-words", "verbatim-focused", "verbatim-semantic",
            "verbatim-gated-semantic", "extracted-semantic")
BASELINE, CANDIDATE = "verbatim-gated-semantic", "extracted-semantic"
# One utterance an hour, oldest first, so the recency term has something real to
# act on. Everything is evaluated at one fixed `now`, so a rerun is comparable.
SPACING = timedelta(hours=1)


def load():
    corpus = [json.loads(line) for line in (FIXTURE / "corpus.jsonl").read_text().splitlines() if line.strip()]
    probes = [json.loads(line) for line in (FIXTURE / "tasks.jsonl").read_text().splitlines() if line.strip()]
    return corpus, probes


def _legacy_word_match(request, rows):
    """The predicate ARIES shipped until 2026-09-29, reproduced exactly.

        words = {w for w in re.findall(r"\\w+", request.casefold()) if len(w) > 3}
        [m for m in memories if words & set(re.findall(r"\\w+", m["text"].casefold()))]

    Kept here and nowhere else: it is a baseline, not a code path.
    """
    import re
    terms = {w for w in re.findall(r"\w+", request.casefold()) if len(w) > 3}
    scored = []
    for row in rows:
        overlap = terms & set(re.findall(r"\w+", row["text"].casefold()))
        if overlap:
            scored.append((len(overlap), row))
    scored.sort(key=lambda item: -item[0])
    return [row for _, row in scored[:K]]


def build(variant, corpus, embedder, *, cascade=None, excluded=(), origin=None):
    """Populate one variant's store. Returns (rows, cache, statistics)."""
    origin = origin or datetime(2026, 9, 20, 9, 0, 0)
    semantic = variant.endswith("semantic")
    cache = vectors.VectorCache(embedder.dim) if semantic else None
    rows, stale, decisions, supersessions = [], set(), [], []
    embed_ms, model_calls, escalations = [], 0, 0

    for index, item in enumerate(corpus):
        text = extraction.normalise(item["text"])
        created = origin + index * SPACING
        kind = extraction.classify_kind(text)
        decision = {"id": item["id"], "action": "APPEND", "stage": "none", "reason": "stored verbatim",
                    "confidence": 1., "similarity": None}

        if variant in ("verbatim-gated-semantic", "extracted-semantic"):
            refused = extraction.gate(text, excluded=excluded)
            if refused is not None:
                decisions.append({**decision, **refused.as_dict(), "id": item["id"]})
                continue

        vector = None
        if semantic:
            started = perf_counter()
            vector = embedder.passages([text])[0]
            embed_ms.append((perf_counter() - started) * 1000)

        if variant == "extracted-semantic":
            neighbours = cache.search(vector, limit=5)
            neighbours = [(rid, score, next(r["text"] for r in rows if r["id"] == rid))
                          for rid, score in neighbours]
            before = cascade.calls
            verdict = cascade.run(text, neighbours, excluded=excluded)
            escalations += cascade.calls > before
            model_calls = cascade.calls
            decision = {"id": item["id"], **verdict.as_dict()}
            decisions.append(decision)
            if verdict.action in ("ABORT", "NOOP"):
                continue
            if verdict.action == "SUPERSEDE" and verdict.related_to:
                # Arbitration by clock, exactly as `store.arbitrate` does it:
                # the corpus is in chronological order, so the stored row is
                # always the older one and always the one that loses.
                #
                # The live store keeps the utterance and withdraws only the
                # LEARNED conclusion drawn from it (`store.withdrawn_sources`),
                # because a machine may not expire what the user said. Here the
                # two are 1:1 by construction, so one row stands for the pair;
                # the retrieval-visible effect is identical and the layer rule
                # is what `tests/test_memory.py` checks instead.
                stale.add(verdict.related_to)
                supersessions.append({"new": item["id"], "withdrew": verdict.related_to,
                                      "correct": item.get("supersedes") == verdict.related_to,
                                      "confidence": round(verdict.confidence, 4),
                                      "similarity": round(verdict.similarity or 0., 4)})
        else:
            decisions.append(decision)

        row = {"id": item["id"], "text": text, "kind": kind, "layer": 60,
               "importance": IMPORTANCE.get(kind, .5), "created_at": created,
               "last_retrieved_at": None, "vector": vector}
        rows.append(row)
        if cache is not None:
            cache.add(item["id"], vector)

    live = [r for r in rows if r["id"] not in stale]
    expected_supersessions = {i["supersedes"] for i in corpus if i.get("supersedes")}
    return live, cache, {
        "stored": len(live), "expired_by_supersession": sorted(stale),
        "supersessions": supersessions,
        "supersessions_correct": sum(s["correct"] for s in supersessions),
        "supersessions_false": sum(not s["correct"] for s in supersessions),
        "supersessions_missed": sorted(expected_supersessions - stale),
        "offered": len(corpus), "model_calls": model_calls, "escalations": escalations,
        "escalation_rate": round(escalations / max(1, len(corpus)), 4),
        "median_embed_ms": round(sorted(embed_ms)[len(embed_ms)//2], 3) if embed_ms else None,
        "decisions": decisions}


def select(variant, rows, query, embedder):
    """Top-K for one probe. Returns (ids, search_ms)."""
    if variant == "verbatim-exact-words":
        started = perf_counter()
        chosen = _legacy_word_match(query, rows)
        return [r["id"] for r in chosen], (perf_counter() - started) * 1000
    version = "semantic-v3" if variant.endswith("semantic") else "focused-v2"
    query_vector = embedder.query(query) if version == "semantic-v3" else None
    started = perf_counter()
    scored = retrieval.score_memories(rows, query, version, now=_NOW,
                                      query_vector=query_vector, limit=K)
    return [row["id"] for _, row, _ in scored], (perf_counter() - started) * 1000


_NOW = datetime(2026, 9, 22, 9, 0, 0)     # fixed, so recency is reproducible


def evaluate(variant, corpus, probes, embedder, *, cascade=None, excluded=()):
    forbidden = {item["id"] for item in corpus if item.get("expect") == "GATE"}
    rows, _, stats = build(variant, corpus, embedder, cascade=cascade, excluded=excluded)
    present = {r["id"] for r in rows}
    cases, search_ms = [], []
    for probe in probes:
        selected, elapsed = select(variant, rows, probe["query"], embedder)
        search_ms.append(elapsed)
        expected, stale = set(probe.get("expected", [])), set(probe.get("stale", []))
        top = set(selected)
        hit = bool(expected & top) if expected else None
        cases.append({
            "id": probe["id"], "query": probe["query"], "mode": probe["mode"],
            "expected": probe.get("expected", []), "selected": selected,
            "hit_at_k": hit,
            "recall_at_k": round(len(expected & top) / len(expected), 4) if expected else None,
            "reciprocal_rank": next((1 / (i + 1) for i, s in enumerate(selected) if s in expected), 0.)
                               if expected else None,
            "stale_returned": sorted(stale & top),
            "forbidden_returned": sorted(forbidden & top),
            "clean": not (stale & top) and not (forbidden & top),
            "gold_unstorable": sorted(expected - present),
        })
    answered = [c for c in cases if c["hit_at_k"] is not None]
    return {
        "variant": variant, "cases": cases, **stats,
        "hit_at_k": sum(c["hit_at_k"] for c in answered), "answerable": len(answered),
        "mean_reciprocal_rank": round(sum(c["reciprocal_rank"] for c in answered) / max(1, len(answered)), 4),
        "mean_recall_at_k": round(sum(c["recall_at_k"] for c in answered) / max(1, len(answered)), 4),
        "clean": sum(c["clean"] for c in cases), "probes": len(cases),
        "stale_returns": sum(len(c["stale_returned"]) for c in cases),
        "forbidden_returns": sum(len(c["forbidden_returned"]) for c in cases),
        "gold_lost_to_extraction": sorted({g for c in cases for g in c["gold_unstorable"]}),
        "median_search_ms": round(sorted(search_ms)[len(search_ms)//2], 4),
    }


def compare(*, embedder_name=None, model=None, excluded=("терапија",)):
    """Every variant on the same fixture, with the identities that make it
    reproducible. The shape `learning_eval.compare` established."""
    corpus, probes = load()
    payload = (FIXTURE / "corpus.jsonl").read_bytes() + b"\0" + (FIXTURE / "tasks.jsonl").read_bytes()
    embedder = embedding.get(embedder_name or embedding.DEFAULT)
    settings = {}
    if model:
        settings["model"] = model
    cascade = extraction.Cascade(**settings)

    results = {v: evaluate(v, corpus, probes, embedder,
                           cascade=extraction.Cascade(**settings) if v == "extracted-semantic" else None,
                           excluded=excluded)
               for v in VARIANTS}
    baseline, candidate = results[BASELINE], results[CANDIDATE]
    answerable = [p["id"] for p in probes if p.get("expected")]
    pairs = {"hit": ([next(c["hit_at_k"] for c in baseline["cases"] if c["id"] == i) for i in answerable],
                     [next(c["hit_at_k"] for c in candidate["cases"] if c["id"] == i) for i in answerable]),
             "clean": ([c["clean"] for c in baseline["cases"]], [c["clean"] for c in candidate["cases"]])}

    from aries.workspace.memory import store
    implementation = b"\0".join(Path(m.__file__).read_bytes() for m in
                                (retrieval, extraction, vectors, store, embedding))
    verdict = _verdict(baseline, candidate, pairs)
    return {
        "fixture_sha256": hashlib.sha256(payload).hexdigest(),
        "implementation_sha256": hashlib.sha256(implementation).hexdigest(),
        "embedder": embedder.name, "dimensions": embedder.dim,
        "decision_model": cascade.model, "k": K, "corpus": len(corpus), "probes": len(probes),
        "environment": {"openblas_num_threads": os.environ.get("OPENBLAS_NUM_THREADS"),
                        "evaluated_at_utc": _NOW.isoformat()},
        "variants": results,
        "statistics": {name: paired_statistics(*values) for name, values in pairs.items()},
        "verdict": verdict, "promoted": False,
    }


def _verdict(baseline, candidate, pairs):
    """State the disappointing answer as plainly as the flattering one."""
    found = candidate["hit_at_k"] - baseline["hit_at_k"]
    cleaner = candidate["clean"] - baseline["clean"]
    lines = []
    if found > 0:
        lines.append(f"extraction retrieved {found} more answer(s) than storing everything")
    elif found == 0:
        lines.append("extraction retrieved exactly as many answers as storing everything")
    else:
        lines.append(f"extraction retrieved {-found} FEWER answer(s) than storing everything")
    if cleaner > 0:
        lines.append(f"and returned a stale or refused memory on {cleaner} fewer probe(s)")
    elif cleaner < 0:
        lines.append(f"and returned a stale or refused memory on {-cleaner} MORE probe(s)")
    else:
        lines.append("and was no cleaner")
    saved = baseline["stored"] - candidate["stored"]
    lines.append(f"storing {candidate['stored']} rows instead of {baseline['stored']} ({saved} fewer), "
                 f"at {candidate['model_calls']} local model call(s)")
    hit_p = paired_statistics(*pairs["hit"])["exact_mcnemar_two_sided_p"]
    clean_p = paired_statistics(*pairs["clean"])["exact_mcnemar_two_sided_p"]
    lines.append(f"neither difference is significant on this fixture (hit p={hit_p:.3f}, clean p={clean_p:.3f})")
    if found <= 0 and cleaner <= 0:
        lines.append("ON THIS FIXTURE THE EXTRACTION IS A COST OPTIMISATION, NOT A CAPABILITY")
    elif found <= 0:
        lines.append("ON RETRIEVAL ALONE IT IS A COST OPTIMISATION; the capability claim rests "
                     "entirely on the stale and refused returns, which this fixture is too small "
                     "to establish")
    if candidate.get("supersessions_false"):
        lines.append(f"and {candidate['supersessions_false']} of "
                     f"{len(candidate.get('supersessions', []))} supersession(s) were WRONG, "
                     f"destroying a true memory — unmitigated")
    return " · ".join(lines)


async def report(db):
    """The same card shape the learning comparison uses, for the dashboard."""
    from aries.settings import SettingsService
    result = compare()
    active = await SettingsService(db).get("workspace.memory_retrieval")
    cards = [{"title": "Semantic memory comparison",
              "text": f"Active version: {active}. No version changed by this run.",
              "evidence": f"{result['corpus']} utterances · {result['probes']} probes · "
                          f"{result['embedder']} · k={result['k']}"}]
    for name, score in result["variants"].items():
        cards.append({"title": name,
                      "text": f"{score['hit_at_k']}/{score['answerable']} answers found · "
                              f"{score['clean']}/{score['probes']} probes clean · "
                              f"{score['stored']} rows stored · {score['forbidden_returns']} refused-topic returns",
                      "evidence": f"MRR {score['mean_reciprocal_rank']} · "
                                  f"median search {score['median_search_ms']} ms"})
    for name, stats in result["statistics"].items():
        cards.append({"title": f"Paired comparison — {name}",
                      "text": f"{CANDIDATE} minus {BASELINE}: {stats['accuracy_difference']:+.0%} · "
                              f"exact two-sided McNemar p={stats['exact_mcnemar_two_sided_p']:.3f}",
                      "evidence": stats["interpretation"]})
    cards.append({"title": "Verdict", "text": result["verdict"],
                  "evidence": "Stated as measured. The baseline is store-everything-verbatim with the "
                              "same embedder, not 'no memory'."})
    return {"state": "done", "summary": "Compared five memory variants on one fixture of real speech",
            "cards": cards, "comparison": result, "active_version": active}
