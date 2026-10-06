"""The durable state of the engine.

Every table here is a generalisation of one in backend/app/models/models.py;
the mapping is in docs/MEMORY.md. Marketing tables (products, platforms,
campaign targets, metrics…) live in examples/marketing, not here.

  Task              ← Campaign             one unit of work with a lifecycle
  TaskRun           ← AgentRun             one execution of the agent chain
  AgentStep         ← AgentStep            one agent's contribution (+confidence)
  ActionProposal    ← ActionProposal       the machine's typed request to act
  ApprovalRequest   ← ApprovalRequest      the human's decision, per channel
  AuditEvent        ← AuditEvent           immutable, append-only
  ExecutionOperation← ExecutionOperation   idempotent external side effect
  ExecutionPlan/Step← ExecutionPlan/Step   resumable multi-step DAG
  ScheduledTask     ← ScheduledPost        due-queue with retry/backoff
  AutomationLog     ← AutomationLog        append-only journal (trace lives here)
  Feedback          ← Feedback             human corrections (learning signal)
  LearnedRule       ← StyleGuide           distilled rules injected into prompts
  MemoryItem        ← MemoryItem           vector memory (RAG)
  ChatMessage       ← ChatMessage          conversation history
  EvalCase/Run/Result ← same               the eval harness
  Artifact          (new)                  produced files/outputs by task
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentic_core.database.base import Base


# === Tasks ===================================================================
# Task status vocabulary is governed by orchestrator/states.py. The storage
# strings are listed here so a reader of the table knows what to expect.
TASK_STATUSES = (
    "draft", "planning", "running", "completed_unverified", "validation_failed",
    "awaiting_approval", "rejected", "approved", "scheduled", "executing",
    "partially_done", "done", "failed", "cancelled", "archived",
)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(60), index=True)          # e.g. "linux.repair", "campaign"
    title: Mapped[str] = mapped_column(String(255))
    brief: Mapped[str | None] = mapped_column(Text)                    # what was asked
    input: Mapped[str | None] = mapped_column(Text)                    # JSON: structured input
    result: Mapped[str | None] = mapped_column(Text)                   # JSON: the final output
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=2)          # 1 high · 2 med · 3 low
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    depends_on: Mapped[str | None] = mapped_column(Text)               # JSON list[int] of task ids
    assigned_agent: Mapped[str | None] = mapped_column(String(60))     # router's decision
    routing: Mapped[str | None] = mapped_column(Text)                  # JSON: how it was routed + why
    created_by: Mapped[str | None] = mapped_column(String(100), default="agent")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text)
    error_class: Mapped[str | None] = mapped_column(String(20))
    # Approval
    approval_channel: Mapped[str | None] = mapped_column(String(30))
    approval_ref: Mapped[str | None] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(100))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    runs: Mapped[list["TaskRun"]] = relationship(back_populates="task", cascade="all, delete-orphan",
                                                 order_by="TaskRun.id")
    artifacts: Mapped[list["Artifact"]] = relationship(cascade="all, delete-orphan",
                                                       order_by="Artifact.id")


class TaskRun(Base):
    """One execution of the agent chain for a task."""
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    trigger: Mapped[str] = mapped_column(String(40), default="manual")   # manual|autopilot|schedule|event|retry
    status: Mapped[str] = mapped_column(String(20), default="running")   # running|done|failed
    model: Mapped[str | None] = mapped_column(String(60))
    workflow: Mapped[str | None] = mapped_column(String(60))
    summary: Mapped[str | None] = mapped_column(Text)
    decisions: Mapped[str | None] = mapped_column(Text)                  # JSON: Director decisions
    evaluation: Mapped[str | None] = mapped_column(Text)                 # JSON: evaluator verdict
    verdict: Mapped[str | None] = mapped_column(String(20))              # pass|fail|retry|replan|escalate
    correlation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    task: Mapped["Task"] = relationship(back_populates="runs")
    steps: Mapped[list["AgentStep"]] = relationship(cascade="all, delete-orphan", order_by="AgentStep.id")


class AgentStep(Base):
    """One agent's contribution inside a run, with confidence and evidence."""
    __tablename__ = "agent_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"), index=True)
    agent: Mapped[str] = mapped_column(String(40))
    label: Mapped[str | None] = mapped_column(String(80))
    summary: Mapped[str | None] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text)        # JSON
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[str | None] = mapped_column(Text)      # JSON
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Artifact(Base):
    """A produced output attached to a task: a file, a report, a diff."""
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))            # file|text|json|screenshot|log
    name: Mapped[str] = mapped_column(String(255))
    path: Mapped[str | None] = mapped_column(String(500))    # on-disk location under data_dir
    content: Mapped[str | None] = mapped_column(Text)        # inline for small artifacts
    content_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# === Proposals and approvals =================================================

