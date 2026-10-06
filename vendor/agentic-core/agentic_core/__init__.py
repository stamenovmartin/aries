"""agentic_core — the reusable orchestration engine extracted from the Insomnia
Marketing OS backend.

Nothing in this package knows what a campaign, a product or a social platform
is. The vocabulary is Task / Agent / Tool / Evaluation / Approval, and every
module carries a note saying which file of the original backend it was lifted
from, so the two can be read side by side.

Sub-packages (see docs/ARCHITECTURE.md):

  config         settings (env-backed) + runtime overrides (file-backed)
  database       engine, models, schema bootstrap, drop-guard
  orchestrator   Director graph, resumable DAG, idempotent operations,
                 error taxonomy, state machines, retry/replan/escalate lifecycle
  router         rule-based → LLM-based → fallback task routing
  agents         agent specs, registry, and the run loop
  llm            provider abstraction (CLI agent / Ollama / OpenAI-compatible /
                 template), structured output, cache, telemetry
  tools          tool registry, capability-declaring connectors, guarded calls
  evaluators     deterministic checks, weighted scorers, LLM judge, gate+repair
  workflows      declarative workflow specs run through the Director
  memory         context layer (short-term), vector memory (long-term),
                 feedback distillation, chat history, checkpoints, recovery
  scheduler      in-process workers, due-queue with retry/backoff, triggers
  security       RBAC, principal, credential crypto, secret store,
                 environments, sandbox, approvals, policy engine
  observability  JSON logging with redaction, correlation ids, metrics,
                 immutable audit log, agent trace
  api            FastAPI surface with correlation → auth → audit middleware
"""

__version__ = "1.0.0"
