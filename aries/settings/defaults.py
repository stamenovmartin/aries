"""The settings ARIES ships with — sections GENERAL, AI, NEWS, NOTIFICATIONS,
PRIVACY and AUTONOMY of specification section 20, plus the autonomy presets of
section 33.

Importing this module registers the definitions. It holds no values: a default
here is the DEFAULT layer, the weakest one, so every entry below is a starting
point the user or a learning loop can outrank.

Each definition carries the sentence an agent reads to understand the knob, so a
model deciding "may I notify about this?" sees the meaning of the threshold and
not merely a float.
"""
from __future__ import annotations

from aries.settings.schema import SettingDef, define

# ── GENERAL ──────────────────────────────────────────────────────────────────
define(SettingDef("general.language", str, "en", "Language",
                  "Language ARIES writes its answers, briefings and notifications in.",
                  "general", control="select", choices=("en", "mk", "de", "fr", "es")))
define(SettingDef("general.region", str, "", "Region",
                  "Region used for local news, holidays, units and time formatting. Empty means unset.",
                  "general"))
define(SettingDef("general.timezone", str, "UTC", "Time zone",
                  "Time zone for schedules, briefings, deadlines and quiet hours.", "general"))
define(SettingDef("general.theme", str, "system", "Appearance",
                  "Visual theme of the ARIES interface.",
                  "general", control="select", choices=("system", "light", "dark")))
define(SettingDef("general.start_on_login", bool, False, "Start on login",
                  "Whether ARIES services start automatically when the user logs in.",
                  "general", control="toggle"))

# ── AUTONOMY (section 33) ────────────────────────────────────────────────────
# user_only: how much ARIES may do without asking is never something ARIES
# infers for itself. This is the single most consequential setting in the system.
define(SettingDef("autonomy.level", str, "manual", "Autonomy level",
                  "How much ARIES may do without asking. manual: agents only suggest. "
                  "assisted: low-risk actions run automatically. automated: approved "
                  "workflow categories run on their own. custom: permissions set individually.",
                  "autonomy", control="select", choices=("manual", "assisted", "automated", "custom"),
                  user_only=True))
define(SettingDef("autonomy.require_approval_risk", str, "medium", "Always ask above risk",
                  "Lowest risk tier that always requires a human approval before execution.",
                  "autonomy", control="select", choices=("low", "medium", "high"), user_only=True))
define(SettingDef("autonomy.max_actions_per_hour", int, 30, "Action budget",
                  "Maximum side-effecting actions ARIES may take in one hour before it must stop and ask.",
                  "autonomy", control="number", minimum=0, maximum=1000, unit="actions/hour", user_only=True))

# ── AI (section 20) ──────────────────────────────────────────────────────────
define(SettingDef("ai.provider_priority", list, ["cli", "ollama", "openai"], "Model priority",
                  "Order in which model providers are tried; the first reachable one is used.",
                  "ai", control="list", advanced=True))
define(SettingDef("ai.prefer_local", bool, False, "Prefer local models",
                  "Route work to a locally hosted model whenever one can do the job, for privacy.",
                  "ai", control="toggle"))
define(SettingDef("ai.reasoning_depth", str, "balanced", "Reasoning depth",
                  "How much deliberation to spend per task where the provider supports it.",
                  "ai", control="select", choices=("fast", "balanced", "thorough")))
define(SettingDef("ai.daily_cost_limit", float, 0.0, "Daily cost limit",
                  "Maximum spend on paid model calls per day. 0 means no limit is enforced.",
                  "ai", control="number", minimum=0.0, unit="USD/day", user_only=True))
define(SettingDef("ai.send_file_contents", bool, False, "Allow file contents to leave the machine",
                  "Whether a cloud model may receive the contents of local files, rather than only their names.",
                  "ai", control="toggle", user_only=True))

# Sampling — the knobs a user turns when the answers feel wrong. Every default
# below is EXACTLY what the local runtime was already sent before these existed
# (temperature 0.1, num_ctx 8192, a 4096-token output ceiling), so adding the
# panel changes no output until a slider moves. A default that shifted today's
# answers would read as a regression, not as a new feature.
define(SettingDef("ai.temperature", float, 0.1, "Temperature",
                  "How much the model gambles on less likely words. 0 is repeatable and literal; "
                  "around 0.7 is conversational; above 1.2 it invents. Structured extraction and "
                  "routing decisions are more reliable low.",
                  "ai", control="slider", minimum=0.0, maximum=2.0))
# minimum is not 0: measured on this runtime, top_p 0.0 at temperature 1.8 returns
# the greedy answer every time, so a user who dragged it to zero would find the
# temperature slider apparently dead. A setting with a dead zone is a bug report.
define(SettingDef("ai.top_p", float, 0.9, "Top-p (nucleus)",
                  "Keeps only the most likely words whose probabilities add up to this fraction. "
                  "1.0 considers everything; 0.5 keeps the model on the obvious path. Temperature "
                  "is the dial to try first — this one mostly matters above temperature 1.",
                  "ai", control="slider", minimum=0.05, maximum=1.0, advanced=True))
# user_only: raising this enlarges the KV cache and makes the local runtime
# reload the model. On a card already holding speech recognition and the model
# server, a learning loop nudging it upward is how ARIES runs out of VRAM.
define(SettingDef("ai.context_tokens", int, 8192, "Context window",
                  "How much conversation and document text the local model may hold at once. "
                  "Larger remembers more but costs video memory and reloads the model; the local "
                  "runtime, not ARIES, decides what it can fit.",
                  "ai", control="number", minimum=512, maximum=32768, unit="tokens",
                  advanced=True, user_only=True))
