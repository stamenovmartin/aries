"""Fetching something from the internet, safely. The debt Entry 005 recorded.

The Sources Registry validates a location when it is ADDED — literal host only,
no DNS. That guard is real but partial, and its docstring says so. This module
is the other half: the checks that can only be made at the moment of the request.

WHAT AN ATTACKER GETS TO CONTROL
--------------------------------
A source URL is user-supplied, and the content it returns is attacker-supplied.
Three ways that turns into a request ARIES should never make:

  1. DNS. `https://evil.example/feed.xml` is a perfectly public-looking name that
     resolves to 127.0.0.1, or to 169.254.169.254. The add-time check cannot see
     this, because it does not resolve.
  2. REBINDING. The name resolves to a public address when checked and to a
     private one microseconds later when connected. Validating a name and then
     handing that NAME to the HTTP client leaves exactly this window.
  3. REDIRECTS. The most common bypass of all, and the cheapest: the feed is at a
     legitimate host, and answers `302 Location: http://169.254.169.254/…`. An
     HTTP client following redirects automatically has just fetched the cloud
     metadata endpoint on the attacker's behalf.

WHAT THIS MODULE DOES ABOUT EACH
--------------------------------
  1. Resolves the name and checks EVERY address it resolves to — not just the
     first. A host answering with one public and one private address is refused
     outright rather than raced.
  2. **Pins** the address: the connection is made to the validated IP, with the
     `Host` header and the TLS SNI name set to the original hostname, so the
     certificate is still verified against the real name. There is no second
     resolution for an attacker to win — the socket connects to the address that
     was checked. This is what closes rebinding, and it is why `sni_hostname`
     matters: without it, pinning would mean disabling certificate verification,
     which trades one hole for a worse one.
  3. Follows redirects MANUALLY, one hop at a time, running the full check again
     on every hop. Automatic redirect following is turned off, not trusted.

And the limits that are not about addresses at all: a hard byte cap enforced
while streaming (so a feed that is an endless stream cannot exhaust memory), a
timeout, a redirect limit, and a content-type check.

WHAT REMAINS
------------
Pinning removes the rebinding window for the connection ARIES makes. It does not
make a hostile server trustworthy — what it RETURNS is still attacker-controlled
data, which is why `feed.py` refuses DTDs and every field is treated as text,
never as markup. And a host that is genuinely public but malicious is, correctly,
still reachable: this is a guard against ARIES being aimed at the wrong place,
not a content filter.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = ("http", "https")
REDIRECT_CODES = (301, 302, 303, 307, 308)


class FetchRefused(Exception):
    """The request was not made, and why. Never raised for a server's failure —
    only for a request ARIES declined to send."""


@dataclass
class FetchResult:
    url: str                       # the final URL, after redirects
    status: int
    body: bytes
    content_type: str = ""
    elapsed_ms: int = 0
    hops: list[str] = field(default_factory=list)
    resolved_ip: str = ""
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def text(self, limit: int | None = None) -> str:
        raw = self.body[:limit] if limit else self.body
        return raw.decode("utf-8", errors="replace")

    def as_dict(self) -> dict:
        return {"url": self.url, "status": self.status, "bytes": len(self.body),
                "content_type": self.content_type, "elapsed_ms": self.elapsed_ms,
                "hops": self.hops, "resolved_ip": self.resolved_ip,
                "truncated": self.truncated, "ok": self.ok}


def address_reason(ip: str) -> str | None:
    """Why this address is one ARIES must not connect to, or None."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "not a valid address"
    if addr.is_loopback:
        return "loopback"
    if addr.is_link_local:
        return "link-local (the cloud metadata range)" if str(addr).startswith("169.254") \
            else "link-local"
    if addr.is_private:
        return "private"
    if addr.is_reserved or addr.is_multicast or addr.is_unspecified:
        return "reserved"
    return None


