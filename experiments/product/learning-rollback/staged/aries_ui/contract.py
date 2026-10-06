"""What the Control Centre needs from ARIES, declared as data.

Pure data — no GTK import — so it can be read from both sides: by the UI, and by
the ARIES test suite running in the virtual environment.

WHY THIS EXISTS
---------------
The UI and ARIES are separate processes on separate interpreters (ADR-0004), so
nothing but this file connects their expectations. That gap is real: during
development the learning evidence endpoint changed shape when reversal detection
sliced it by time and source, the UI still read the old flat keys, and the
Learning screen rendered an error page. Nothing failed until a human looked.

So the dependency is declared, and a test in the ARIES suite asserts that every
endpoint listed here exists and returns the keys the UI reads. The contract
breaks in CI rather than in front of the user.
"""
from __future__ import annotations

# endpoint → the keys the UI reads from its response.
# "a.b" means "key b inside object a"; "a[].b" means "key b in each item of list a".
READS: dict[str, tuple[str, ...]] = {
    "/api/aries/analytics": ("metrics", "window", "timing", "failed_metrics", "honesty"),
    "/api/aries/workspace/applications": ("installed", "catalogue[].id", "catalogue[].package"),
    "/api/aries/workspace/telemetry": ("measured_at", "probes"),
    "/api/aries/workspace": ("goals", "memories", "web_search", "capabilities[].id", "capabilities[].example"),
    "/api/aries/home": (
        "status.healthy", "status.automations_enabled", "status.automations_total",
        "decisions[].id", "decisions[].kind", "decisions[].title", "decisions[].risk",
        "notifications[].title", "notifications[].severity", "notifications[].source",
        "health.ran", "health.summary", "health.findings", "health.probes",
        "automations[].automation_id", "automations[].name", "automations[].enabled",
        "learned[].topic", "learned[].learned", "learned[].user",
    ),
    "/api/aries/automations": (
        "automations[].automation_id", "automations[].name", "automations[].enabled",
        "automations[].version", "automations[].purpose", "automations[].risk",
        "automations[].next_run", "automations[].due_reason", "automations[].interval_minutes",
        "automations[].permissions", "automations[].agents", "automations[].tools",
        "automations[].health", "automations[].last_run", "automations[].evolution_history",
        "automations[].rollback_version", "automations[].trigger",
        "worker.switch_on", "worker.state", "worker.means",
    ),
    "/api/aries/interests": (
        "interests[].topic", "interests[].stance", "interests[].weight",
        "interests[].weight_source", "interests[].user_weight", "interests[].learned",
        "interests[].synonyms", "interests[].engagement",
        "summary.learned", "summary.shadowed",
    ),
    "/api/aries/settings": (
        "settings[].key", "settings[].value", "settings[].type", "settings[].title",
        "settings[].description", "settings[].section", "settings[].control",
        "settings[].choices", "settings[].minimum", "settings[].maximum",
        "settings[].advanced", "settings[].user_only", "settings[].unit",
    ),
    "/api/aries/sources": (
        "sources[].source_id", "sources[].name", "sources[].enabled", "sources[].location",
        "sources[].location_original", "sources[].priority", "sources[].trust",
        "sources[].topics", "sources[].health", "sources[].performance",
        "sources[].last_sync", "sources[].last_error", "sources[].metadata",
    ),
    "/api/aries/sources/catalogue": (
        "categories[].id", "categories[].title",
        "entries[].id", "entries[].name", "entries[].description", "entries[].category",
        "entries[].language", "entries[].already_added",
        "unavailable[].name", "unavailable[].why",
    ),
    "/api/aries/news": (
        "items[].item_id", "items[].title", "items[].source_id", "items[].relevance",
        "items[].disposition", "items[].topics", "items[].explanation",
        "items[].excluded_by", "items[].link",
    ),
    "/api/aries/learning/evidence": (
        "minimum_observations",
        "topics[].topic", "topics[].decisive", "topics[].trend",
        "topics[].overall.shown", "topics[].overall.engaged",
        "topics[].overall.rate", "topics[].overall.lower", "topics[].overall.upper",
    ),
    "/api/aries/learning/reversals": (
        "policy_version",
        "contested[].target", "contested[].classification", "contested[].reason",
        "contested[].confidence", "contested[].believed",
        "reversals[].target", "reversals[].status", "reversals[].established",
        "reversals[].confirmations", "reversals[].required_confirmations",
        "reversals[].reason", "reversals[].interval", "reversals[].window_days",
        "reversals[].policy_version", "reversals[].resolved_at",
    ),
    "/api/aries/learning/feedback": (
        "feedback[].id", "feedback[].text", "feedback[].classification",
        "feedback[].scope", "feedback[].ambiguous", "feedback[].question",
        "feedback[].applied", "feedback[].action", "feedback[].at",
    ),
    "/api/aries/learning/preferences": (
        "means", "settings[].key", "settings[].value", "settings[].source",
        "settings[].source_label", "settings[].explicit", "settings[].rationale",
        "topics[].topic", "topics[].weight", "topics[].explicit",
    ),
    "/api/aries/health/latest": ("ran",),
    "/api/aries/brief": ("exists",),
    "/api/aries/runtime": (
        "state", "means", "summary", "installed", "enabled", "api_reachable",
        "components[].name", "components[].kind", "components[].ok",
        "components[].detail", "components[].severity",
        "process.pid", "process.started_at",
    ),
    "/api/aries/shell/status": (
        "severity", "state", "summary", "decisions", "notifications",
        "notification_severity", "health_severity", "health_findings",
        "automations_enabled", "automations_total", "next_run", "next_run_name",
        "brief_ready", "background_mode", "inhibitor_held", "autonomy",
    ),
    "/api/aries/shell/config": (
        "settings", "tokens", "control_centre",
    ),
    "/api/aries/power": (
        "background_mode", "allow_suspend", "allow_gpu_jobs", "gpu_jobs_note", "effect",
        "display.state", "display.detail", "display.off_after_seconds",
        "display.configured_minutes", "display.will_restore_to",
        "system.awake", "system.session",
        "inhibitor.available", "inhibitor.unavailable_reason", "inhibitor.active",
        "inhibitor.what", "inhibitor.mode", "inhibitor.held_by_aries",
        "inhibitor.other_sleep_blockers",
        "resources.measurement.cpu_pct", "resources.measurement.cpu_unavailable",
        "resources.measurement.gpu_pct", "resources.measurement.gpu_subject",
        "resources.measurement.gpu_unavailable",
        "resources.measurement.temperature_celsius",
        "resources.measurement.temperature_subject",
        "resources.measurement.temperature_unavailable",
        "resources.limits", "resources.display_off", "resources.running_heavy",
        "resources.classes[].name", "resources.classes[].title",
        "resources.classes[].heavy", "resources.classes[].status",
        "resources.classes[].why",
        "resources.events",
    ),
    "/api/aries/power/events": ("events",),
    "/api/aries/power/workloads": (
        "default", "classes[].name", "classes[].title", "classes[].description",
        "classes[].heavy", "classes[].permission_setting", "classes[].watches",
        "classes[].budgeted",
    ),
    "/api/aries/connect": (
        "enabled", "understand_locally", "attention_enabled",
        "keyring.available", "keyring.backend",
        "connectors[].source_type", "connectors[].outbound", "connectors[].capabilities",
        "sources[].source_id", "sources[].name", "sources[].type", "sources[].location",
        "sources[].enabled", "sources[].outbound", "sources[].capabilities",
        "sources[].last_sync", "sources[].last_error",
        "sources[].credential",
    ),
    "/api/aries/attention": (
        "ran", "needs_you", "can_wait", "injection_attempts", "not_understood",
        "sources_considered", "failures",
    ),
    "/api/aries/operator": (
        "enabled", "planner", "confirm_model_plans", "settle_seconds",
        "can_verify", "cannot_verify_why", "windows",
        "model.location", "model.name", "model.reachable", "model.has_model",
        "model.detail", "model.gpu",
        "goals[].kind", "goals[].ceiling", "goals[].why_ceiling", "goals[].params",
        "grades[].grade", "grades[].meaning",
    ),
    "/api/aries/operator/history": (
        "counts", "runs",
    ),
    "/api/aries/data": (
        "database_bytes", "would_remove",
        "tables[].table", "tables[].kind", "tables[].present", "tables[].would_remove",
        "tables[].why", "tables[].reason",
        "working_set.held", "working_set.bytes", "working_set.tasks",
        "working_set.sensitive",
        "policies[].table", "policies[].kind", "policies[].reason",
        "policies[].minimum_days", "policies[].dependants", "policies[].forever",
        "classes[].kind", "classes[].title", "classes[].meaning",
    ),
    "/api/aries/data/working-set": (
        "items[].id", "items[].task_id", "items[].label", "items[].source",
        "items[].sensitive", "items[].bytes", "items[].created_at",
    ),
    "/api/aries/connections": (
        "counts",
        "integrations[].id", "integrations[].name", "integrations[].description",
        "integrations[].category", "integrations[].status", "integrations[].detail",
        "integrations[].permissions", "integrations[].outbound",
        "integrations[].requires_credentials", "integrations[].spec_section",
        "integrations[].sources",
    ),
}

