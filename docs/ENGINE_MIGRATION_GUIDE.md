# MIGRATION GUIDE — from the marketing orchestration to an Agentic Linux Operating Environment

Goal: agents that execute Linux tasks, inspect system state, evaluate results, and automatically repair/retry — using the same orchestration the marketing system uses to research, write, review, repair, approve and publish. Nothing was redesigned: the mechanisms below are the marketing ones with the nouns changed. `examples/linux_agent/` is a working starter; this guide says what maps to what and what you still have to decide.

## 1. The mapping

| Marketing concept (original file) | What it is | Linux equivalent (core module / example) |
|---|---|---|
| Campaign (`models.Campaign`, `api/campaigns.py`) | one unit of work with an approval lifecycle | `Task(kind="linux.repair"|"linux.inspect")` — `orchestrator/service.py` |
| CampaignTarget per platform | one side-effecting action per channel | one `ExecutionStep` per shell command in a resumable plan — `orchestrator/dag.py` |
| product facts (price, stock) | ground truth the copy must respect | facts the inspector read (`df`, `systemctl is-active`, journal) — `ctx["facts"]` |
| Research agent | gather facts before writing | `linux.inspector` (read-only tools, bounded tool loop) |
| Strategy agent | decide objective/angle/per-platform brief | `linux.planner` (objective, minimal reversible steps, verify checks, risk, needs_human) |
| Copy agent (per platform) | produce the deliverable | the plan's steps executed as guarded tool calls (`linux.exec`, `linux.service_restart`) |
| Reviewer (`review.py`) — hard errors block | deterministic QA | `EVALUATORS`: execution (exit codes, uncertainty) + `expected_state("verification")` running the plan's read-only checks |
| AI lector (advisory) | second opinion | `linux.verifier` / `evaluators/judge.make_judge` (optional) |
| `gate_and_repair` (regenerate with corrective note) | self-correction | lifecycle RETRY with `corrective_note`; REPLAN hands the failed checks back to the planner |
| `execution/errors.py` taxonomy | retry safety | identical (`orchestrator/errors.py`): a timed-out `apt-get` is `uncertain`, a `command not found` is `validation` → replan, `permission denied` is `auth` → escalate |
| `execution/operations.py` idempotency | never publish twice | never run the same mutation twice: key = tool + payload + task |
| `execution/dag.py` staged Meta post | resume, not restart | a repair plan crashes at step 3 → the retry runs step 3 only |
| `POSTING_TEST_MODE` / `LIVE_PLATFORMS` | dry-run / live allowlist | `DRY_RUN` / `LIVE_TOOLS` (`security/…`, `POST /api/environment/go-live`) |
| `policy/engine.py` (out of stock, 8 publishes/hour) | deterministic gate | `security/policy.py` (hourly cap, risk tier) + `sandbox.py` denylist/allowlist — add rules like "no writes under /etc without approval" |
| Telegram/WhatsApp approval, `ActionProposal` | human in the loop | same tables and API (`/api/proposals`); plug a Telegram notifier into `register_kind(notify=…)` |
| Reklama5 quota (`posting/quota.py`) | per-site budget | `MAX_ACTIONS_PER_HOUR`, per-tool caps you add to policy |
| `triggers.py` (price drop → campaign) | event-driven work | `scheduler/triggers.py`: disk ≥ 92% → `linux.repair`; unit failed → `linux.repair` (`examples/linux_agent/workflow.py`) |
| Autopilot (daily brief) | self-proposed work | `autopilot_pass()` reads disk/services and records events; the `triggers` worker turns them into tasks |
| Scheduler (quiet hours, backoff, caps) | when work may run | `scheduler/scheduled.py` — e.g. no restarts in business hours = quiet hours |
| Feedback → StyleGuide (nightly) | learning from corrections | `Feedback` on rejected/edited plans → `LearnedRule(scope="linux.planner")` injected into the planner |
| Context layer (`backend/context/*`) | what the team knows now | write the host inventory, maintenance windows, known-flaky units as context docs; every agent reads the digest |
| Vector memory (RAG) | long-term recall | remember incidents and their fixes; `recall_context` before planning |
| Audit, trace, metrics, health | observability | identical |
| `dbguard` / `APP_ENV` | never destroy the wrong database | identical; plus the sandbox denylist for the host itself |

## 2. The Linux lifecycle, step by step (`examples/linux_agent/workflow.py`)

