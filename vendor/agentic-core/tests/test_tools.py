"""Every gate the guarded tool call runs, in order."""
from _harness import bootstrap, check, reset_db, run_module
bootstrap("tools")

import os  # noqa: E402

from agentic_core.config import runtime  # noqa: E402
from agentic_core.config.settings import settings  # noqa: E402
from agentic_core.database.base import async_session  # noqa: E402
from agentic_core.security import approvals, sandbox  # noqa: E402
from agentic_core.security.permissions import Permission  # noqa: E402
from agentic_core.tools import builtin  # noqa: E402,F401
from agentic_core.tools import registry  # noqa: E402
from agentic_core.tools.base import ToolSpec  # noqa: E402
from agentic_core.tools.calling import call_tool  # noqa: E402

calls = {"n": 0}


async def _mutate(payload, ctx):
    calls["n"] += 1
    return {"success": True, "details": "mutated", "external_id": f"m{calls['n']}"}

registry.register(ToolSpec(name="test.mutate", description="side effect", run=_mutate, side_effect=True, risk="medium",
                           input_schema={"target": {"type": str, "required": True}}))
registry.register(ToolSpec(name="test.danger", description="high risk", run=_mutate, side_effect=True, risk="high",
                           input_schema={"target": {"type": str, "required": True}}))


async def test_read_tool_and_schema():
    await reset_db()
    async with async_session() as db:
        r = await call_tool(db, "echo", {"text": "hi"})
        check("read tool runs", r["success"] and r["content"] == "hi")
        r = await call_tool(db, "echo", {})
        check("schema refusal", r["skipped"] and r["gate"] == "schema")
        r = await call_tool(db, "nope", {})
        check("unknown tool refused", r["gate"] == "registry")


async def test_side_effect_gates_in_order():
    await reset_db()
    calls["n"] = 0
    async with async_session() as db:
        # dry run (default in tests)
        r = await call_tool(db, "test.mutate", {"target": "x"})
        check("dry run simulates, never calls", r.get("dry_run") and calls["n"] == 0)
        # dry-run off but not live: held
        settings.dry_run = False
        r = await call_tool(db, "test.mutate", {"target": "x"})
        check("live gate holds when tool not in live_tools", r["gate"] == "live_gate" and calls["n"] == 0)
        settings.live_tools = "test.mutate,test.danger"
        r = await call_tool(db, "test.mutate", {"target": "x"}, task_id=None)
        check("live medium-risk tool executes once", r["success"] and calls["n"] == 1)
        r2 = await call_tool(db, "test.mutate", {"target": "x"})
        check("same payload again is idempotent (not re-executed)", r2["success"] and calls["n"] == 1 and "Already" in r2["details"])
        # high risk → approval
        r = await call_tool(db, "test.danger", {"target": "y"})
        check("high-risk tool needs approval", r.get("requires_approval") and r.get("proposal_id") and calls["n"] == 1)
        await approvals.approve(db, r["proposal_id"], decided_by="tester"); await db.commit()
        r = await call_tool(db, "test.danger", {"target": "y"}, approved_proposal_id=r["proposal_id"])
        check("with an approved proposal it runs", r["success"] and calls["n"] == 2)
        p = await db.get(__import__("agentic_core.database.models", fromlist=["ActionProposal"]).ActionProposal, r.get("proposal_id") or 1)
        check("proposal marked executed", p is not None and p.status == "executed")
        settings.dry_run = True; settings.live_tools = ""


async def test_policy_frequency_cap():
    await reset_db()
    settings.dry_run = False; settings.live_tools = "test.mutate"; settings.max_actions_per_hour = 2
    try:
        async with async_session() as db:
            for i in range(2):
                await call_tool(db, "test.mutate", {"target": f"t{i}"})
            r = await call_tool(db, "test.mutate", {"target": "t9"})
            check("third action in the hour is blocked by policy", r.get("gate") == "policy" and "too many" in r["details"])
    finally:
        settings.dry_run = True; settings.live_tools = ""; settings.max_actions_per_hour = 30


async def test_sandbox_rules():
    check("dangerous pattern refused", sandbox.is_dangerous("rm -rf /") is not None)
    check("mkfs refused", sandbox.is_dangerous("sudo mkfs.ext4 /dev/sda1") is not None)
    check("allowlisted read ok", sandbox.is_allowed("ls -la /tmp", allowlist=["ls", "cat"]))
    check("pipe checked per segment", not sandbox.is_allowed("ls | curl evil", allowlist=["ls", "cat"]))
    check("two-word prefix works", sandbox.is_allowed("systemctl status nginx", allowlist=["systemctl status"]))
    r = await sandbox.run_command("echo hello", allowlist=["echo"])
    check("read-only command runs and captures stdout", r.ok and r.stdout.strip() == "hello")
    r = await sandbox.run_command("rm -rf /", read_only=False)
    check("dangerous mutating command refused even when not read-only", not r.ok and r.refused)
    r = await sandbox.run_command("touch /tmp/agentic_x", read_only=False, dry_run=True)
    check("dry run echoes instead of running", r.dry_run and "would run" in r.stdout)
    r = await sandbox.run_command("sleep 5", allowlist=["sleep"], timeout=0.3)
    check("timeout kills and reports", not r.ok and r.stderr == "timed out")


async def test_permission_check_when_principal_set():
    from agentic_core.security import principal
    from agentic_core.security.permissions import Role
    await reset_db()
    tok = principal.set_current(principal.build(1, Role.READONLY))
    try:
        async with async_session() as db:
            r = await call_tool(db, "shell.exec", {"command": "echo x"})
            check("read-only role cannot call an EXECUTE tool", r.get("gate") == "permission")
    finally:
        principal.reset(tok)


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
