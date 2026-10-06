"""The ARIES Sources Registry — §24.

    from aries.sources import for_agent, add

    await add(db, name="Reuters AI", type="rss",
              location="https://example.com/ai.xml", topics=["ai"], priority="high")

    # what an agent asks; it never names a website itself
    for source in await for_agent(db, type="rss", topics=["ai"], capability="read"):
        ...

Importing this package registers the source types, the table and the settings.
"""
from __future__ import annotations

from aries.sources import settings as _settings  # noqa: F401  registers the settings
from aries.sources import safety, service, types
from aries.sources.models import AriesSource
from aries.sources.safety import Checked, SourceRejected
from aries.sources.service import (
    add, add_from_catalogue, effective_rank, for_agent, get, list_sources, record_feedback, record_sync,
    remove, slugify, summary, update,
)
from aries.sources.types import Priority, SourceType, Trust, all_types

__all__ = ["add", "add_from_catalogue", "get", "update", "remove", "list_sources", "for_agent", "record_sync",
           "record_feedback", "summary", "effective_rank", "slugify",
           "AriesSource", "SourceRejected", "Checked", "SourceType", "Trust", "Priority",
           "all_types", "types", "safety", "service"]