```
TASK        Task(kind="linux.repair", brief="Mount /var is at 97% — free space safely")
EXECUTION   execute(task, ctx):
              inspector  → facts (read-only tools only, ≤8 calls)          [AgentStep]
              planner    → {objective, steps[{tool, payload}], verify[], risk, needs_human}
              needs_human or no steps → result{success:false, requires_approval}  → ESCALATE
              run_plan(plan_key=linux:<task>:<hash(steps)>, StepSpec per command)
                 each step = call_tool(...) through dry-run → live gate → policy → approval → idempotency
RESULT      {success, uncertain, plan, execution{state, steps[...]}}
EVALUATION  execution evaluator (uncertain → error; step failed → error(replan))
            expected_state("verification"): run every plan.verify command (read-only), match expect_regex
VERDICT     pass → done (or awaiting_approval when plan.risk == high)
            step_failed / verification mismatch → REPLAN: inspect again, plan again (≤2), execute again
            uncertain (a mutation timed out) → RECONCILE: proposal for a human, never re-run
            policy/auth/unknown/exhausted → ESCALATE: proposal + audit + notify
```

Try it (dry-run, no model):
```bash
AGENTIC_APP=examples.linux_agent scripts/start.sh
curl -s -X POST localhost:8000/api/events -H 'content-type: application/json' -d '{"kind":"disk","subject":"/var","data":{"pct":97}}'
curl -s -X POST localhost:8000/api/events/propose            # → a linux.repair task
curl -s -X POST localhost:8000/api/tasks/1/run               # inspector → planner(needs_human without a model) → escalation proposal
curl -s localhost:8000/api/proposals
```
With a model (`AI_PROVIDER=cli` + a logged-in `the reviewing agent`/`codex`, or `ollama`, or `openai`), the planner returns real steps; keep `DRY_RUN=true` until `/api/execution/recent` looks right, then `POST /api/environment/go-live {"dry_run": false, "live_tools": "linux.service_restart"}` — one tool at a time, exactly as the marketing system unlocked one platform at a time after a rehearsal.

## 3. What to keep exactly as it is

* The lifecycle's decision table (`orchestrator/lifecycle._decide`) and the taxonomy — they encode incidents the original paid for (a "failed" that was really "live", a retry that double-posted).
* `sent` before the call; `uncertain` never auto-retried; recovery marks in-flight work `uncertain`.
* Deterministic checks as the backbone; the judge only adjusts.
* The two-switch live gate and the proposal gate for high risk.
* Workers paced by last run; no external scheduler process.
* Honest observability rules.

## 4. What you must add for Linux (not in the core by design)

1. **Verification predicates** for your fixes (`evaluators/deterministic.expected_state`): "unit active", "disk < N%", "port listening", "file has mode X". The planner's `verify[]` covers the generic case; hard-code the important ones.
2. **Your mutation allowlist** (`examples/linux_agent/settings.py::linux_mutation_allowlist`) and extra `sandbox.DANGEROUS` patterns for your hosts. Everything not allowlisted is refused and escalated, never guessed.
3. **Policy rules** (`@policy.rule`): maintenance windows, "no apt on production before 18:00", per-host caps.
4. **A notifier** (`register_kind(notify=…)`): the original's Telegram channel (`examples/marketing/backend/app/services/telegram/__init__.py`) is a 200-line httpx module you can port as-is; the long-poll worker (`telegram_worker.py`) shows the offset-cursor pattern (`memory/checkpoints`).
5. **Remote hosts**: `linux.exec` runs locally. For a fleet, implement a `Connector` (`tools/connectors.py`) per host/agent (SSH, an agent daemon) with `capabilities()` read from what is actually reachable, and route by target name — the marketing `connectors/registry.py` pattern.
6. **Eval cases** (`POST /api/evals/cases`): snapshot real incidents (facts + expected outcome) so a prompt change is measured, not felt — the original's `evals/seed.py` deliberately includes temptations (an out-of-stock product); yours should include "a fix that must NOT be applied".
7. **Reconciliation probes**: for an `uncertain` step (a restart that timed out), a read-only probe (`systemctl is-active`) + `POST /api/execution/plans/{key}/steps/{step}/reconcile` closes the loop without a human where evidence exists.

## 5. Migration checklist

- [ ] `pip install -r requirements.txt`, `scripts/run_tests.sh` green.
- [ ] Copy `examples/linux_agent` to your package; rename kinds/tools; set `AGENTIC_APP`.
- [ ] Write the verification predicates and the allowlists; add policy rules.
- [ ] Pick a provider; keep `REQUIRE_AI=false` until the fallbacks are what you want when the model is down.
- [ ] Port the Telegram notifier + long-poll worker if approvals happen on a phone.
- [ ] Seed eval cases from past incidents; run `/api/evals/run` before every prompt change.
- [ ] Turn off `DRY_RUN`, then add tools to `LIVE_TOOLS` one at a time after reading `/api/execution/recent`.
- [ ] Production: set `API_KEY`, `SECRET_KEY`, `CREDENTIALS_KEY`, `APP_ENV=production`; mint per-person tokens with roles (approver ≠ executor).
