"""ARIES's security controls, exercised against real sockets and real hostile input.

The SSRF guard in particular is not testable with a mock: the whole point is what
happens between resolving a name and opening a socket, so these tests run a real
HTTP server on loopback and make real requests to it.
"""
from __future__ import annotations

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-security")

import httpx  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.api import security as apisec  # noqa: E402
from aries.news.fetch import FetchRefused, address_reason, fetch  # noqa: E402
from aries.news.feed import FeedError, clean, parse  # noqa: E402


# ── a real server on loopback ───────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):      # silence
        pass

    def do_GET(self):
        if self.path == "/feed":
            body = (b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
                    b"<item><title>Hello</title><link>https://e.com/1</link></item>"
                    b"</channel></rss>")
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/redirect-local":
            self.send_response(302)
            self.send_header("Location", "/feed")
            self.end_headers()
        elif self.path == "/redirect-metadata":
            # The classic SSRF bypass: a legitimate host redirecting inward.
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data")
            self.end_headers()
        elif self.path == "/redirect-loop":
            self.send_response(302)
            self.send_header("Location", "/redirect-loop")
            self.end_headers()
        elif self.path == "/huge":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            for _ in range(200):
                self.wfile.write(b"x" * 8192)
        else:
            self.send_response(404)
            self.end_headers()


_server = HTTPServer(("127.0.0.1", 0), _Handler)
PORT = _server.server_address[1]
BASE = f"http://127.0.0.1:{PORT}"
threading.Thread(target=_server.serve_forever, daemon=True).start()


# ── address classification ──────────────────────────────────────────────────

async def test_address_classification():
    cases = {"127.0.0.1": "loopback", "::1": "loopback", "10.0.0.1": "private",
             "192.168.1.1": "private", "172.16.0.1": "private",
             "169.254.169.254": "link-local (the cloud metadata range)",
             "224.0.0.1": "reserved", "8.8.8.8": None, "1.1.1.1": None}
    for ip, expected in cases.items():
        got = address_reason(ip)
        check(f"{ip} classified as {expected or 'public'}", got == expected)


async def test_fetch_refuses_before_connecting():
    for url, why in [("http://127.0.0.1/x", "loopback"),
                     ("http://169.254.169.254/latest", "metadata"),
                     ("http://192.168.1.5/x", "private"),
                     ("file:///etc/passwd", "scheme"),
                     ("https://user:pw@example.com/x", "credentials")]:
        try:
            await fetch(url, allow_private=False, timeout=5)
            check(f"{why}: refused", False)
        except FetchRefused:
            check(f"a {why} target is refused before any connection", True)
        except Exception as e:
            check(f"a {why} target is refused before any connection ({type(e).__name__})", False)


# ── real fetches ────────────────────────────────────────────────────────────

async def test_fetch_happy_path():
    r = await fetch(f"{BASE}/feed", allow_private=True, timeout=10)
    check("a permitted fetch succeeds", r.ok and r.status == 200)
    check("the body comes back", b"<rss" in r.body)
    check("the content type is recorded", "xml" in r.content_type)
    check("the address actually connected to is recorded", r.resolved_ip == "127.0.0.1")
    check("and it parses as a feed", parse(r.body).items[0].title == "Hello")


async def test_redirects_are_followed_and_re_validated():
    r = await fetch(f"{BASE}/redirect-local", allow_private=True, timeout=10)
    check("a safe redirect is followed", r.ok and b"<rss" in r.body)
    check("and every hop is recorded", len(r.hops) == 2)


async def test_redirect_to_metadata_is_refused():
    """The bypass that defeats add-time validation entirely: the host is
    legitimate, and it answers 302 Location: 169.254.169.254."""
    try:
        await fetch(f"{BASE}/redirect-metadata", allow_private=True, timeout=10)
        check("a redirect into the metadata endpoint is refused", False)
    except FetchRefused as e:
        check("a redirect into the metadata endpoint is refused", True)
        check("and names what it refused", "169.254.169.254" in str(e))


async def test_redirect_to_metadata_refused_even_when_private_is_allowed_elsewhere():
    """allow_private exists so ARIES can read a feed on the LAN. It must still
    refuse the metadata range, which is never a legitimate source."""
    try:
        await fetch(f"{BASE}/redirect-metadata", allow_private=False, timeout=10)
        check("refused with allow_private off", False)
    except FetchRefused:
        check("refused with allow_private off", True)


async def test_redirect_limit():
    try:
        await fetch(f"{BASE}/redirect-loop", allow_private=True, timeout=10, max_redirects=2)
        check("an endless redirect loop is stopped", False)
    except FetchRefused as e:
        check("an endless redirect loop is stopped", "redirect" in str(e))


async def test_size_cap_is_enforced_while_streaming():
    r = await fetch(f"{BASE}/huge", allow_private=True, timeout=15, max_bytes=50_000)
    check("a large response is truncated, not swallowed whole", r.truncated is True)
    check("and never exceeds the cap", len(r.body) <= 50_000)


# ── hostile feed content ────────────────────────────────────────────────────

