"""What ARIES keeps, for how long, and what would break if it did not.

THE RULE, IN ONE ANALOGY
-----------------------
A browser opens a page, you read it, you close it, and the page is gone. What
survives is a bookmark — not the HTML. ARIES should work the same way: it pulls
in mail, files and pages to do a piece of work, uses them, and discards them.
What persists is the conclusion and enough provenance to answer *"where did you
get that?"*.

Without this, the first thing an Operator does when it reads your mail is start
a hoard: message bodies in a SQLite file, forever, because nothing ever said to
remove them. `automation_logs` was already the largest table in the database
before ARIES had read a single personal thing.

FIVE CLASSES, AND THE POINT OF EACH
-----------------------------------
    working      the context pulled in to do one task. Deleted when the task
                 ends, not on a timer — its lifetime is the task's.
    operational  logs, samples, runs. Useful for a window, then noise.
    memory       what ARIES concluded. Kept until the user removes it.
    provenance   a small pointer back to where a memory came from. Lives exactly
                 as long as the memory it supports.
    audit        the record of what ARIES did. NEVER deleted automatically —
                 §29 requires that nothing ARIES does be invisible, and a
                 retention policy that quietly erases the evidence of its own
                 deletions is the one policy nobody could trust.

THE PART THAT IS EASY TO GET WRONG
----------------------------------
Deleting a row another subsystem reads. The circuit breaker decides whether an
automation is broken by reading its run history; the learning loop measures
engagement from news items; health baselines are computed from samples. Delete
those too eagerly and a subsystem does not fail — it quietly starts answering
differently, which is worse.

So every policy names its dependants, and the minimum window that keeps them
correct. A retention that would starve a dependant is refused rather than
applied, which is why `minimum_days` exists and is not merely advisory.
"""
from __future__ import annotations

from dataclasses import dataclass, field

WORKING = "working"
OPERATIONAL = "operational"
MEMORY = "memory"
PROVENANCE = "provenance"
AUDIT = "audit"


# The vocabulary itself, so no screen has to hard-code what a class means or
# invent its own wording for it. Same reason the power classes are described in
# one place: two explanations of the same idea eventually disagree.
CLASSES: tuple[dict, ...] = (
    {"kind": WORKING, "title": "Working",
     "meaning": "What ARIES is reading right now to do one task. Released when "
                "the task ends, whatever the outcome."},
    {"kind": OPERATIONAL, "title": "Operational",
     "meaning": "Logs, samples and runs. Useful for a window, then noise."},
    {"kind": MEMORY, "title": "Memory",
     "meaning": "What ARIES concluded, and what you told it. Kept until you "
                "remove it — a preference that expired is not a preference."},
    {"kind": PROVENANCE, "title": "Provenance",
     "meaning": "Where a memory came from. Lives exactly as long as the memory "
                "it supports."},
    {"kind": AUDIT, "title": "Audit",
     "meaning": "The record of what ARIES did, including its own deletions. "
                "Never removed automatically."},
)


@dataclass(frozen=True)
class Retention:
    """One class of data, and the honest reason for its lifetime."""

    table: str
    kind: str
    reason: str                      # why this long, in a sentence a person reads
    timestamp_column: str = "created_at"
    setting: str | None = None       # the settings key holding the window, in days
    default_days: int | None = None  # None means "kept until the user removes it"
    # Who reads this table, and the shortest window that keeps them correct.
    # Not documentation: `service.apply` refuses a window below the minimum.
    dependants: tuple[str, ...] = field(default_factory=tuple)
    minimum_days: int = 0

    @property
    def forever(self) -> bool:
        return self.default_days is None

    def as_dict(self) -> dict:
        return {"table": self.table, "kind": self.kind, "reason": self.reason,
                "setting": self.setting, "default_days": self.default_days,
                "dependants": list(self.dependants), "minimum_days": self.minimum_days,
                "forever": self.forever}


# ── the register ────────────────────────────────────────────────────────────
# Everything ARIES writes appears here. A table absent from this list is a table
# nobody decided about, which a test refuses to allow.

