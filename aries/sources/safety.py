"""Validating where a source points — the security core of the registry.

A source is the first thing in ARIES that names somewhere ARIES will later GO:
a folder to read, a host to fetch from. Everything downstream — the News Radar,
document ingestion, any agent that asks the registry for somewhere to look —
trusts that the location was checked once, here, when it was added.

So this module refuses rather than warns, and it refuses at ADD time. A source
that cannot be validated is not stored with a flag saying so; it is rejected,
with a reason the user can act on. The alternative — store it and check later —
means the check lives in every consumer, and the one consumer that forgets is
the vulnerability.

PATHS
-----
Three rules, and the order matters:

  1. Expand and RESOLVE first. `~/docs` becomes an absolute path, and every
     symlink is followed. This is not tidiness: a symlink at `~/research`
     pointing to `~/.ssh` would pass any check made against the string the user
     typed. Resolution turns "where they said" into "where it actually is",
     and only the latter is worth checking.
  2. Refuse anything inside `privacy.excluded_paths`. That setting is the user's
     own list of places ARIES must never read, it defaults to `~/.ssh` and
     `~/.gnupg`, and it is `user_only` — no learning loop can widen it. This is
     the first component to enforce it, and enforcing it here means every later
     consumer inherits the guarantee.
  3. Refuse system directories. `/etc`, `/proc`, `/sys`, `/dev`, `/boot` and
     `/root` are not places a personal assistant reads for information; a source
     pointing at one is a mistake or an attack, and neither deserves the benefit
     of the doubt.

URLS
----
Scheme allowlisted per source type, no credentials embedded (they would sit in
the database in plaintext, and §32 says secrets belong in the keyring), and
literal private, loopback, link-local or reserved addresses refused unless the
user has explicitly allowed them.

**An honest limit.** The address check looks at the literal host as written. It
does NOT resolve the hostname, so a public name that resolves to 127.0.0.1 — or
one that resolves differently when it is actually fetched (DNS rebinding) —
passes. Closing that properly means resolving at FETCH time and pinning the
address, which belongs in whatever does the fetching, not here. This is a guard
against mistakes and casual misuse, and it is worth having; it is not a complete
defence against a determined attacker, and calling it one would be worse than
not having it. Recorded as a risk in the Build Journal for the component that
will fetch.
"""
from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from aries.sources.types import SourceType

# Directories a personal assistant has no business reading as a "source".
SYSTEM_PATHS = ("/etc", "/proc", "/sys", "/dev", "/boot", "/root", "/var/lib", "/usr/lib")

# Hostnames that mean "this machine" without being an IP literal.
LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}


class SourceRejected(ValueError):
    """A location the registry refuses to store, with a reason for the user."""

    def __init__(self, message, *, code="INVALID_ARGUMENT"):
        super().__init__(message)
        self.code = code


@dataclass
class Checked:
    """A validated location: what the user typed, and what it really is."""

    location: str                # normalised, stored form
    original: str                # what the user typed
    outbound: bool
    detail: dict

    def as_dict(self) -> dict:
        return {"location": self.location, "original": self.original,
                "outbound": self.outbound, **self.detail}


def _under(path: str, parent: str) -> bool:
    """True when `path` is `parent` or lies inside it. Compares resolved,
    normalised paths so `/home/u/../u/.ssh` cannot slip past `/home/u/.ssh`."""
    try:
        return os.path.commonpath([path, parent]) == parent
    except ValueError:                      # different drives / relative mix
        return False


def check_path(raw: str, *, excluded: list[str], must_exist: bool = True) -> Checked:
    """Validate a local path source."""
    if not raw or not raw.strip():
        raise SourceRejected("a path is required")
    original = raw.strip()

    expanded = os.path.expanduser(os.path.expandvars(original))
    if not os.path.isabs(expanded):
        raise SourceRejected(
            f"'{original}' is not an absolute path — give a full path such as ~/Documents/research")

    # Resolve symlinks BEFORE any check: the target is what will actually be read.
    resolved = os.path.realpath(expanded)

    for pattern in excluded or []:
        ex = os.path.realpath(os.path.expanduser(os.path.expandvars(str(pattern).strip())))
        if not ex or ex == os.sep:
            continue
        if _under(resolved, ex):
            via = "" if resolved == expanded else f" (it resolves to {resolved})"
            raise SourceRejected(
                f"'{original}' is inside {pattern}, which privacy.excluded_paths forbids ARIES "
                f"from reading{via}", code="PATH_EXCLUDED")

    for sysdir in SYSTEM_PATHS:
        if _under(resolved, sysdir):
            raise SourceRejected(
                f"'{original}' is inside the system directory {sysdir} — ARIES does not read "
                f"system directories as information sources", code="PROTECTED_PATH")

    if must_exist:
        if not os.path.exists(resolved):
            raise SourceRejected(f"'{original}' does not exist")
        if not os.path.isdir(resolved):
            raise SourceRejected(f"'{original}' is not a directory")
        if not os.access(resolved, os.R_OK | os.X_OK):
            raise SourceRejected(f"'{original}' is not readable by this user")

    return Checked(location=resolved, original=original, outbound=False,
                   detail={"kind": "path", "followed_symlink": resolved != expanded,
                           "exists": os.path.exists(resolved)})