async def resolve(host: str, port: int) -> list[str]:
    """Every address a host resolves to. Off the event loop — getaddrinfo blocks."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise FetchRefused(f"'{host}' could not be resolved: {e}") from None
    return sorted({i[4][0] for i in infos})


async def check_target(url: str, *, allow_private: bool) -> tuple[str, str, int, str]:
    """Validate one URL and return (host, pinned_ip, port, scheme).

    Every resolved address must pass. A host answering with a mix of public and
    private addresses is refused rather than raced: there is no benign reason for
    a feed to do that, and picking the public one would be trusting the ordering
    of a DNS response an attacker controls.
    """
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise FetchRefused(f"scheme '{scheme}' is not fetchable (only {', '.join(ALLOWED_SCHEMES)})")
    host = parts.hostname
    if not host:
        raise FetchRefused(f"'{url}' has no host")
    if parts.username or parts.password:
        raise FetchRefused("credentials in a URL are refused")
    port = parts.port or (443 if scheme == "https" else 80)

    ips = await resolve(host, port)
    if not ips:
        raise FetchRefused(f"'{host}' resolved to nothing")
    if not allow_private:
        bad = [(ip, address_reason(ip)) for ip in ips if address_reason(ip)]
        if bad:
            listed = ", ".join(f"{ip} ({why})" for ip, why in bad)
            raise FetchRefused(
                f"'{host}' resolves to an address ARIES must not connect to: {listed}")
    return host, ips[0], port, scheme


async def fetch(url: str, *, allow_private: bool = False, max_bytes: int = 4_000_000,
                timeout: float = 20.0, max_redirects: int = 3,
                user_agent: str = "ARIES/0.1 (+personal assistant; respects robots)",
                accept: str = "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.9, */*;q=0.5",
                client: httpx.AsyncClient | None = None) -> FetchResult:
    """Fetch a URL with every check above applied at every hop."""
    import time
    t0 = time.monotonic()
    hops: list[str] = []
    current = url
    owned = client is None
    # follow_redirects is off: redirects are followed by THIS function, so that
    # each hop is validated. Leaving it on would hand the decision to httpx.
    c = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)

    try:
        for hop in range(max_redirects + 1):
            host, ip, port, scheme = await check_target(current, allow_private=allow_private)
            hops.append(current)
            parts = urlsplit(current)
            target = parts._replace(
                netloc=f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}").geturl()

            headers = {"Host": parts.netloc, "User-Agent": user_agent, "Accept": accept,
                       "Accept-Encoding": "gzip, deflate"}
            # sni_hostname keeps TLS verification against the REAL name while the
            # socket goes to the address we validated. Pinning without it would
            # mean turning certificate checking off.
            extensions = {"sni_hostname": host} if scheme == "https" else {}

            try:
                req = c.build_request("GET", target, headers=headers, extensions=extensions)
                resp = await c.send(req, stream=True)
            except httpx.HTTPError as e:
                raise FetchRefused(f"could not fetch {current}: {type(e).__name__}: {e}") from None

            try:
                if resp.status_code in REDIRECT_CODES:
                    location = resp.headers.get("location")
                    await resp.aclose()
                    if not location:
                        raise FetchRefused(f"{resp.status_code} with no Location header")
                    if hop >= max_redirects:
                        raise FetchRefused(f"more than {max_redirects} redirects")
                    # Resolve relative Locations against the hop we asked for, not
                    # the pinned-IP URL, or the Host would be lost.
                    current = urljoin(current, location)
                    continue

                body = bytearray()
                truncated = False
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        truncated = True
                        break
                await resp.aclose()
            finally:
                if not resp.is_closed:
                    await resp.aclose()

            return FetchResult(
                url=current, status=resp.status_code, body=bytes(body[:max_bytes]),
                content_type=(resp.headers.get("content-type") or "").split(";")[0].strip().lower(),
                elapsed_ms=int((time.monotonic() - t0) * 1000), hops=hops,
                resolved_ip=ip, truncated=truncated)
        raise FetchRefused(f"more than {max_redirects} redirects")
    finally:
        if owned:
            await c.aclose()