# Ceiling, not a request: it can only lower what a caller already asked for, so
# it cannot make a caller exceed the gateway's own 4096-token transport bound.
define(SettingDef("ai.max_output_tokens", int, 4096, "Maximum answer length",
                  "Longest answer the local model may produce in one turn. Lower it for terse "
                  "replies and faster responses; a task that needs more than it gets fails "
                  "loudly rather than returning a truncated answer.",
                  "ai", control="number", minimum=256, maximum=4096, unit="tokens"))

# ── NEWS (section 20) ────────────────────────────────────────────────────────
define(SettingDef("news.enabled", bool, False, "News Radar",
                  "Whether ARIES collects, clusters and ranks news for the user.",
                  "news", control="toggle"))
define(SettingDef("news.topics", list, [], "Topics I care about",
                  "Topics that make an article relevant. Explicit topics outrank anything ARIES infers.",
                  "news", control="multiselect"))
define(SettingDef("news.excluded_topics", list, [], "Topics to ignore",
                  "Topics that disqualify an article however well it scores otherwise.",
                  "news", control="multiselect"))
define(SettingDef("news.languages", list, ["en"], "Preferred languages",
                  "Languages an article may be written in to be considered.", "news", control="multiselect"))
define(SettingDef("news.relevance_threshold", float, 0.6, "Relevance threshold",
                  "Minimum relevance score, from 0 to 1, for an article to reach the user at all.",
                  "news", control="slider", minimum=0.0, maximum=1.0))
define(SettingDef("news.breaking_threshold", float, 0.9, "Breaking-news threshold",
                  "Relevance score above which an article interrupts the user instead of waiting for a briefing.",
                  "news", control="slider", minimum=0.0, maximum=1.0))
define(SettingDef("news.max_items_per_briefing", int, 8, "Items per briefing",
                  "Most articles to include in one briefing, after deduplication and ranking.",
                  "news", control="number", minimum=1, maximum=50, unit="items"))
define(SettingDef("news.poll_interval_minutes", int, 120, "Check frequency",
                  "How often enabled sources are polled for new material.",
                  "news", control="number", minimum=5, maximum=1440, unit="minutes"))

# ── BRIEFING (automation 01) ─────────────────────────────────────────────────
define(SettingDef("briefing.morning_enabled", bool, False, "Morning brief",
                  "Whether the Morning Intelligence Brief is produced.", "briefing", control="toggle"))
define(SettingDef("briefing.morning_time", str, "07:30", "Morning brief time",
                  "Local time the morning brief is delivered, as HH:MM.", "briefing"))
define(SettingDef("briefing.length", str, "standard", "Briefing length",
                  "How much detail a briefing carries.",
                  "briefing", control="select", choices=("headlines", "standard", "detailed")))
# Order matters and is the user's to change: the brief is rendered in this order.
# "decisions" is first because it is the only section the user is BLOCKED on —
# everything else is information, that is a queue. The original default here was
# written before any collector existed and named a section ("priorities") that
# was never built, while omitting the three that turned out to matter most.
define(SettingDef("briefing.sections", list,
                  ["decisions", "system", "news", "automations", "learning"],
                  "Briefing sections",
                  "Which sections the brief contains, in order. Available: decisions, system, "
                  "news, automations, learning, calendar, email, projects.",
                  "briefing", control="multiselect",
                  choices=("decisions", "system", "news", "automations", "learning",
                           "calendar", "email", "projects")))

# ── NOTIFICATIONS (section 26) ───────────────────────────────────────────────
define(SettingDef("notifications.minimum_level", str, "important", "Notify me about",
                  "Lowest notification level that reaches the user immediately. Anything below it "
                  "is held for the next briefing or only logged.",
                  "notifications", control="select", choices=("critical", "important", "briefing", "background")))
define(SettingDef("notifications.quiet_hours_start", str, "22:00", "Quiet hours start",
                  "Time after which only critical notifications interrupt, as HH:MM.", "notifications"))
define(SettingDef("notifications.quiet_hours_end", str, "07:00", "Quiet hours end",
                  "Time at which normal notifications resume, as HH:MM.", "notifications"))
define(SettingDef("notifications.channels", list, ["desktop"], "Delivery channels",
                  "Where notifications are delivered.",
                  "notifications", control="multiselect", choices=("desktop", "telegram", "email")))

# ── PRIVACY ──────────────────────────────────────────────────────────────────
define(SettingDef("privacy.mode", bool, False, "Privacy mode",
                  "When on, ARIES avoids cloud models and external calls wherever a local path exists.",
                  "privacy", control="toggle", user_only=True))
define(SettingDef("privacy.remember_conversations", bool, True, "Remember conversations",
                  "Whether useful facts from conversations may become long-term memory.",
                  "privacy", control="toggle", user_only=True))
define(SettingDef("privacy.excluded_paths", list, ["~/.ssh", "~/.gnupg"], "Never read these paths",
                  "Filesystem paths ARIES must never read, index or send anywhere.",
                  "privacy", control="list", user_only=True))
define(SettingDef("privacy.excluded_memory_topics", list, [], "Never remember these topics",
                  "Topics that must never be written to memory, however useful they seem.",
                  "privacy", control="list", user_only=True))
