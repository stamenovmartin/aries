"""Tools every deployment gets: safe reads and the guarded shell.
Registered on import of agentic_core.tools.builtin."""
from __future__ import annotations

import json
import os

import httpx

from agentic_core.security import sandbox
from agentic_core.security.permissions import Permission
from agentic_core.tools.registry import tool


@tool("echo", "Return the payload unchanged — the smoke-test tool.",
      input_schema={"text": {"type": str, "required": True}}, risk="low")
async def echo(payload, ctx):
    return {"success": True, "content": payload["text"]}


@tool("fs.read", "Read a text file (bounded) under an allowed root.",
      input_schema={"path": {"type": str, "required": True}, "max_bytes": {"type": int}},
      risk="low", permission=Permission.VIEW_DATA)
async def fs_read(payload, ctx):
    root = os.path.abspath(ctx.get("fs_root") or os.environ.get("AGENTIC_FS_ROOT") or "/")
    path = os.path.abspath(payload["path"])
    if not path.startswith(root):
        return {"success": False, "details": f"path outside allowed root {root}", "error_class": "policy"}
    limit = int(payload.get("max_bytes") or 64_000)
    with open(path, "rb") as fh:
        data = fh.read(limit + 1)
    return {"success": True, "content": data[:limit].decode(errors="replace"), "truncated": len(data) > limit,
            "path": path}


@tool("shell.read", "Run a read-only shell command (allowlisted, sandboxed, timed out).",
      input_schema={"command": {"type": str, "required": True}, "timeout_s": {"type": (int, float)}},
      risk="low", timeout_s=60)
async def shell_read(payload, ctx):
    r = await sandbox.run_command(payload["command"], timeout=payload.get("timeout_s"), read_only=True,
                                  allowlist=ctx.get("allowlist"))
    return r.as_dict()


@tool("shell.exec", "Run a MUTATING shell command. Side-effecting: dry-run, live gate, policy, approval, idempotency.",
      input_schema={"command": {"type": str, "required": True}, "timeout_s": {"type": (int, float)},
                    "target": {"type": str}},
      risk="high", side_effect=True, idempotent=False, permission=Permission.EXECUTE, timeout_s=300)
async def shell_exec(payload, ctx):
    r = await sandbox.run_command(payload["command"], timeout=payload.get("timeout_s"), read_only=False,
                                  dry_run=False)
    return r.as_dict()


@tool("http.get", "HTTP GET a URL (read-only).",
      input_schema={"url": {"type": str, "required": True}}, risk="low", timeout_s=30)
async def http_get(payload, ctx):
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        r = await client.get(payload["url"])
    return {"success": r.status_code < 400, "status": r.status_code, "content": r.text[:20000],
            "details": f"HTTP {r.status_code}"}


@tool("json.parse", "Parse a JSON string.", input_schema={"text": {"type": str, "required": True}}, risk="low")
async def json_parse(payload, ctx):
    try:
        return {"success": True, "output": json.loads(payload["text"])}
    except ValueError as e:
        return {"success": False, "details": f"invalid JSON: {e}", "error_class": "validation"}
