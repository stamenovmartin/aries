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
    return diverse(rows, topics=lambda r: r.topics, source=lambda r: r.source_id,
                   limit=limit, per_source=per_source)
