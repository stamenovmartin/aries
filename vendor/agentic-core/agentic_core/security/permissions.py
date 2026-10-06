"""What each role may do, and which permission every route demands.
Lifted from backend/app/core/permissions.py.

Approval and execution are separate permissions and no role below owner or
administrator holds both. The route policy is a table, longest prefix wins,
and it fails closed: an unmatched mutation defaults to EDIT, never "allowed".
A sensitive verb appearing as a path segment (/approve, /execute, /run)
upgrades a weak permission to the one the action demands.
"""
from __future__ import annotations

import enum


class Role(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "administrator"
    OPERATOR = "operator"        # create/edit tasks; cannot approve or execute
    APPROVER = "approver"        # approve/reject; cannot execute
    EXECUTOR = "executor"        # execute approved work; cannot approve
    ANALYST = "analyst"
    READONLY = "read_only"


class Permission(str, enum.Enum):
    VIEW_DATA = "view_data"
    CREATE_TASK = "create_task"
    RUN_AGENT = "run_agent"
    EDIT_TASK = "edit_task"
    APPROVE = "approve"            # deliberately not EXECUTE
    SCHEDULE = "schedule"
    EXECUTE = "execute"            # deliberately not APPROVE
    MANAGE_TOOLS = "manage_tools"
    VIEW_SECRETS = "view_secrets"
    MANAGE_USERS = "manage_users"
    EXPORT_DATA = "export_data"


P = Permission
_ALL = set(P)

ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.OWNER: set(_ALL),
    Role.ADMIN: _ALL - {P.VIEW_SECRETS},
    Role.OPERATOR: {P.VIEW_DATA, P.CREATE_TASK, P.RUN_AGENT, P.EDIT_TASK, P.SCHEDULE, P.EXPORT_DATA},
    Role.APPROVER: {P.VIEW_DATA, P.APPROVE, P.EXPORT_DATA},
    Role.EXECUTOR: {P.VIEW_DATA, P.EXECUTE, P.SCHEDULE, P.EXPORT_DATA},
    Role.ANALYST: {P.VIEW_DATA, P.EXPORT_DATA},
    Role.READONLY: {P.VIEW_DATA},
}


def permissions_for(role) -> set[Permission]:
    if isinstance(role, str):
        try:
            role = Role(role)
        except ValueError:
            return set()
    return set(ROLE_PERMISSIONS.get(role, set()))


_POLICY: list[tuple[str, dict[str, Permission]]] = [
    ("/api/execution", {"GET": P.VIEW_DATA, "*": P.EXECUTE}),
    ("/api/scheduler", {"POST": P.SCHEDULE, "PATCH": P.SCHEDULE, "DELETE": P.SCHEDULE}),
    ("/api/proposals", {"POST": P.APPROVE}),
    ("/api/settings", {"GET": P.VIEW_DATA, "*": P.MANAGE_TOOLS}),
    ("/api/environment", {"*": P.MANAGE_TOOLS}),
    ("/api/tools", {"POST": P.MANAGE_TOOLS, "PATCH": P.MANAGE_TOOLS, "DELETE": P.MANAGE_TOOLS}),
    ("/api/audit", {"GET": P.MANAGE_USERS}),
    ("/api/users", {"*": P.MANAGE_USERS}),
    ("/api/tokens", {"*": P.MANAGE_USERS}),
    ("/api/agents", {"POST": P.RUN_AGENT}),
    ("/api/tasks", {"POST": P.CREATE_TASK, "PATCH": P.EDIT_TASK, "PUT": P.EDIT_TASK, "DELETE": P.EDIT_TASK}),
    ("/api/evals", {"POST": P.RUN_AGENT}),
]

_DEFAULTS: dict[str, Permission] = {
    "GET": P.VIEW_DATA, "HEAD": P.VIEW_DATA, "OPTIONS": P.VIEW_DATA,
    "POST": P.EDIT_TASK, "PUT": P.EDIT_TASK, "PATCH": P.EDIT_TASK, "DELETE": P.EDIT_TASK,
}

_ACTION_SEGMENT: dict[str, Permission] = {
    "execute": P.EXECUTE, "run": P.EXECUTE, "publish": P.EXECUTE, "go-live": P.MANAGE_TOOLS,
    "approve": P.APPROVE, "reject": P.APPROVE,
}
_UPGRADABLE = {P.VIEW_DATA, P.EDIT_TASK, P.RUN_AGENT, P.CREATE_TASK, P.SCHEDULE}


def permission_for(method: str, path: str) -> Permission:
    method = method.upper()
    best = None
    for prefix, table in _POLICY:
        if not path.startswith(prefix):
            continue
        perm = table.get(method) or table.get("*")
        if perm is None:
            continue
        if best is None or len(prefix) > best[0]:
            best = (len(prefix), perm)
    resolved = best[1] if best else _DEFAULTS.get(method, P.EDIT_TASK)
    if method in ("POST", "PUT", "PATCH") and resolved in _UPGRADABLE:
        segments = path.strip("/").split("/")
        for verb, perm in _ACTION_SEGMENT.items():
            if verb in segments:
                return perm
    return resolved
