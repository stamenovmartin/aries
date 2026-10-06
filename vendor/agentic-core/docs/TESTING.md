# TESTING

## Layout

```
agentic-core/tests/
  _harness.py            bootstrap(name): APP_ENV=test, own sqlite file, DATA_DIR, template provider, dry-run
  run_tests.py           every test file in its own process (the original run_tests.py pattern)
  test_states.py         the 4 invariants, aliases, rollup, edit-revokes-approval
  test_errors.py         taxonomy; with_retry retries only transient
  test_operations_dag.py idempotency (done/reconcile/execute), resume-not-restart, uncertain blocks, reconcile_step
  test_graph.py          Director: dependency order, skip propagation, dynamic repair gate, failed node, parallel levels
  test_evaluators.py     hard-error cap, judge adjusts but never overrides, expected_state → replan, scorer suite, gate_and_repair
  test_lifecycle.py      pass · retry with corrective note · retry exhausted → proposal · replan · policy → escalate · uncertain → reconcile · require_approval
  test_tools.py          9 gates in order, idempotent re-call, approval flow, policy frequency cap, sandbox rules, RBAC on tools
  test_router.py         rules → LLM → fallback, confidence, kind wins, needs_human
  test_scheduler.py      quiet hours, approval gate, claim, retry/backoff, deferral ≠ outcome, dead letter, triggers cooldown
  test_memory.py         context layer digest, vector recall, feedback distill + rules context, chat history, cursors
  test_security.py       permissions table, crypto (refusal, roundtrip, AAD, tamper), secret store rotation/revoke, audit immutability, redaction
  test_workflow_agents.py agent fallback + describe, workflow with dynamic repair, run_task_now through the lifecycle
  test_api.py            end to end over ASGI: health, roster, route, plan preview, task create+run, dry-run tool, audit, 401/403 with a read-only token
examples/linux_agent/test_linux_agent.py   the Linux starter end to end (dry-run, template provider)
```

## Rules inherited from the original

* Every test declares `APP_ENV=test` and its own `DATABASE_URL` BEFORE importing the engine (`setdefault` is not enough in a container).
* `drop_all` is refused anywhere else (`database/guard.py`).
* Nothing reaches a live system from a test: template provider, `DRY_RUN=true`, `LIVE_TOOLS=""`, workers not started.
* Tests are plain scripts (`check(label, cond)` + a `run_module` runner) so they run without pytest, and pytest-compatible (`test_*` functions with assertions) so they also run under it.

## Example workflows exercised

* `plan_execute_verify`: research → plan → execute → review → repair(dynamic gate) — `test_workflow_agents.py`, `test_api.py`.
* `direct`: execute → review — `test_workflow_agents.py::test_run_task_now_through_lifecycle`.
* Linux: inspect → plan → (DAG of tool calls) → verify → replan/escalate — `examples/linux_agent/test_linux_agent.py`.
