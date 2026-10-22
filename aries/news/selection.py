"""Bounded, deterministic topic diversity; relevance does not establish urgency."""
from collections import OrderedDict
from datetime import datetime, timedelta
from sqlalchemy import select
from aries.news.models import AriesNewsItem


def diverse(items, *, topics, source, limit, per_source=3):
    """Round-robin primary topics, preserving ranked order inside each topic."""
    groups = OrderedDict()
    for item in items:
        key = next(iter(topics(item)), 'other')
        groups.setdefault(key, []).append(item)
    result, counts = [], {}
    while groups and len(result) < limit:
        for key in list(groups):
            group = groups[key]
            while group:
                item = group.pop(0)
                src = source(item)
                if per_source and counts.get(src, 0) >= per_source:
                    continue
                result.append(item)
                counts[src] = counts.get(src, 0) + 1
                break
            if not group:
                del groups[key]
            if len(result) >= limit:
                break
    return result


# ── ARIES_NEWS_DIVERSE_TOPK ─────────────────────────────────────────────────────
# MIND-small dev: round-robin over topics cost 0.035 AUC, because it interleaves a
# topic's weakest items with the next topic's best ones all the way down the list.
# Maximal Marginal Relevance (Carbonell and Goldstein, SIGIR 1998) trades relevance
# against redundancy at each pick: score = LAMBDA * relevance - (1 - LAMBDA) * [the
# item's primary topic is already among the picks]. A clearly more relevant item still
# wins over a new topic. LAMBDA is fixed here, not fitted on evaluation data.
MMR_LAMBDA = 0.7


def mmr(items, *, relevance, topics, source, limit, per_source=3, lam=MMR_LAMBDA):
    """Greedy MMR with topic redundancy; relevance is min-max scaled over `items`."""
    pool = list(items)
    if not pool:
        return []
    rel = [float(relevance(i)) for i in pool]
    low, high = min(rel), max(rel)
    rel = [(r - low) / (high - low) if high > low else 1. for r in rel]
    key = [next(iter(topics(i)), 'other') for i in pool]
    left, seen, counts, result = list(range(len(pool))), set(), {}, []
    while left and len(result) < limit:
        best = max(left, key=lambda j: (lam * rel[j] - (1 - lam) * (key[j] in seen), -j))
        left.remove(best)
        src = source(pool[best])
        if per_source and counts.get(src, 0) >= per_source:
            continue
        result.append(pool[best])
        seen.add(key[best])
        counts[src] = counts.get(src, 0) + 1
    return result


async def briefing_rows(db, *, limit=8, hours=24, per_source=3):
    since = datetime.utcnow() - timedelta(hours=hours)
    rows = (await db.execute(select(AriesNewsItem).where(
        AriesNewsItem.disposition.in_(['delivered', 'held']),
        AriesNewsItem.is_representative.is_(True),
        AriesNewsItem.dismissed.is_(False),
        AriesNewsItem.first_seen_at >= since,
        (AriesNewsItem.published_at.is_(None) | (AriesNewsItem.published_at >= since)),
    ).order_by(AriesNewsItem.first_seen_at.desc(), AriesNewsItem.id.desc()).limit(2000))).scalars().all()
    rows.sort(key=lambda r: (-r.relevance, -(r.published_at or r.first_seen_at).timestamp()))
    from aries import flags
    if flags.enabled('ARIES_NEWS_DIVERSE_TOPK'):
        return mmr(rows, relevance=lambda r: r.relevance, topics=lambda r: r.topics, source=lambda r: r.source_id,
                   limit=limit, per_source=per_source)
    return diverse(rows, topics=lambda r: r.topics, source=lambda r: r.source_id,
                   limit=limit, per_source=per_source)