# Writes the UI performs: (method, path template). Every one must exist, and
# every one goes through the same permission and audit path as the CLI.
WRITES: tuple[tuple[str, str], ...] = (
    ("PUT", "/api/aries/settings/{key}"),
    ("DELETE", "/api/aries/settings/{key}"),
    ("POST", "/api/aries/automations/{id}/run"),
    ("POST", "/api/aries/automations/{id}/enabled"),
    ("POST", "/api/aries/interests"),
    ("PATCH", "/api/aries/interests/{topic}"),
    ("DELETE", "/api/aries/interests/{topic}"),
    ("POST", "/api/aries/sources"),
    ("POST", "/api/aries/sources/from-catalogue"),
    ("PATCH", "/api/aries/sources/{id}"),
    ("DELETE", "/api/aries/sources/{id}"),
    ("POST", "/api/aries/news/{item_id}/feedback"),
    ("POST", "/api/aries/learning/feedback"),
    ("POST", "/api/aries/learning/feedback/{id}/scope"),
    ("PUT", "/api/aries/power"),
    ("POST", "/api/aries/operator"),
    ("POST", "/api/aries/connect"),
    ("DELETE", "/api/aries/connect/{source_id}"),
    ("POST", "/api/aries/attention/run"),
    ("POST", "/api/aries/data/clean"),
    ("POST", "/api/aries/data/sweep"),
    # The command router and the shell's action route. Listed here even though
    # the caller is JavaScript in another process: the contract test is the only
    # thing that notices when an endpoint the desktop depends on changes shape.
    ("POST", "/api/aries/command"),
    ("POST", "/api/aries/shell/act"),
)


