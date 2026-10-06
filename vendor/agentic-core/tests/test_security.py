from _harness import bootstrap, check, reset_db, run_module
bootstrap("security")

import os  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402
from agentic_core.observability import audit  # noqa: E402
from agentic_core.security import crypto, secrets_store  # noqa: E402
from agentic_core.security.permissions import Permission, Role, permission_for, permissions_for  # noqa: E402


def test_permissions_table():
    check("approver cannot execute", Permission.EXECUTE not in permissions_for(Role.APPROVER))
    check("executor cannot approve", Permission.APPROVE not in permissions_for(Role.EXECUTOR))
    check("/api/tasks/1/approve needs APPROVE", permission_for("POST", "/api/tasks/1/approve") is Permission.APPROVE)
    check("/api/tasks/1/run needs EXECUTE", permission_for("POST", "/api/tasks/1/run") is Permission.EXECUTE)
    check("GET is view_data", permission_for("GET", "/api/whatever") is Permission.VIEW_DATA)
    check("unknown POST fails closed to EDIT_TASK", permission_for("POST", "/api/whatever") is Permission.EDIT_TASK)
    check("audit read needs manage_users", permission_for("GET", "/api/audit") is Permission.MANAGE_USERS)


def test_crypto():
    os.environ.pop("CREDENTIALS_KEY", None)
    try:
        crypto.encrypt("x"); check("refuses without key", False)
    except crypto.KeyUnavailable:
        check("refuses without key", True)
    os.environ["CREDENTIALS_KEY"] = crypto.generate_key()
    ct = crypto.encrypt("EAAG-secret-token-1234567890", aad="meta|TOKEN")
    check("tagged v1", ct.startswith("v1:") and "secret" not in ct)
    check("roundtrip", crypto.decrypt(ct, aad="meta|TOKEN") == "EAAG-secret-token-1234567890")
    try:
        crypto.decrypt(ct, aad="other|TOKEN"); check("AAD binds to row", False)
    except crypto.CiphertextInvalid:
        check("AAD binds to row", True)
    try:
        crypto.decrypt(ct[:-3] + "AAA", aad="meta|TOKEN"); check("tamper detected", False)
    except crypto.CiphertextInvalid:
        check("tamper detected", True)
    check("hint hides all but 4", crypto.hint_for("EAAG-secret-token-1234567890").startswith("…"))


async def test_secret_store_rotation_and_revoke():
    await reset_db()
    os.environ["CREDENTIALS_KEY"] = crypto.generate_key()
    secrets_store.register("test", "TEST_TOKEN", "test token")
    async with async_session() as db:
        r = await secrets_store.save(db, {"TEST_TOKEN": "first-value-12345", "NOT_ALLOWED": "x"})
        check("saves allowed, rejects unknown", r["saved"] == ["TEST_TOKEN"] and r["rejected"] == ["NOT_ALLOWED"])
        check("resolve returns the value", await secrets_store.resolve(db, "TEST_TOKEN") == "first-value-12345")
        st = {f["key"]: f for f in await secrets_store.state(db)}
        check("state never carries the value", st["TEST_TOKEN"]["set"] and "first" not in str(st["TEST_TOKEN"]))
        await secrets_store.rotate(db, "TEST_TOKEN", "second-value-12345")
        check("old value served while pending", await secrets_store.resolve(db, "TEST_TOKEN") == "first-value-12345")
        await secrets_store.confirm_rotation(db, "TEST_TOKEN")
        check("new value after confirm", await secrets_store.resolve(db, "TEST_TOKEN") == "second-value-12345")
        os.environ["TEST_TOKEN"] = "env-fallback"
        await secrets_store.revoke(db, "TEST_TOKEN")
        check("revoked does NOT fall back to env", await secrets_store.resolve(db, "TEST_TOKEN") is None)
    os.environ.pop("CREDENTIALS_KEY", None)
    async with async_session() as db:
        r = await secrets_store.save(db, {"TEST_TOKEN": "x" * 20})
        check("save refused without key, nothing written plaintext", r["saved"] == [] and r["refused"])


async def test_audit_is_immutable():
    await reset_db()
    from sqlalchemy import select, update
    from agentic_core.database.models import AuditEvent
    async with async_session() as db:
        await audit.log_event(db, actor_type="system", action="test.event", entity_type="x", entity_id=1, detail={"k": "v"})
        await db.commit()
        row = (await db.execute(select(AuditEvent))).scalars().first()
        row.action = "tampered"
        try:
            await db.commit(); check("edit refused", False)
        except audit.AuditEventImmutable:
            await db.rollback(); check("edit refused", True)
    async with async_session() as db:
        try:
            await db.execute(update(AuditEvent).values(action="x")); check("bulk update refused", False)
        except audit.AuditEventImmutable:
            check("bulk update refused", True)


def test_redaction():
    from agentic_core.observability.logging_setup import redact_text, scrub
    os.environ["MY_SECRET_TOKEN"] = "supersecretvalue123"
    t = redact_text("token EAAGabcdefghijklmnopqrstuvwxyz1234 and supersecretvalue123 and postgres://u:pw@h/db")
    check("shapes and env values redacted", "EAAG" not in t and "supersecretvalue123" not in t and ":pw@" not in t)
    s = scrub({"password": "abc", "nested": {"api_key": "k", "ok": 1}})
    check("keys redacted recursively", s["password"] == "***" and s["nested"]["api_key"] == "***" and s["nested"]["ok"] == 1)


if __name__ == "__main__":
    import sys; sys.exit(run_module(sys.modules[__name__]))
