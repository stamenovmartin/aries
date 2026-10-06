# TOOLS

## 1. In the original

The marketing backend has three "tool" surfaces, all reproduced in the core:

1. **Connectors** (`app/connectors/`): one interface per channel (`MarketingConnector`), a `Capabilities` dataclass READ from config (never assumed), `NotSupported` instead of fake success, paid actions default to paused, and a **registry** (`connectors/registry.py::connector_for`) that maps a channel name to a connector — adding a connector is one rule. A `MockFacebookConnector` proves the core does not depend on Meta.
2. **Compilers** (`app/compilers/`): neutral `CampaignIntent` → native plan (`CompileResult` with post/ad/refusal). Shared prechecks (empty copy, out of stock) live in the base class.
3. **Actions** (`app/services/agent/workspace.py::ACTIONS`): ~40 named actions the chat agent can call; each calls the SAME route handler the dashboard calls ("the chat is a second door into one room, not a parallel implementation that will drift").

The **publish path** (`app/services/posting/__init__.py::publish_campaign`) is the reference for tool-calling logic and error handling. Its gates, in order: test mode (dry-run) → live gate (`LIVE_PLATFORMS`) → policy engine → atomic in-flight claim → compile → classifieds quota (`posting/quota.py`) → idempotent operation (`begin`/`mark_sent` BEFORE the gather) → `asyncio.gather` over connectors (no exception escapes a target) → `record` → status roll-up → recovery on crash (`_recover_crashed_run`: in-flight targets become terminal `skipped`, never `failed`).

The **external CLI agent** (`services/ai/__init__.py::_cli_agent_run_inner`) is the sandbox pattern: empty scratch cwd, own process group, timeout with `killpg`, bounded semaphore, `--sandbox read-only`, stderr captured, output stripped.

## 2. In the core

### Tool registry — `tools/base.py`, `tools/registry.py`

```python
@tool("fs.read", "Read a text file", input_schema={"path": {"type": str, "required": True}},
      risk="low", permission=Permission.VIEW_DATA)
async def fs_read(payload, ctx): ...
```

`ToolSpec` fields: `name, description, run, input_schema, output_schema, permission, risk (low|medium|high), side_effect, requires_approval, idempotent, timeout_s, capabilities(), tags`. `GET /api/tools` returns `describe()` for every tool plus connector capabilities. `registry.for_model(names)` is the compact list an agent prompt carries.

Built-in (`tools/builtin.py`): `echo`, `fs.read` (bounded, under an allowed root), `shell.read` (allowlisted, sandboxed), `shell.exec` (mutating: high risk, side_effect, non-idempotent, EXECUTE permission), `http.get`, `json.parse`.

### The guarded call — `tools/calling.call_tool(db, name, payload, ctx, task_id, approved_proposal_id)`

| # | gate | refusal shape (`{"success": False, "skipped": True, "gate": …}`) |
|---|---|---|
| 1 | registry + RBAC permission of the current principal | `registry`, `permission` |
| 2 | payload validates against `input_schema` | `schema` |
| 3 | **dry run** (`runtime.get_dry_run()`): a side-effecting tool is simulated | returns `{"success": True, "dry_run": True}` |
| 4 | **live gate**: the tool must be named in `live_tools` (`*` = all) | `live_gate` |
| 5 | **policy** (`security/policy.evaluate`): frequency cap, empty payload, risk tier | `policy` |
| 6 | **approval**: `requires_approval` or risk `high` or policy demanded → an `ActionProposal` is created and returned with `requires_approval: True, proposal_id` | `approval` |
| 7 | **idempotency**: `operations.begin(key)`; `done` → recorded result; `reconcile` → refusal with `uncertain`; else `mark_sent` and commit BEFORE the call | `reconcile` |
| 8 | the call, with `timeout_s`; a timeout after start is `uncertain` for side-effecting tools; exceptions become classified failures | — |
| 9 | `operations.record`, `mark_executed` on the proposal, metrics, audit line, journal line | — |

Read-only tools skip 3–7. Every refusal is a first-class result in the same shape as a success.

### Sandbox — `security/sandbox.py`

`run_command(command, timeout, read_only, allowlist, dry_run)`: dangerous-pattern denylist (always refused: `rm -rf /`, `mkfs`, `dd of=/dev`, shutdown/reboot, fork bomb, writes to /etc/passwd…), read-only allowlist by command prefix checked per pipe/chain segment, scratch cwd with a minimal environment, own process group + `SIGKILL` on timeout, bounded concurrency, a timeout on a mutating command reports `uncertain`.

### Connectors — `tools/connectors.py`

`Connector` (read/write/execute/fetch_metrics/listen, `capabilities()`), `ActionRequest`/`ActionResult`, `register_connector(match, cls)`, `connector_for(target)`, `MockConnector`. Use it when a tool wraps an external system with several operations.

### Error handling summary

* A tool returns `{success, details, external_id?, uncertain?, skipped?, error_class?}`. `operations.record` maps that to `succeeded | failed(+class) | uncertain | skipped`.
* `uncertain` is never auto-retried anywhere (lifecycle, DAG, scheduler, recovery). `POST /api/execution/plans/{key}/steps/{step}/reconcile` is the human's/probe's way out.
* Metrics: `tool_calls_total{tool,outcome}`, `errors_total{error_class,where}`; audit: `tool.executed` / `tool.failed`.