def check_url(raw: str, *, schemes: tuple[str, ...], allow_private: bool = False) -> Checked:
    """Validate a URL source."""
    if not raw or not raw.strip():
        raise SourceRejected("a URL is required")
    original = raw.strip()
    parts = urlsplit(original)

    if not parts.scheme:
        raise SourceRejected(f"'{original}' has no scheme — write it as https://…")
    if parts.scheme.lower() not in schemes:
        raise SourceRejected(
            f"scheme '{parts.scheme}' is not allowed for this source type "
            f"(allowed: {', '.join(schemes)})")
    if not parts.hostname:
        raise SourceRejected(f"'{original}' has no host")
    if parts.username or parts.password:
        raise SourceRejected(
            "credentials must not be embedded in a source URL — they would be stored in "
            "plain text. Add the source without them and connect it under Integrations")

    host = parts.hostname.lower()
    private_reason = _private_address_reason(host)
    if private_reason and not allow_private:
        raise SourceRejected(
            f"'{host}' is {private_reason}. ARIES refuses sources pointing at this machine or a "
            f"private network by default — enable sources.allow_private_addresses if that is "
            f"really what you want")

    return Checked(location=original, original=original, outbound=True,
                   detail={"kind": "url", "host": host, "scheme": parts.scheme.lower(),
                           "private": bool(private_reason)})


def _private_address_reason(host: str) -> str | None:
    """Why this literal host is not a public address, or None if it looks public.

    Only the literal is examined — see the module docstring on what that does and
    does not protect against.
    """
    if host in LOCAL_HOSTNAMES or host.endswith(".localhost"):
        return "a loopback name"
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None                          # a hostname; not resolved here, on purpose
    if ip.is_loopback:
        return "a loopback address"
    # Link-local BEFORE private: Python marks 169.254.0.0/16 as both, and
    # "link-local" is the more useful word — 169.254.169.254 is the cloud
    # metadata endpoint, and a user who typed it deserves to be told which
    # thing they actually aimed at.
    if ip.is_link_local:
        return "a link-local address (the cloud metadata range)" if str(ip).startswith("169.254") \
            else "a link-local address"
    if ip.is_private:
        return "a private address"
    if ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return "a reserved address"
    return None


def check_connector(raw: str) -> Checked:
    """Validate a connector-addressed source, e.g. `gmail:me@example.com`.

    The form is `<connector>:<target>`. Nothing is contacted: whether the
    connector exists and what it may do is decided when it is connected, under
    the Integrations permission model (§21–§23).
    """
    if not raw or ":" not in raw:
        raise SourceRejected("a connector source looks like '<connector>:<target>', e.g. gmail:me@example.com")
    connector, _, target = raw.strip().partition(":")
    if not connector.strip() or not target.strip():
        raise SourceRejected("both a connector and a target are required, e.g. google:primary")
    return Checked(location=f"{connector.strip().lower()}:{target.strip()}", original=raw.strip(),
                   outbound=True, detail={"kind": "connector", "connector": connector.strip().lower(),
                                          "target": target.strip()})


def check(raw: str, stype: SourceType, *, excluded: list[str], allow_private: bool = False,
          must_exist: bool = True) -> Checked:
    """Validate a location against its declared type."""
    if stype.location_kind == "path":
        return check_path(raw, excluded=excluded, must_exist=must_exist)
    if stype.location_kind == "url":
        return check_url(raw, schemes=stype.schemes or ("http", "https"), allow_private=allow_private)
    if stype.location_kind == "connector":
        return check_connector(raw)
    raise SourceRejected(f"source type '{stype.name}' has an unknown location kind")
