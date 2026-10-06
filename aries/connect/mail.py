"""A mailbox, read-only, over IMAP.

WHY IMAP AND NOT THE GMAIL API
------------------------------
IMAP works with every provider, needs no OAuth application registered with
anyone, and — the part that matters here — **has no write scope in the shape
ARIES uses it**. An OAuth token for Gmail is a token that can send, and the
argument "we only call the read endpoints" is exactly the argument that stops
being true the first time someone adds a feature.

An app password in the keyring, used against a read-only IMAP session, cannot
send mail no matter what any model says. That is a capability boundary rather
than a promise about code.

WHAT IT NEVER DOES
------------------
Mark as read. IMAP will happily set `\\Seen` when a message is fetched, and a
person whose assistant silently marked their inbox read would be right to throw
the whole project away. Every fetch uses `BODY.PEEK[]`, which is the same
request without the side effect.

Nor does it delete, move, flag, or send. There is no code here that does, and
the connector protocol has no method through which it could be asked to.

THE CONTENT
-----------
Comes back as `Untrusted`. Everything downstream — the summariser, the working
set, the Control Centre — is built on that being true, and it is why the type
exists rather than a comment.
"""
from __future__ import annotations

import email
import email.policy
import imaplib
import logging
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from aries.connect.base import Health, Item, register
from aries.connect.secrets import SecretRef, read as read_secret
from aries.connect.untrusted import Untrusted

logger = logging.getLogger(__name__)

# A mail body longer than this is a newsletter or a thread with everything
# quoted; the first part carries what a person would read.
MAX_BODY = 20_000
TIMEOUT_S = 25.0

# `provider:account` — the same shape the source registry's example shows.
LOCATION = re.compile(r"^(?P<provider>[a-z0-9.-]+):(?P<account>[^\s:]+@[^\s:]+)$")

# Where the well-known providers live, so a person types "gmail:me@gmail.com"
# and not a hostname. An unknown provider is an error rather than a guess: a
# wrong IMAP host is a connection attempt to a machine the user did not choose.
PROVIDERS: dict[str, dict] = {
    "gmail": {"host": "imap.gmail.com", "port": 993,
              "note": "needs an App Password — Google refuses a normal password over IMAP"},
    "outlook": {"host": "outlook.office365.com", "port": 993, "note": ""},
    "yahoo": {"host": "imap.mail.yahoo.com", "port": 993,
              "note": "needs an app password"},
    "icloud": {"host": "imap.mail.me.com", "port": 993, "note": "needs an app password"},
    "fastmail": {"host": "imap.fastmail.com", "port": 993, "note": ""},
    "imap": {"host": "", "port": 993,
             "note": "give the server as imap:user@host — the host after the @ is used"},
}


def parse_location(location: str) -> tuple[str, str, str, int]:
    """`gmail:me@example.com` → (provider, account, host, port)."""
    match = LOCATION.match((location or "").strip())
    if not match:
        raise ValueError(
            f"'{location}' is not a mailbox — write it as provider:address, "
            f"for example gmail:you@gmail.com (providers: {', '.join(sorted(PROVIDERS))})")
    provider, account = match.group("provider"), match.group("account")
    spec = PROVIDERS.get(provider)
    if spec is None:
        raise ValueError(
            f"ARIES does not know the provider '{provider}'. Known: "
            f"{', '.join(sorted(PROVIDERS))}. Use imap:user@your.server for anything else.")
    host = spec["host"] or account.split("@", 1)[1]
    return provider, account, host, int(spec["port"])


