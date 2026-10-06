"""ARIES Integrations — the boundary between ARIES and everything outside it.

    secrets.py    the OS keyring, and every place a credential must never appear
    untrusted.py  external content is DATA; it can never become an action
    base.py       what a connector is — read-only, by having no write method
    files.py      local folders: no credential, no network, nothing leaves
    mail.py       a mailbox over IMAP, read-only
    service.py    connect, read, search — audited, and into the working set
    settings.py   the switches, off by default

The rule the whole package is built around: **content can never widen what
ARIES may do.** A model that has read your mail may produce a summary and a
category. It cannot produce a goal, a tool call, a recipient or a setting. The
worst a successful prompt injection achieves is a wrong summary.
"""
from __future__ import annotations

from aries.connect import base, files, secrets, service, untrusted
from aries.connect import mail as _mail                # noqa: F401  registers the connector
from aries.connect import settings as _settings        # noqa: F401  registers settings
from aries.connect import automation as _automation    # noqa: F401  the Attention Pass

__all__ = ["base", "files", "secrets", "service", "untrusted"]