def walk(payload, path: str):
    """Resolve a dotted path with `[]` list markers. Returns (found, value)."""
    node = payload
    for part in path.split("."):
        listy = part.endswith("[]")
        key = part[:-2] if listy else part
        if not isinstance(node, dict) or key not in node:
            return False, None
        node = node[key]
        if listy:
            if not isinstance(node, list):
                return False, None
            if not node:
                return True, None          # empty list: shape unverifiable, not wrong
            node = node[0]
    return True, node

WRITES += (
    ("POST", "/api/aries/workspace"),
    ("POST", "/api/aries/workspace/{goal_id}/cancel"),
    ("POST", "/api/aries/workspace/{goal_id}/approve"),
    ("POST", "/api/aries/workspace/memories"),
    ("DELETE", "/api/aries/workspace/memories/{memory_id}"),
)

READS['/api/aries/learning/task-reviews'] = ('counts.reviewed', 'counts.useful', 'counts.needs_work', 'scope', 'reviews[].goal_id', 'reviews[].rating', 'reviews[].episode.request')
WRITES += (("POST", "/api/aries/learning/task-reviews/{goal_id}"),)

READS['/api/aries/learning/task-reviews'] += ('retrieval_version',)
READS['/api/aries/learning/controls'] = ('items[].id', 'items[].kind', 'items[].label',
    'items[].scope', 'items[].value', 'items[].revision', 'history[].id', 'history[].action',
    'history[].label', 'history[].can_undo', 'truncated', 'note')
WRITES += (("POST", "/api/aries/learning/controls/reset"),
           ("POST", "/api/aries/learning/controls/{event_id}/undo"))

WRITES += (("POST", "/api/aries/workspace/{goal_id}/recover"),)

WRITES += (("POST", "/api/aries/workspace/memory-replacements/{proposal_id}/review"),)
