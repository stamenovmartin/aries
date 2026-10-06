"""Where ARIES keeps a credential — and every place it must never appear.

THE RULE, AS THE USER STATED IT
-------------------------------
Credentials must never enter prompts, general memory, normal logs, audit
payloads, Git, or agent state. Agents never receive a raw secret.

That is not a guideline here, it is the shape of the module. Nothing in ARIES
outside this file may hold a password; everything else holds a **reference** —
`aries:email:me@example.com` — which is meaningless without the keyring, and
which is therefore safe to write into the database, the audit log, a settings
row, a prompt and a screenshot.

WHERE IT ACTUALLY GOES
----------------------
The OS keyring, over the freedesktop Secret Service — on this machine
`gnome-keyring-daemon`, unlocked by the login password and locked again when the
session ends. That is the same store the user's browser and mail client use, and
the argument for it is not convenience: a secret in a file that ARIES can read
is a secret every process running as the user can read, and ARIES has no
business widening that.

If there is no keyring, **ARIES refuses to store the credential** rather than
falling back to a file. A fallback would be the interesting failure: it would
work, nobody would notice, and the guarantee would be gone.

WHAT A REFERENCE LOOKS LIKE AND WHY
-----------------------------------
`aries:<kind>:<account>` — the kind and the account are not secret, they are how
a person recognises which credential a screen is talking about. Putting them in
the reference means the Connections screen can say "the password for
me@example.com" without ever reading it.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

SERVICE = "aries"

# A reference is safe to store anywhere. This pattern is what makes that
# checkable: a test asserts that nothing outside this module writes something
# that does NOT look like one into the database.
REFERENCE = re.compile(r"^aries:[a-z0-9_.-]+:[^\s:]+$")


class NoKeyring(RuntimeError):
    """There is nowhere safe to put this. ARIES will not improvise."""


class SecretRef(str):
    """A pointer to a credential. Prints as itself and never as the secret.

    A `str` subclass rather than a dataclass so it can be stored, compared and
    formatted like the string it is — while `__repr__` stays honest in a
    traceback, which is where a naive secret wrapper usually leaks.
    """

    __slots__ = ()

    @classmethod
    def make(cls, kind: str, account: str) -> "SecretRef":
        ref = f"{SERVICE}:{kind}:{account}"
        if not REFERENCE.match(ref):
            raise ValueError(f"'{kind}/{account}' does not make a usable reference")
        return cls(ref)

    @property
    def kind(self) -> str:
        return self.split(":", 2)[1]

    @property
    def account(self) -> str:
        return self.split(":", 2)[2]

    def __repr__(self) -> str:      # noqa: D105
        return f"SecretRef({str(self)!r})"


def available() -> tuple[bool, str]:
    """Is there a real keyring? Measured, not assumed."""
    try:
        import keyring
        from keyring.backends import fail
    except ImportError as exc:
        return False, f"the keyring library is not installed ({exc})"
    backend = keyring.get_keyring()
    if isinstance(backend, fail.Keyring):
        return False, ("no keyring backend is available — on a desktop this means "
                       "gnome-keyring or kwallet is not running")
    return True, type(backend).__module__.split(".")[-1]


def store(kind: str, account: str, secret: str) -> SecretRef:
    """Put a credential in the keyring and return the reference to it.

    The secret is not logged, not returned, and not echoed back in any error —
    including the error raised when storing fails, which is the one people
    forget.
    """
    ok, detail = available()
    if not ok:
        raise NoKeyring(
            f"ARIES will not store a credential without a keyring: {detail}. "
            f"It does not fall back to a file — a secret in a file ARIES can read "
            f"is a secret every process running as you can read.")
    if not secret:
        raise ValueError("an empty credential is not a credential")

    import keyring
    ref = SecretRef.make(kind, account)
    try:
        keyring.set_password(SERVICE, str(ref), secret)
    except Exception as exc:                          # noqa: BLE001
        raise NoKeyring(f"the keyring refused to store it: {type(exc).__name__}") from None
    logger.info("stored a credential for %s (reference only: %s)", kind, ref)
    return ref


def read(ref: str) -> str | None:
    """Fetch a credential. The ONLY function in ARIES that returns a secret.

    Callers are expected to hand it straight to the thing that needs it and let
    it go. It is never put in the working set, never in a prompt, and never in a
    return value that gets serialised.
    """
    if not REFERENCE.match(str(ref)):
        raise ValueError(f"{ref!r} is not a credential reference")
    ok, _ = available()
    if not ok:
        return None
    import keyring
    try:
        return keyring.get_password(SERVICE, str(ref))
    except Exception:                                 # noqa: BLE001
        logger.exception("could not read the credential %s", ref)
        return None


def forget(ref: str) -> bool:
    """Remove a credential. Deliberate, never on a timer — see DATA.md."""
    if not REFERENCE.match(str(ref)):
        raise ValueError(f"{ref!r} is not a credential reference")
    ok, _ = available()
    if not ok:
        return False
    import keyring
    try:
        keyring.delete_password(SERVICE, str(ref))
        logger.info("forgot the credential %s", ref)
        return True
    except Exception:                                 # noqa: BLE001
        return False


def present(ref: str) -> bool:
    """Is there a credential behind this reference? Answered without reading it
    into anything that outlives the call."""
    try:
        return read(ref) is not None
    except ValueError:
        return False


def describe(ref: str | None) -> dict:
    """What a screen may say about a credential. Never the credential."""
    if not ref:
        return {"reference": None, "stored": False, "where": "", "account": ""}
    ok, backend = available()
    return {"reference": str(ref), "stored": present(ref) if ok else False,
            "where": f"the OS keyring ({backend})" if ok else "nowhere — no keyring",
            "account": SecretRef(ref).account if REFERENCE.match(str(ref)) else ""}