async def test_feed_refuses_dtd():
    """Verified on this machine: ElementTree refuses XXE but EXPANDS nested
    internal entities, which is the billion-laughs denial of service."""
    billion = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
               b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
               b']><rss><item>&lol2;</item></rss>')
    try:
        parse(billion)
        check("a feed declaring a DOCTYPE is refused", False)
    except FeedError as e:
        check("a feed declaring a DOCTYPE is refused", True)
        check("and says why", "entity expansion" in str(e))


async def test_feed_content_is_data_not_markup():
    check("tags are stripped", clean("<b>bold</b> text") == "bold text")
    check("entities are unescaped after stripping, not before",
          clean("&lt;script&gt;alert(1)&lt;/script&gt; hi") == "alert(1) hi")
    check("a very long field is bounded", len(clean("x" * 99999)) <= 2000)
    check("nothing empty crashes it", clean(None) == "" and clean("") == "")


# ── the loopback control ────────────────────────────────────────────────────

class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, host):
        self.client = _FakeClient(host) if host else None
        self.url = type("U", (), {"path": "/api/aries/automations"})()


async def test_no_api_key_means_loopback_only():
    from agentic_core.config.settings import settings

    async def _next(_):
        return "served"

    settings.api_key = ""
    for host in ("127.0.0.1", "::1", "localhost", "testclient"):
        r = await apisec.local_only_middleware(_FakeRequest(host), _next)
        check(f"a request from {host} is served", r == "served")
    for host in ("192.168.1.50", "8.8.8.8", "10.0.0.2"):
        r = await apisec.local_only_middleware(_FakeRequest(host), _next)
        check(f"a request from {host} is refused with no API key", getattr(r, "status_code", None) == 403)
    r = await apisec.local_only_middleware(_FakeRequest(None), _next)
    check("an unknown client address fails closed", getattr(r, "status_code", None) == 403)

    settings.api_key = "a-real-key"
    r = await apisec.local_only_middleware(_FakeRequest("192.168.1.50"), _next)
    check("with an API key configured, remote requests reach authentication", r == "served")
    settings.api_key = ""


async def test_startup_report_is_honest():
    from agentic_core.config.settings import settings
    settings.api_key = ""
    rep = apisec.startup_report()
    check("the posture says it serves loopback only", rep["serves"] == "loopback only")
    check("and that secret storage is unavailable without a key",
          rep["secret_storage"].startswith("refused"))
    check("and that side effects are simulated", rep["dry_run"] is True)


# ── input bounds ────────────────────────────────────────────────────────────

async def test_input_bounds():
    from fastapi import HTTPException
    ok = True
    try:
        apisec.bound_text("x" * 5000, apisec.MAX_NAME_LEN, "name")
        ok = False
    except HTTPException:
        pass
    check("an oversized field is refused", ok)
    try:
        apisec.bound_list(["x"] * 10_000, max_items=apisec.MAX_TERMS,
                          max_len=apisec.MAX_TERM_LEN, field="synonyms")
        ok = False
    except HTTPException:
        pass
    check("too many list entries are refused", ok)
    try:
        apisec.bound_list(["x" * 9999], max_items=apisec.MAX_TERMS,
                          max_len=apisec.MAX_TERM_LEN, field="synonyms")
        ok = False
    except HTTPException:
        pass
    check("an oversized list entry is refused", ok)
    check("normal input passes",
          apisec.bound_list(["ai", "agents"], max_items=10, max_len=50, field="t") == ["ai", "agents"])


async def test_a_long_term_cannot_reach_the_regex_compiler():
    from aries.interests.matching import MAX_TERM_CHARS, Matchable
    m = Matchable.build("x" * 100_000, [], 0.5)
    check("a huge term is truncated before compilation",
          len(m.terms[0].text) <= MAX_TERM_CHARS)


# ── the audit trail names who acted ─────────────────────────────────────────

async def test_audit_records_the_principal():
    await reset_db()
    from sqlalchemy import select

    from agentic_core.database.models import AuditEvent
    from agentic_core.security import principal as pc

    from aries.settings import SettingsService

    token = pc.set_current(pc.shared_key_owner())
    try:
        who = apisec.actor()
        check("the actor is derived from the principal", "shared-key" in who)
        check("and keeps the user: prefix the write rules require", who.startswith("user:"))
        async with async_session() as db:
            await SettingsService(db).set("general.theme", "dark", set_by=who)
            rows = (await db.execute(select(AuditEvent).where(
                AuditEvent.action == "setting.changed"))).scalars().all()
        check("the audit event names that principal", any("shared-key" in (r.actor or "") for r in rows))
    finally:
        pc.reset(token)


if __name__ == "__main__":
    code = run_module(sys.modules[__name__])
    # Shut the test server down explicitly. As a daemon thread it was being
    # killed mid-request at interpreter shutdown, which raised BrokenPipeError
    # on stderr and made the process exit non-zero even though every assertion
    # had passed — a green suite that reports failure is worse than a red one,
    # because it trains you to ignore the exit code.
    try:
        _server.shutdown()
        _server.server_close()
    except Exception:
        pass
    sys.exit(code)
