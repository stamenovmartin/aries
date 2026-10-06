"""ARIES News Radar — §13/03.

Importing this package registers the settings, the table, the workflow, the task
kind and the automation genome.
"""
from __future__ import annotations

from aries.news import settings as _settings  # noqa: F401
from aries.news.automation import AUTOMATION_ID, EVALUATORS, SPEC, TASK_KIND, WORKFLOW
from aries.news.dedupe import Candidate, Cluster, cluster, similarity
from aries.news.feed import Feed, FeedError, FeedItem, clean, parse
from aries.news.fetch import FetchRefused, FetchResult, address_reason, fetch
from aries.news.models import AriesNewsItem, fingerprint

__all__ = ["SPEC", "TASK_KIND", "WORKFLOW", "AUTOMATION_ID", "EVALUATORS",
           "fetch", "FetchResult", "FetchRefused", "address_reason",
           "parse", "Feed", "FeedItem", "FeedError", "clean",
           "cluster", "Cluster", "Candidate", "similarity",
           "AriesNewsItem", "fingerprint"]
