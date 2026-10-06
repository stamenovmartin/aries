"""ARIES Personal Interest Profile — §25.

    from aries.interests import add, score_text

    await add(db, topic="LLM agents", synonyms=["agentic"], weight=0.9)
    await add(db, topic="cryptocurrency", stance="avoid")

    r = await score_text(db, "Building agentic loops with tool use")
    r.score          # 0.9
    r.explanation    # "matches 1 topic(s): llm agents (0.90)"

Importing this package registers the table and the settings.
"""
from __future__ import annotations

from aries.interests import settings as _settings  # noqa: F401  registers the settings
from aries.interests import matching, service
from aries.interests.matching import Matchable, Relevance, normalise
from aries.interests.models import AVOID, WANT, AriesInterest
from aries.interests.service import (
    InterestError, add, get, learn, list_interests, profile, record_engagement,
    remove, score_text, summary, topics_for, update,
)

__all__ = ["add", "get", "update", "remove", "list_interests", "profile", "score_text",
           "topics_for", "learn", "record_engagement", "summary", "InterestError",
           "AriesInterest", "WANT", "AVOID", "Matchable", "Relevance", "normalise",
           "matching", "service"]
