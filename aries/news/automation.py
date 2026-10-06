"""The Personal News Radar — §13/03.

    collect → cluster → verify → rank → deliver

Built as a declarative `WorkflowSpec` run through the engine's Director rather
than as one function. The specification treats workflows as first-class objects
(§9, §10): nodes with dependencies and gates, each recorded as a decision, each
traced as a step. Writing this as a single `async def` would have worked and
would have thrown all of that away — there would be nothing to inspect when a
pass produces a surprising result, and nothing for §19's topology evolution to
operate on later.

Because it is a graph, every node's decision is persisted: which ran, which were
skipped and why. `GET /api/tasks/{id}` shows the whole pass.

THE PIPELINE, AND WHAT EACH STEP IS HONEST ABOUT
------------------------------------------------
collect   Read every enabled source the registry offers for the user's topics,
          through the guarded fetcher. A source that fails is recorded against
          that source (feeding its health and the circuit breaker) and the pass
          continues — one dead feed must never cost the user the other twenty.

cluster   Group items telling the same story so the user is told once.

verify    NOT fact-checking. ARIES cannot verify a claim without a model, and
          pretending otherwise would be the dishonesty §13/20 warns about. What
          this step does is reject the structurally implausible: no title, a
          publication date in the future, an item older than the window. Named
          `verify` because §13/03 names it, and documented for what it is.

rank      Score each cluster against the Interest Profile. Deterministic and
          explainable — every item carries which topic matched, on which word,
          and whether that weight was the user's or learned.

deliver   Apply §26's notification policy. Relevance alone never establishes
          urgency; above `news.relevance_threshold` it waits for the
          briefing; below it is stored but never shown. Everything is stored,
          including what was not shown, because §29 requires that "why didn't
          you tell me about this?" be answerable.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import select

from agentic_core.evaluators.base import Evaluator, issue
from agentic_core.orchestrator.lifecycle import LifecyclePolicy
from agentic_core.scheduler.queue import register_kind
from agentic_core.security.permissions import Permission
from agentic_core.workflows import spec as wf

from aries.automations.genome import AutomationSpec, record_run, register
from aries.health.findings import Severity
from aries.interests import service as interests
from aries.news import settings as _settings  # noqa: F401  registers the settings
from aries.news.dedupe import Candidate, cluster as cluster_items
from aries.news.feed import FeedError, parse
from aries.news.fetch import FetchRefused, fetch
from aries.news.models import AriesNewsItem, fingerprint
from aries.notify import policy as notify
from aries.settings import SettingsService
from aries.sources import service as sources

logger = logging.getLogger(__name__)

AUTOMATION_ID = "aries.news"
TASK_KIND = "aries.news.scan"
WORKFLOW = "news_radar"


# ── 1. collect ──────────────────────────────────────────────────────────────

async def collect(ctx: dict) -> dict:
    db = ctx["db"]
    s = SettingsService(db)
    cfg = await s.section("news")
    ctx["news_config"] = cfg

    topics = await interests.topics_for(db)
    chosen = await sources.for_agent(db, types_=["rss"], topics=topics, capability="read",
                                     limit=int(cfg["news.max_sources_per_pass"]))
    allow_private = bool(await s.get("sources.allow_private_addresses"))

    collected, per_source, failures = [], [], []
    # Every fetch happens before any write. record_sync flushes, and a flush takes
    # SQLite's write lock for the rest of the transaction — held across up to 25
    # network fetches it starved every other writer into "database is locked",
    # which is what made spoken commands fail. Close the read transaction too.
    syncs: list[tuple[str, dict]] = []
    await db.commit()
    for source in chosen:
        t0 = time.monotonic()
        try:
            res = await fetch(source.location, allow_private=allow_private,
                              max_bytes=int(cfg["news.max_bytes_per_source"]),
                              timeout=float(cfg["news.fetch_timeout_seconds"]))
            if not res.ok:
                raise FetchRefused(f"HTTP {res.status}")
            feed = parse(res.body, max_items=int(cfg["news.max_items_per_source"]))
        except (FetchRefused, FeedError) as e:
            # A source that fails is the SOURCE's failure, recorded against it so
            # its health degrades and ranking notices — not the pass's failure.
            syncs.append((source.source_id, {"ok": False, "error": str(e)}))
            failures.append({"source_id": source.source_id, "error": str(e)[:300]})
            continue
        except Exception as e:                      # noqa: BLE001
            logger.exception("Unexpected error reading %s", source.source_id)
            syncs.append((source.source_id, {"ok": False, "error": f"{type(e).__name__}: {e}"}))
            failures.append({"source_id": source.source_id, "error": f"{type(e).__name__}: {e}"})
            continue

        from aries.news.catalogue import CATALOGUE
        coverage = next((e.coverage_topics for e in CATALOGUE if e.url == source.location), ())
        for item in feed.items:
            collected.append({
                "source_id": source.source_id, "source_weight": float(source.priority),
                "coverage_topics": list(coverage),
                "title": item.title, "link": item.link, "summary": item.summary,
                "author": item.author, "guid": item.guid, "published": item.published,
                "item_id": fingerprint(source.source_id, item.guid or item.link or item.title),
            })
        per_source.append({"source_id": source.source_id, "items": len(feed.items),
                           "ms": int((time.monotonic() - t0) * 1000), "feed": feed.kind})
        syncs.append((source.source_id, {"ok": True, "items_seen": len(feed.items)}))
    for source_id, outcome in syncs:
        await sources.record_sync(db, source_id, commit=False, **outcome)
    await db.commit()
    return {"collected": collected, "per_source": per_source, "fetch_failures": failures,
            "sources_considered": len(chosen)}


# ── 2. cluster ──────────────────────────────────────────────────────────────

async def cluster(ctx: dict) -> dict:
    cfg = ctx.get("news_config") or {}
    items = ctx.get("collected") or []
    # Sorted so the preferred representative comes first: the registry already
    # ordered the sources, so a higher-priority source speaks for a story.
    candidates = [Candidate(item_id=i["item_id"], title=i["title"], link=i["link"],
                            guid=i["guid"], source_id=i["source_id"],
                            weight=i["source_weight"], extra=i)
                  for i in items]
    groups = cluster_items(candidates,
                           threshold=float(cfg.get("news.duplicate_threshold", 0.6)))
    duplicates = sum(g.size - 1 for g in groups)
    return {"clusters": groups, "cluster_count": len(groups), "duplicates_merged": duplicates}


# ── 3. verify ───────────────────────────────────────────────────────────────

async def verify(ctx: dict) -> dict:
    """Structural plausibility only — see the module docstring."""
    cfg = ctx.get("news_config") or {}
    max_age = timedelta(hours=float(cfg.get("news.max_age_hours", 72.0)))
    now = datetime.utcnow()
    kept, rejected = [], []
    for group in ctx.get("clusters") or []:
        item = group.representative.extra
        title = (item.get("title") or "").strip()
        published = item.get("published")
        if not title:
            rejected.append({"item_id": item["item_id"], "why": "no title"}); continue
        # A small skew is normal (publisher clocks, time zones); a day is not.
        if published and published > now + timedelta(hours=6):
            rejected.append({"item_id": item["item_id"],
                             "why": f"published in the future ({published.isoformat()})"}); continue
        if published and (now - published) > max_age:
            rejected.append({"item_id": item["item_id"],
                             "why": f"older than {max_age.total_seconds() / 3600:.0f}h"}); continue
        kept.append(group)
    return {"verified": kept, "rejected": rejected}


# ── 4. rank ─────────────────────────────────────────────────────────────────

async def rank(ctx: dict) -> dict:
    db = ctx["db"]
    profile = await interests.profile(db)
    from aries.interests.matching import score as score_text

    ranked = []
    for group in ctx.get("verified") or []:
        item = group.representative.extra
        text = f"{item['title']}. {item.get('summary', '')}"
        rel = score_text(text, profile)
        # Only explicitly curated subject-specific feeds provide coverage evidence.
        # Broad publishers are not assumed to make every article about their country.
        if not rel.excluded:
            covered = set(item.get("coverage_topics", []))
            existing = {m["topic"] for m in rel.matched}
            for interest in profile:
                if not interest.avoid and interest.key in covered and interest.key not in existing:
                    rel.matched.append({"topic": interest.key, "weight": interest.weight,
                                        "source": "curated_feed_coverage", "hits": []})
            if rel.matched:
                inverse = 1.0
                for match in rel.matched:
                    inverse *= 1.0 - match["weight"]
                rel.score = round(1.0 - inverse, 6)
                rel.matched.sort(key=lambda m: -m["weight"])
                rel.explanation += "; feed coverage: " + ", ".join(sorted(covered)) if covered else ""
        ranked.append({"group": group, "item": item, "relevance": rel})
    ranked.sort(key=lambda r: -r["relevance"].score)
    return {"ranked": ranked}


# ── 5. deliver ──────────────────────────────────────────────────────────────

async def deliver(ctx: dict) -> dict:
    db = ctx["db"]
    s = SettingsService(db)
    cfg = dict(ctx.get("news_config") or {})
    cfg.update(await s.section("notifications"))
    threshold = float(cfg.get("news.relevance_threshold", 0.6))
    max_items = int(cfg.get("news.max_items_per_briefing", 8))

    per_source_cap = int(cfg.get("news.max_per_source_in_briefing", 3))

    known = set((await db.execute(select(AriesNewsItem.item_id))).scalars().all())
    delivered, held, stored, engaged_topics = [], [], 0, []
    stored_ids: set[str] = set()           # written during THIS pass
    from_source: dict[str, int] = {}

    from aries.news.selection import diverse
    ranked = ctx.get("ranked") or []
    eligible = [r for r in ranked if not r["relevance"].excluded
                and r["relevance"].score >= threshold and r["item"]["item_id"] not in known]
    selected = {r["item"]["item_id"] for r in diverse(
        eligible, topics=lambda r: [m["topic"] for m in r["relevance"].matched],
        source=lambda r: r["item"]["source_id"], limit=max_items, per_source=per_source_cap)}
    for entry in ranked:
        item, rel, group = entry["item"], entry["relevance"], entry["group"]
        if item["item_id"] in known:
            continue                       # already seen in an earlier pass

        if rel.excluded:
            disposition = "excluded"
        elif rel.score < threshold:
            disposition = "below_threshold"
        else:
            severity = Severity.NOTICE  # Interest is not evidence of urgency.
            # Both immediate and held items count toward source/total caps.
            over_source = (per_source_cap > 0
                           and from_source.get(item["source_id"], 0) >= per_source_cap)
            if item["item_id"] not in selected or over_source or len(delivered) + len(held) >= max_items:
                disposition = "below_threshold"
            else:
                decision, _ = await notify.emit(
                    db, key=f"news:{item['item_id']}", title=item["title"][:300],
                    severity=severity, source=AUTOMATION_ID,
                    body=f"{item.get('summary', '')[:400]}\n{item.get('link', '')}", config=cfg)
                disposition = "delivered" if decision.delivered else "held"
                (delivered if decision.delivered else held).append({
                    "title": item["title"], "link": item.get("link", ""),
                    "relevance": rel.score, "source_id": item["source_id"],
                    "topics": [m["topic"] for m in rel.matched],
                    "why": rel.explanation, "cluster_size": group.size})
                engaged_topics.extend(m["topic"] for m in rel.matched)
                from_source[item["source_id"]] = from_source.get(item["source_id"], 0) + 1

        # Every member of the cluster is stored, including the duplicates, so a
        # later "why didn't you show me this?" has an answer.
        #
        # SKIPPING WHAT IS ALREADY THERE. The outer loop skips a `ranked` entry
        # whose item is known, but a cluster's MEMBERS are a different set: a
        # new article can cluster with one stored a pass ago, and two entries in
        # this same pass can share a cluster and so share members. Both insert
        # an item_id that already exists, and `item_id` is unique — so the flush
        # raised, the session was poisoned, and every later statement in the
        # pass failed with PendingRollbackError. Three passes of that opened the
        # News Radar's circuit breaker.
        #
        # It stayed hidden because the run still returned `success: True` from
        # its own body while the lifecycle recorded `failed`. The Operator's
        # verifier is what made the two visible side by side.
        for member in group.members:
            if member.item_id in known or member.item_id in stored_ids:
                continue
            # A SEPARATE set, not `known`. The first fix added members to
            # `known` itself, which quietly changed what `known` means further
            # down — the per-source "this item reached the user" counter reads
            # it to decide whether an item is new, and every item was suddenly
            # old. Two meanings in one variable: "seen before this pass" and
            # "written during this pass" are different facts.
            stored_ids.add(member.item_id)
            src_item = member.extra
            is_rep = member.item_id == group.representative.item_id
            db.add(AriesNewsItem(
                item_id=src_item["item_id"], source_id=src_item["source_id"],
                title=src_item["title"][:500], link=src_item.get("link", ""),
                summary=src_item.get("summary", ""), author=src_item.get("author", ""),
                published_at=src_item.get("published"),
                relevance=rel.score, matched_json=_json(rel.matched),
                excluded_by=(rel.excluded_by or {}).get("topic") if rel.excluded else None,
                explanation=rel.explanation,
                cluster_id=group.cluster_id, is_representative=is_rep,
                duplicate_of=None if is_rep else group.representative.item_id,
                disposition=disposition if is_rep else "duplicate"))
            stored += 1

    # Count what the user was shown, per topic — the evidence §16's medium loop
    # will later turn into a learned weight. Counting only; nothing is inferred here.
    if engaged_topics:
        await interests.record_engagement(db, sorted(set(engaged_topics)), shown=True, commit=False)
    for entry in ctx.get("ranked") or []:
        item = entry["item"]
        if entry["relevance"].score >= threshold and item["item_id"] not in known:
            await sources.record_sync(db, item["source_id"], ok=True, items_useful=1, commit=False)
    await db.commit()

    considered = ctx.get("sources_considered", 0)
    failures = ctx.get("fetch_failures") or []
    if considered and len(failures) >= considered:
        summary = f"every source failed ({len(failures)} of {considered})"
    elif not ctx.get("collected"):
        summary = (f"nothing collected from {considered} source(s)" if considered
                   else "no enabled source matched the interest profile")
    else:
        spread = len({d["source_id"] for d in delivered})
        summary = (f"{len(delivered)} delivered from {spread} source(s), {len(held)} held, "
                   f"{ctx.get('duplicates_merged', 0)} duplicates merged, "
                   f"{len(ctx.get('rejected') or [])} rejected, "
                   f"{considered} sources")
        if failures:
            summary += f", {len(failures)} source(s) failed"

    return {"result": {
        "success": True, "summary": summary, "details": summary,
        "delivered": delivered, "held": held,
        "stored": stored, "clusters": ctx.get("cluster_count", 0),
        "duplicates_merged": ctx.get("duplicates_merged", 0),
        "rejected": ctx.get("rejected") or [],
        "per_source": ctx.get("per_source") or [],
        "fetch_failures": ctx.get("fetch_failures") or [],
        "sources_considered": ctx.get("sources_considered", 0),
    }}


def _json(value) -> str:
    import json
    return json.dumps(value, ensure_ascii=False, default=str)


# ── gates ───────────────────────────────────────────────────────────────────

@wf.gate("news_collected")
def _collected(ctx):
    n = len(ctx.get("collected") or [])
    return bool(n), f"{n} items collected" if n else "no source returned anything"


@wf.gate("news_survived_verification")
def _survived(ctx):
    n = len(ctx.get("verified") or [])
    return bool(n), f"{n} stories to rank" if n else "nothing survived verification"


# ── the workflow (§9, §10) ──────────────────────────────────────────────────

SPEC_WF = wf.register(wf.WorkflowSpec(
    WORKFLOW,
    description="Read every permitted source, merge duplicate stories, discard the implausible, "
                "score what is left against the interest profile, and tell the user only what "
                "clears their thresholds.",
    nodes=[
        wf.NodeSpec("collect", label="Read the sources", fn=collect),
        wf.NodeSpec("cluster", label="Merge duplicate stories", fn=cluster,
                    depends_on=["collect"], gate="news_collected"),
        wf.NodeSpec("verify", label="Discard the implausible", fn=verify, depends_on=["cluster"]),
        wf.NodeSpec("rank", label="Score against my interests", fn=rank,
                    depends_on=["verify"], gate="news_survived_verification"),
        # Depends on COLLECT, not on rank — deliberately.
        #
        # It depended on rank at first, and that was a hole: when every source
        # failed, the cluster gate closed, verify and rank skipped as dependents,
        # and deliver skipped with them. Deliver is what assembles the result, so
        # the pass returned nothing, the evaluators saw an empty dict, and a run
        # in which every single source was dead was recorded as a success.
        #
        # The step that REPORTS must not be skippable by the conditions it is
        # reporting on. Depending only on collect keeps it running whatever the
        # gates decide, and being last in this list keeps it running last.
        wf.NodeSpec("deliver", label="Decide who needs to know", fn=deliver,
                    depends_on=["collect"]),
    ]))


# ── evaluators: they judge the PASS, never the news ─────────────────────────

async def _pass_worked(result, task, ctx) -> list[dict]:
    if not isinstance(result, dict):
        return [issue("error", "no_result", "the news pass returned nothing")]
    considered = result.get("sources_considered", 0)
    failures = result.get("fetch_failures") or []
    if considered and len(failures) >= considered:
        return [issue("error", "every_source_failed",
                      f"all {considered} sources failed: "
                      + "; ".join(f["error"] for f in failures[:3]))]
    return []


async def _source_health(result, task, ctx) -> list[dict]:
    return [issue("warn", "source_failed", f"{f['source_id']}: {f['error'][:120]}")
            for f in (result or {}).get("fetch_failures") or []]


async def _has_sources(result, task, ctx) -> list[dict]:
    if not (result or {}).get("sources_considered"):
        return [issue("warn", "no_sources",
                      "no enabled RSS source matched the interest profile — "
                      "add one with: aries sources add --type rss")]
    return []


EVALUATORS = [
    Evaluator("news_pass_worked", _pass_worked, weight=2.0),
    Evaluator("source_health", _source_health, weight=0.5),
    Evaluator("has_sources", _has_sources, weight=0.5),
]


# ── the genome (§12) ────────────────────────────────────────────────────────

async def _learning_status(db) -> dict:
    from sqlalchemy import func

    rows = (await db.execute(
        select(AriesNewsItem.disposition, func.count(AriesNewsItem.id))
        .group_by(AriesNewsItem.disposition))).all()
    counts = {d: int(n) for d, n in rows}
    total = sum(counts.values())
    engaged = (await db.execute(
        select(func.count(AriesNewsItem.id)).where(AriesNewsItem.engaged.is_(True)))).scalar() or 0
    shown = counts.get("delivered", 0)
    return {
        "items_seen": total, "by_disposition": counts, "engaged": engaged,
        "engagement_rate": round(engaged / shown, 3) if shown else None,
        "explanation": (
            f"{total} items seen, {shown} delivered, {engaged} acted on. "
            + ("Engagement is counted but not yet turned into learned topic weights — "
               "that is the medium loop of section 16."
               if shown else "Nothing delivered yet, so there is nothing to learn from.")),
    }


SPEC = AutomationSpec(
    automation_id=AUTOMATION_ID,
    name="News Radar",
    version="1.0.0",
    purpose="Read the sources the user chose, merge duplicate stories, score what is left "
            "against their interests, and interrupt only when it is worth it.",
    run=lambda ctx: _run_via_task(ctx),
    trigger="schedule",
    schedule_setting="news.poll_interval_minutes",
    default_interval_minutes=120,
    conditions=["news.enabled is on", "at least one enabled RSS source", "at least one topic"],
    input_sources=["aries_sources (type=rss)"],
    task_kind=TASK_KIND,
    workflow=WORKFLOW,
    agents=[],                       # deterministic: no model is involved
    tools=["https fetch (guarded)"],
    permissions=[Permission.VIEW_DATA],
    memory_dependencies=["aries_news_items", "aries_interests", "aries_sources"],
    enabled_setting="news.enabled",
    writes_settings=[],
    risk="low",                      # reads the internet; changes nothing outside ARIES
    requires_approval=False,
    evaluation_metrics=["delivered_count", "duplicate_merge_rate", "source_failure_rate",
                        "engagement_rate", "below_threshold_rate"],
    reward_signals=["the user opened an item", "the user dismissed an item as noise",
                    "a source produced only duplicates", "a topic was never engaged with"],
    learning_status=lambda db: _learning_status(db),
)

register(SPEC)
register_kind(TASK_KIND, workflow=WORKFLOW, evaluators=EVALUATORS,
              policy=LifecyclePolicy(max_retries=1, max_replans=0, pass_threshold=0.6))


async def _run_via_task(ctx: dict) -> dict:
    """The genome's `run` is only used for automations without a task kind; this
    one has one, so the runner takes the lifecycle path and never calls here."""
    raise RuntimeError("aries.news runs through its task kind, not directly")