@dataclass
class MailConnector:
    source_type: str = "email"
    outbound: bool = True

    def capabilities(self) -> tuple[str, ...]:
        # No "listen": IMAP IDLE is a long-lived connection ARIES does not hold
        # yet, and claiming it would put a capability on the Connections screen
        # that nothing implements.
        return ("read", "search")

    async def check(self, source) -> Health:
        now = datetime.now(timezone.utc)
        try:
            provider, account, host, port = parse_location(source.location)
        except ValueError as exc:
            return Health(False, str(exc), checked_at=now)

        ref = SecretRef.make("email", account)
        password = read_secret(ref)
        if not password:
            note = PROVIDERS[provider].get("note") or ""
            return Health(False,
                          f"no password is stored for {account}"
                          + (f" — {note}" if note else ""),
                          needs_credential=True, checked_at=now)
        try:
            box = _connect(host, port, account, password)
        except imaplib.IMAP4.error as exc:
            return Health(False, f"{host} refused the login: {_safe(exc)}",
                          needs_credential=True, checked_at=now)
        except (OSError, socket.timeout) as exc:
            return Health(False, f"could not reach {host}: {_safe(exc)}", checked_at=now)
        try:
            status, data = box.select("INBOX", readonly=True)
            count = int(data[0]) if status == "OK" and data and data[0] else 0
            return Health(True, f"{account} · {count} message(s) in the inbox",
                          checked_at=now)
        finally:
            _close(box)

    async def read(self, source, *, since: datetime | None = None,
                   limit: int = 50) -> list[Item]:
        criteria = ["ALL"]
        if since:
            # IMAP SINCE has DAY resolution, so it is a coarse filter that must
            # never be treated as exact: the caller still compares dates.
            criteria = ["SINCE", since.strftime("%d-%b-%Y")]
        return await self._fetch(source, criteria, limit)

    async def search(self, source, query: str, *, limit: int = 25) -> list[Item]:
        text = (query or "").strip()
        if not text:
            return []
        # TEXT searches headers and body server-side, which is the whole reason
        # to use IMAP search rather than downloading everything and grepping.
        return await self._fetch(source, ["TEXT", text], limit)

    async def _fetch(self, source, criteria: list[str], limit: int) -> list[Item]:
        import asyncio

        provider, account, host, port = parse_location(source.location)
        password = read_secret(SecretRef.make("email", account))
        if not password:
            raise PermissionError(f"no password is stored for {account}")

        # imaplib is synchronous and blocking; run it off the event loop so one
        # slow mailbox cannot stall every other worker in the process.
        return await asyncio.to_thread(
            _fetch_blocking, host, port, account, password, criteria, limit)


def _fetch_blocking(host: str, port: int, account: str, password: str,
                    criteria: list[str], limit: int) -> list[Item]:
    box = _connect(host, port, account, password)
    try:
        box.select("INBOX", readonly=True)
        status, data = box.search(None, *criteria)
        if status != "OK" or not data or not data[0]:
            return []
        ids = data[0].split()[-limit:]          # newest last in IMAP order
        items: list[Item] = []
        for raw_id in reversed(ids):
            # PEEK, not FETCH: `BODY[]` sets \\Seen, and an assistant that
            # silently marked the user's inbox read would deserve to be deleted.
            status, payload = box.fetch(raw_id, "(BODY.PEEK[])")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            items.append(_to_item(account, raw_id.decode(), payload[0][1]))
        return items
    finally:
        _close(box)


def _to_item(account: str, uid: str, raw: bytes) -> Item:
    message = email.message_from_bytes(raw, policy=email.policy.default)
    subject = str(message.get("Subject", "") or "(no subject)")[:300]
    author = str(message.get("From", "") or "")[:200]
    when = None
    try:
        when = parsedate_to_datetime(message.get("Date", ""))
    except (TypeError, ValueError):
        pass

    body = _plain_text(message)[:MAX_BODY]
    return Item(
        item_id=f"{account}:{uid}", title=subject, author=author, at=when,
        link="", meta={"account": account, "uid": uid,
                       "to": str(message.get("To", "") or "")[:200],
                       "list": str(message.get("List-Id", "") or "")[:120]},
        body=Untrusted(text=body, source=f"email:{account}", label=subject))


def _plain_text(message) -> str:
    """The text a person would read. HTML is a last resort and is stripped.

    Preferring `text/plain` is not cosmetic: an HTML part is where invisible
    text, white-on-white instructions and link-label mismatches live, and the
    plain part of a multipart message is the same content without them.
    """
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not _is_attachment(part):
                return _decode(part)
        for part in message.walk():
            if part.get_content_type() == "text/html" and not _is_attachment(part):
                return _strip_html(_decode(part))
        return ""
    text = _decode(message)
    return _strip_html(text) if message.get_content_type() == "text/html" else text


def _is_attachment(part) -> bool:
    return "attachment" in str(part.get("Content-Disposition", "")).lower()


def _decode(part) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:                                 # noqa: BLE001
        return ""
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, "replace")
    except LookupError:
        return payload.decode("utf-8", "replace")


_TAG = re.compile(r"<[^>]+>")
_STYLE = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)


def _strip_html(html: str) -> str:
    text = _STYLE.sub(" ", html or "")
    text = _TAG.sub(" ", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def _connect(host: str, port: int, account: str, password: str) -> imaplib.IMAP4_SSL:
    box = imaplib.IMAP4_SSL(host, port, timeout=TIMEOUT_S)
    box.login(account, password)
    return box


def _close(box) -> None:
    try:
        box.logout()
    except Exception:                                 # noqa: BLE001
        pass


def _safe(exc: Exception) -> str:
    """An error message with no credential in it.

    IMAP servers echo the login line back in some failures, and `str(exc)` on an
    `IMAP4.error` has carried a password more than once in the wild.
    """
    text = str(exc)
    return re.sub(r"(LOGIN|login)\s+\S+\s+\S+", r"\1 …", text)[:200]


MAIL = register(MailConnector())