POLICIES: tuple[Retention, ...] = (
    Retention("aries_intelligence_events", OPERATIONAL, "Routing, usage and outcome telemetry without raw prompts.", dependants=("intelligence cost and routing statistics",), default_days=30, minimum_days=1),
    Retention("aries_routing_cache", OPERATIONAL, "Verified safe routing hints; never executable actions.", dependants=("exact command routing cache",), default_days=7, minimum_days=1),
    Retention("aries_workspace_goals", OPERATIONAL, "Submitted goals and their dashboard results.", default_days=30, minimum_days=1, dependants=("goal execution and related context",)),
    Retention("aries_workspace_memories", MEMORY, "What the user said, verbatim and in their own language; removable by the user, and expired rather than deleted."),
    Retention("aries_workspace_conclusions", MEMORY, "What ARIES concluded from those utterances, with its confidence and rationale; withdrawn by supersession, never deleted."),
    Retention("aries_workspace_conclusion_sources", PROVENANCE, "Which utterances a conclusion was drawn from. Lives exactly as long as the conclusion it explains — a conclusion that cannot be explained may not exist."),
    # ── working: the task's lifetime, not a timer's ─────────────────────────
    #
    # This one is in the register for the same reason as everything else — so
    # that no table is undecided — but it is the only entry whose window is not
    # measured in days. A working set is released when its task reaches any
    # terminal outcome; the age exists solely to collect what a crashed task
    # could not release itself.
    Retention(
        "aries_working_set", WORKING,
        "Context pulled in to do one task — mail bodies, file contents, pages. "
        "Released when the task ends, whatever the outcome. What is left after "
        "that belongs to a task that died mid-flight.",
        dependants=("resuming an interrupted task",), default_days=None),

    # ── operational: useful for a window, then noise ────────────────────────
    Retention(
        "automation_logs", OPERATIONAL,
        "Line-by-line output of automation runs. Worth having while diagnosing "
        "something that just went wrong; worthless a fortnight later, and by far "
        "the fastest-growing table in the database.",
        setting="data.keep_automation_logs_days", default_days=14,
        dependants=("the Automations screen's last-run detail",), minimum_days=2),

    Retention(
        "aries_health_samples", OPERATIONAL,
        "Individual probe readings. Baselines are computed from them, so the "
        "window has to cover the longest baseline ARIES learns over.",
        timestamp_column="recorded_at",
        setting="data.keep_health_samples_days", default_days=90,
        dependants=("health baselines", "the System screen's trend"), minimum_days=30),

    Retention(
        "aries_news_items", OPERATIONAL,
        "Articles ARIES collected, with what it delivered and held. The medium "
        "learning loop measures engagement from these, so deleting them early "
        "does not break it — it quietly makes it learn from less.",
        timestamp_column="first_seen_at",
        setting="data.keep_news_days", default_days=45,
        dependants=("the medium learning loop", "duplicate detection"), minimum_days=21),

    Retention(
        "aries_notifications", OPERATIONAL,
        "Delivery decisions, including the ones held back. Kept long enough to "
        "answer 'why did you not tell me about this?'.",
        setting="data.keep_notifications_days", default_days=60,
        dependants=("the repeat gate", "the notification history"), minimum_days=14),

    Retention(
        "aries_automation_runs", OPERATIONAL,
        "One row per run. The circuit breaker decides whether an automation is "
        "broken by reading these, and pacing reads the last one — so this window "
        "is a correctness constraint, not a preference.",
        timestamp_column="started_at",
        setting="data.keep_automation_runs_days", default_days=90,
        dependants=("the circuit breaker", "automation pacing", "health()"),
        minimum_days=30),

    Retention(
        "aries_resource_events", OPERATIONAL,
        "When the resource policy refused heavy work or let go again. The policy "
        "reads the most recent row per class to know whether a hold is active.",
        timestamp_column="at",
        setting="data.keep_resource_events_days", default_days=90,
        dependants=("the resource policy's active holds",), minimum_days=7),

    Retention(
        "tasks", OPERATIONAL,
        "The engine's task records. Kept as long as the runs that reference them.",
        setting="data.keep_task_history_days", default_days=90,
        dependants=("task traces in the Control Centre",), minimum_days=14),

    Retention(
        "task_runs", OPERATIONAL,
        "One execution of a task, with its verdict.",
        timestamp_column="started_at",
        setting="data.keep_task_history_days", default_days=90,
        dependants=("task traces", "evaluation history"), minimum_days=14),

    Retention(
        "agent_steps", OPERATIONAL,
        "What an agent did inside a run. The most verbose thing ARIES writes, "
        "and the least useful once the run is old.",
        timestamp_column="at",
        setting="data.keep_task_history_days", default_days=90,
        dependants=("task traces",), minimum_days=7),

    # ── memory: kept until the user removes it ──────────────────────────────
    Retention("aries_settings", MEMORY,
              "What the user chose, and what ARIES inferred. Deleting a setting "
              "on a timer would mean preferences that expire.", default_days=None),
    Retention("aries_interests", MEMORY,
              "The interest profile. The whole point is that it persists.",
              default_days=None),
    Retention("aries_sources", MEMORY,
              "Where the user told ARIES it may look.", default_days=None),
    Retention("aries_learning_changes", MEMORY,
              "Every change the learning loop made, so 'why do you think that?' "
              "has an answer for as long as the belief exists.", default_days=None),
    Retention("aries_reversals", MEMORY,
              "Where ARIES changed its own mind, and on what evidence.",
              timestamp_column="first_seen_at", default_days=None),
    Retention("aries_feedback", MEMORY,
              "What the user said to ARIES. Corrections are the most valuable "
              "data in the system and are never discarded on a schedule.",
              default_days=None),
    Retention("aries_briefs", MEMORY,
              "Past briefings. Small, and occasionally worth looking back at.",
              default_days=None),

    # ── the engine's own tables ─────────────────────────────────────────────
    #
    # Found by the test that refuses to let a table go undecided: seventeen
    # tables belonging to `agentic_core` had no policy at all. They are empty
    # today, which is exactly why it was easy to miss — and `stored_credentials`
    # and `memory_items` are the two tables in this system that most need a
    # decision written down before anything starts filling them.

    Retention("stored_credentials", MEMORY,
              "Encrypted secrets for connected services. Never on a timer: a "
              "credential that expired because a cleaner ran would break a "
              "connection with no explanation. Revocation removes these, not age.",
              default_days=None),
    Retention("memory_items", MEMORY,
              "What ARIES was told to remember. The thing a person would be "
              "most upset to lose silently.", default_days=None),
    Retention("learned_rules", MEMORY,
              "Rules distilled from feedback — the same standing as a preference.",
              default_days=None),
    Retention("feedback", MEMORY,
              "The engine's feedback records. Corrections are never discarded on "
              "a schedule.", default_days=None),
    Retention("users", MEMORY, "Accounts.", default_days=None),
    Retention("api_tokens", MEMORY,
              "Issued tokens. Removed by revoking them, not by age — a token "
              "that vanished on a timer is an outage nobody can diagnose.",
              default_days=None),
    Retention("eval_cases", MEMORY,
              "The evaluation task set. It is a dataset, and a dataset that "
              "expires makes every past result unreproducible.", default_days=None),

    Retention("action_proposals", OPERATIONAL,
              "Things ARIES asked a human about. Expired proposals are already "
              "closed by housekeeping; this removes the closed ones eventually.",
              setting="data.keep_task_history_days", default_days=90,
              dependants=("the decisions history",), minimum_days=30),
    Retention("approval_requests", OPERATIONAL,
              "Approval decisions, kept alongside the proposals they belong to.",
              timestamp_column="requested_at",
              setting="data.keep_task_history_days", default_days=90,
              dependants=("the decisions history",), minimum_days=30),
    Retention("scheduled_tasks", OPERATIONAL,
              "Work the scheduler was asked to run. Completed rows are history.",
              setting="data.keep_task_history_days", default_days=90,
              dependants=("the scheduler's crash sweep",), minimum_days=7),
    Retention("execution_plans", OPERATIONAL,
              "Resumable plans. Kept well past any plan's lifetime so an "
              "interrupted one is never cleaned out from under itself.",
              setting="data.keep_task_history_days", default_days=90,
              dependants=("plan resumption", "at-most-once replay"), minimum_days=30),
    Retention("execution_steps", OPERATIONAL,
              "Steps within a plan.", setting="data.keep_task_history_days",
              default_days=90, dependants=("plan resumption",), minimum_days=30),
    Retention("execution_operations", OPERATIONAL,
              "Side effects, with their at-most-once keys. The window must "
              "outlive any retry, or a replay could repeat an effect.",
              setting="data.keep_task_history_days", default_days=90,
              dependants=("at-most-once semantics",), minimum_days=30),
    Retention("artifacts", OPERATIONAL,
              "Files produced by a run.", setting="data.keep_task_history_days",
              default_days=90, dependants=("task traces",), minimum_days=14),
    Retention("chat_messages", OPERATIONAL,
              "Conversation turns. The working-set rule in another form: the "
              "exchange is worth less than what was concluded from it.",
              setting="data.keep_task_history_days", default_days=90,
              dependants=("conversation history",), minimum_days=7),
    Retention("eval_runs", OPERATIONAL,
              "One execution of the evaluation set.", setting="data.keep_task_history_days",
              default_days=90, dependants=("experiment results",), minimum_days=30),
    Retention("eval_results", OPERATIONAL,
              "Per-case results of an evaluation run.",
              setting="data.keep_task_history_days", default_days=90,
              dependants=("experiment results",), minimum_days=30),

    # ── audit: never automatically ──────────────────────────────────────────
    Retention("audit_events", AUDIT,
              "The record of every consequential act. Never deleted on a timer: "
              "§29 requires that nothing ARIES does be invisible, and a cleaner "
              "that erased the evidence of its own deletions would be the one "
              "part of this system nobody could check.",
              timestamp_column="at", default_days=None),
)

BY_TABLE = {p.table: p for p in POLICIES}


def get(table: str) -> Retention | None:
    return BY_TABLE.get(table)


def describe() -> list[dict]:
    return [p.as_dict() for p in POLICIES]