class ActionProposal(Base):
    """A structured request from the machine to do one consequential thing.
    proposed → approved | rejected | executed | expired; never straight to executed."""
    __tablename__ = "action_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("task_runs.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)     # execute_tool|publish|restart_service|…
    tool: Mapped[str | None] = mapped_column(String(60))
    target_ref: Mapped[str | None] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(String(200))
    payload: Mapped[str | None] = mapped_column(Text)             # JSON: the concrete action
    rationale: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[str | None] = mapped_column(Text)            # JSON
    risk: Mapped[str] = mapped_column(String(10), default="medium")  # low|medium|high
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    created_by: Mapped[str] = mapped_column(String(40), default="agent")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("action_proposals.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20), default="screen")   # screen|telegram|api
    decision: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    decided_by: Mapped[str | None] = mapped_column(String(80))
    note: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


# === Audit ===================================================================

class AuditEvent(Base):
    """Immutable, append-only. observability/audit.py installs a flush guard."""
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(20), index=True)   # agent|human|system|policy
    actor: Mapped[str | None] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(60), index=True)       # proposal.created|approval.granted|tool.executed…
    entity_type: Mapped[str | None] = mapped_column(String(40), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), index=True)
    detail: Mapped[str | None] = mapped_column(Text)
    before_state: Mapped[str | None] = mapped_column(Text)
    after_state: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    source_ip: Mapped[str | None] = mapped_column(String(45))
    permission: Mapped[str | None] = mapped_column(String(40))
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


# === Execution reliability (§28) ============================================

class ExecutionOperation(Base):
    """One external, side-effecting operation, tracked from intent to outcome.
    pending → sent → succeeded | failed | uncertain | skipped."""
    __tablename__ = "execution_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    operation_type: Mapped[str] = mapped_column(String(30), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str | None] = mapped_column(String(60))
    target_ref: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    external_id: Mapped[str | None] = mapped_column(String(200))
    external_url: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_class: Mapped[str | None] = mapped_column(String(20))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())


class ExecutionPlan(Base):
    """A multi-step operation, resumable by plan_key.
    pending → running → succeeded | failed | blocked."""
    __tablename__ = "execution_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_key: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    plan_type: Mapped[str] = mapped_column(String(40), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    target_ref: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())

    steps: Mapped[list["ExecutionStep"]] = relationship(cascade="all, delete-orphan",
                                                        order_by="ExecutionStep.step_index")


class ExecutionStep(Base):
    __tablename__ = "execution_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("execution_plans.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    step_index: Mapped[int] = mapped_column(Integer)
    depends_on: Mapped[str | None] = mapped_column(Text)          # JSON list[str]
    state: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    result: Mapped[str | None] = mapped_column(Text)              # JSON
    error: Mapped[str | None] = mapped_column(Text)
    error_class: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now())


# === Scheduling ==============================================================

class ScheduledTask(Base):
    """queued → processing → executing → done | failed ; guard hit → queued (rescheduled)."""
    __tablename__ = "scheduled_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    kind: Mapped[str] = mapped_column(String(20), default="initial")   # initial | rerun
    reason: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AutomationLog(Base):
    """Append-only journal every worker and agent writes one line to."""
    __tablename__ = "automation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    source: Mapped[str | None] = mapped_column(String(100), index=True)
    details: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))          # success|failure|skipped
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


# === Learning ================================================================

class Feedback(Base):
    """Every human correction: an edit (before/after) or a rejection with a reason."""
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    scope: Mapped[str | None] = mapped_column(String(100))     # which agent / domain the edit touched
    kind: Mapped[str] = mapped_column(String(20), index=True)  # edit | reject | note
    op: Mapped[str | None] = mapped_column(String(30))
    instruction: Mapped[str | None] = mapped_column(Text)
    before: Mapped[str | None] = mapped_column(Text)
    after: Mapped[str | None] = mapped_column(Text)
    sender: Mapped[str | None] = mapped_column(String(60))
    distilled_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LearnedRule(Base):
    """Distilled rules per scope ('' = global), injected back into prompts."""
    __tablename__ = "learned_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    rules: Mapped[str | None] = mapped_column(Text)             # JSON list[str]
    banned: Mapped[str | None] = mapped_column(Text)            # JSON list[str]
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str | None] = mapped_column(String(30))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class MemoryItem(Base):
    __tablename__ = "memory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    ref_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[str] = mapped_column(Text)               # JSON list[float]
    dim: Mapped[int] = mapped_column(Integer, index=True)
    backend: Mapped[str | None] = mapped_column(String(40))
    meta: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(12))              # user | bot | system
    content: Mapped[str] = mapped_column(Text)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    meta: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# === Evals ===================================================================

class EvalCase(Base):
    __tablename__ = "eval_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    agent: Mapped[str] = mapped_column(String(60), default="executor")
    input: Mapped[str | None] = mapped_column(Text)            # JSON: stable, snapshotted input
    expected: Mapped[str | None] = mapped_column(Text)         # JSON: facts the output must respect
    tags: Mapped[str | None] = mapped_column(Text)             # JSON list[str]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    judged: Mapped[bool] = mapped_column(Boolean, default=False)
    cases: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    avg_score: Mapped[float | None] = mapped_column(Float)
    dimensions: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[int | None] = mapped_column(ForeignKey("eval_cases.id", ondelete="SET NULL"))
    case_name: Mapped[str | None] = mapped_column(String(200))
    output: Mapped[str | None] = mapped_column(Text)
    scores: Mapped[str | None] = mapped_column(Text)
    overall: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# === Identity (single-tenant version of models/tenancy.py + tokens.py) =======

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="read_only")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ApiToken(Base):
    """Only the SHA-256 digest is stored; the token is shown once at creation."""
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hint: Mapped[str] = mapped_column(String(16))
    label: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


class StoredCredential(Base):
    """One credential, ciphertext only (security/crypto.py). active|pending|revoked."""
    __tablename__ = "stored_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    hint: Mapped[str] = mapped_column(String(32), default="••••")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
