"""Reference workflows, registered on import.

plan_execute_verify — the generic task shape:
    research (gate: has_brief) → plan → execute → review → repair (gate: review found errors)
This is the marketing campaign graph (orchestration/campaign.py) with the
marketing agents replaced by the generic roster; the repair node's DYNAMIC gate
is exactly the property the original tests pin.
"""
from __future__ import annotations

from agentic_core.evaluators import deterministic as det
from agentic_core.workflows.spec import NodeSpec, WorkflowSpec, register

PLAN_EXECUTE_VERIFY = register(WorkflowSpec(
    name="plan_execute_verify",
    description="research → plan → execute → review → repair(if errors)",
    nodes=[
        NodeSpec("research", "Research", agent="researcher", gate="has_brief"),
        NodeSpec("plan", "Plan", agent="planner", depends_on=["research"], gate="caller_allows"),
        NodeSpec("execute", "Execute", agent="executor", depends_on=["plan"], writes="result"),
        NodeSpec("review", "Review", evaluators=[det.not_empty("content"), det.length(soft=4000, hard=20000, field="content")],
                 depends_on=["execute"]),
        NodeSpec("repair", "Repair", agent="repairer", depends_on=["review"], gate="review_found_errors", writes="result"),
    ]))

DIRECT = register(WorkflowSpec(
    name="direct", description="execute → review only",
    nodes=[NodeSpec("execute", "Execute", agent="executor", writes="result"),
           NodeSpec("review", "Review", evaluators=[det.not_empty("content")], depends_on=["execute"])]))
