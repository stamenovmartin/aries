"""Settings the News Radar adds. The user-facing news.* keys were defined in
Entry 002; these are the mechanical limits of fetching."""
from __future__ import annotations

from aries.settings.schema import SettingDef, define

S = "news"

define(SettingDef("news.max_items_per_source", int, 50, "Items per source",
                  "How many entries to take from one feed in a single pass.",
                  S, control="number", minimum=1, maximum=500, unit="items", advanced=True))
define(SettingDef("news.max_age_hours", float, 72.0, "Ignore items older than",
                  "Entries published longer ago than this are not treated as news.",
                  S, control="number", minimum=1.0, maximum=8760.0, unit="hours"))
define(SettingDef("news.fetch_timeout_seconds", float, 20.0, "Fetch timeout",
                  "How long to wait for one source before giving up on it.",
                  S, control="number", minimum=1.0, maximum=120.0, unit="seconds", advanced=True))
define(SettingDef("news.max_bytes_per_source", int, 4_000_000, "Maximum download",
                  "Largest response ARIES will read from one source. Anything beyond this is "
                  "truncated rather than buffered.",
                  S, control="number", minimum=10_000, maximum=50_000_000, unit="bytes", advanced=True))
define(SettingDef("news.duplicate_threshold", float, 0.6, "Duplicate sensitivity",
                  "How similar two headlines must be, from 0 to 1, to count as the same story.",
                  S, control="slider", minimum=0.3, maximum=1.0, advanced=True))
define(SettingDef("news.max_sources_per_pass", int, 25, "Sources per pass",
                  "How many sources to read in one pass, in priority order.",
                  S, control="number", minimum=1, maximum=200, unit="sources", advanced=True))

define(SettingDef("news.max_per_source_in_briefing", int, 3, "Most items from one source",
                  "How many items a single source may contribute to one briefing. A prolific "
                  "source otherwise crowds out every other one: a first live run delivered 9 of "
                  "10 items from a single feed, which is a worse briefing than a mixed 10 even "
                  "though every item scored higher. 0 means no limit.",
                  S, control="number", minimum=0, maximum=100, unit="items"))

define(SettingDef("news.local_summaries", bool, False, "Macedonian local summaries",
                  "Summarize selected briefing items locally; cache results and retain originals on failure.",
                  S, control="toggle"))
