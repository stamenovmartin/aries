"""Symmetric encryption for credentials at rest, so a database dump is not a
keyring. Lifted from backend/app/core/crypto.py.

With no CREDENTIALS_KEY this module RAISES — it never stores plaintext and never
uses a default key. HMAC-SHA256 in counter mode + encrypt-then-MAC with
per-record subkeys (HKDF salted by the nonce). `v1:` tagged so AES-GCM can be
added as v2 without a rewrite. AAD binds each ciphertext to its row.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

VERSION = "v1"
_SUPPORTED = {"v1"}
ENV_VAR = "CREDENTIALS_KEY"
NONCE_LEN, TAG_LEN, MIN_KEY_LEN = 16, 32, 32


class CryptoRefused(RuntimeError):
    pass


class KeyUnavailable(CryptoRefused):
    pass


class CiphertextInvalid(CryptoRefused):
    pass


def generate_key() -> str:
    return secrets.token_urlsafe(48)


def _master() -> bytes:
    raw = (os.environ.get(ENV_VAR) or "").strip()
    if not raw:
        raise KeyUnavailable(f"No encryption key ({ENV_VAR}). Refusing to save or read a secret — "
                             "plaintext storage is not a fallback.")
    if len(raw) < MIN_KEY_LEN:
        raise KeyUnavailable(f"{ENV_VAR} is too short ({len(raw)} chars, need ≥ {MIN_KEY_LEN}).")
    return raw.encode("utf-8")


def is_configured() -> bool:
    try:
        _master(); return True
    except KeyUnavailable:
        return False


def _expand(prk: bytes, info: bytes, length: int) -> bytes:
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block; counter += 1
    return out[:length]


def _subkeys(master: bytes, nonce: bytes):
    prk = hmac.new(nonce, master, hashlib.sha256).digest()
    return _expand(prk, b"agentic/credentials/enc", 32), _expand(prk, b"agentic/credentials/mac", 32)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray(); counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest(); counter += 1
    return bytes(out[:length])


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, stream))


def _mac_input(nonce, ct, aad):
    return VERSION.encode() + b"\x00" + nonce + ct + b"\x00" + aad.encode("utf-8")


def encrypt(plaintext: str, *, aad: str = "") -> str:
    if plaintext is None:
        raise CryptoRefused("Nothing to encrypt — the value is empty.")
    master = _master()
    nonce = secrets.token_bytes(NONCE_LEN)
    enc_key, mac_key = _subkeys(master, nonce)
    data = plaintext.encode("utf-8")
    ct = _xor(data, _keystream(enc_key, nonce, len(data)))
    tag = hmac.new(mac_key, _mac_input(nonce, ct, aad), hashlib.sha256).digest()
    return f"{VERSION}:" + base64.urlsafe_b64encode(nonce + tag + ct).decode()


def decrypt(token: str, *, aad: str = "") -> str:
    master = _master()
    if not token or ":" not in token:
        raise CiphertextInvalid("Not an encrypted record — no version tag.")
    version, _, body = token.partition(":")
    if version not in _SUPPORTED:
        raise CiphertextInvalid(f"Unknown encryption version '{version}'.")
    try:
        blob = base64.urlsafe_b64decode(body.encode())
    except Exception:
        raise CiphertextInvalid("Corrupt record — cannot decode.")
    if len(blob) < NONCE_LEN + TAG_LEN:
        raise CiphertextInvalid("Truncated record.")
    nonce, tag, ct = blob[:NONCE_LEN], blob[NONCE_LEN:NONCE_LEN + TAG_LEN], blob[NONCE_LEN + TAG_LEN:]
    enc_key, mac_key = _subkeys(master, nonce)
    expected = hmac.new(mac_key, _mac_input(nonce, ct, aad), hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise CiphertextInvalid("Record does not verify under this key: key changed, record altered, or it belongs to another row.")
    return _xor(ct, _keystream(enc_key, nonce, len(ct))).decode("utf-8")


def hint_for(value: str) -> str:
    v = (value or "").strip()
    return ("…" + v[-4:]) if len(v) >= 12 else "••••"


def fingerprint() -> str | None:
    try:
        master = _master()
    except KeyUnavailable:
        return None
    return hashlib.pbkdf2_hmac("sha256", master, b"agentic/credentials/fingerprint", 200_000, dklen=6).hex()


def describe() -> dict:
    configured = is_configured()
    return {"configured": configured, "version": VERSION,
            "fingerprint": fingerprint() if configured else None,
            "note": None if configured else f"No {ENV_VAR}. Secrets can be neither saved nor read until a key is set."}
