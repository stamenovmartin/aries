"""One JSON object per log line, with the join keys already in it, and three
layers of secret redaction. Lifted from backend/app/core/logging_setup.py.

  ts · severity · logger · msg · env · correlation_id · user_id · task_id ·
  execution_id · agent · tool · error{type,class,action}

Redaction: (1) by key name, (2) by value shape, (3) by exact value of every
secret-looking environment variable. Nothing here may raise.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import fields as dataclass_fields, is_dataclass
from datetime import datetime, timezone

from agentic_core.observability.correlation import current as correlation_id
from agentic_core.security import environments

REDACTED = "***"
_extra_context: ContextVar[dict] = ContextVar("log_extra_context", default={})


def context() -> dict:
    return dict(_extra_context.get())


def bind(**fields):
    merged = {**_extra_context.get(), **{k: v for k, v in fields.items() if v is not None}}
    return _extra_context.set(merged)


def unbind(token) -> None:
    _extra_context.reset(token)


@contextmanager
def log_context(**fields):
    """Every line inside this block carries these fields (task_id, agent, tool…)."""
    token = bind(**fields)
    try:
        yield
    finally:
        unbind(token)


_SECRET_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|apikey|authorization|auth|cookie|"
    r"credential|private[_-]?key|client[_-]?secret|session|ciphertext|bearer)", re.I)

_SECRET_SHAPES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"EAA[A-Za-z0-9_-]{20,}"), REDACTED),
    (re.compile(r"\b\d{6,12}:AA[A-Za-z0-9_-]{30,}"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"\bgsk_[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"\bagc_[A-Za-z0-9_-]{12,}"), REDACTED),           # our own ApiToken prefix
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}"), f"Bearer {REDACTED}"),
    (re.compile(r"(?i)(x-api-key|authorization)(\s*[:=]\s*)\S+"), r"\1\2" + REDACTED),
    (re.compile(r"(://[^:/\s]+:)[^@\s]+(@)"), r"\1" + REDACTED + r"\2"),   # DSN password
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), REDACTED),
)

_ENV_RESCAN_SECONDS = 30.0
_env_secrets: tuple[str, ...] = ()
_env_secrets_at = 0.0
_env_lock = threading.Lock()
_MIN_SECRET_LEN = 8


def _environment_secrets() -> tuple[str, ...]:
    global _env_secrets, _env_secrets_at
    now = time.monotonic()
    if now - _env_secrets_at < _ENV_RESCAN_SECONDS and _env_secrets_at:
        return _env_secrets
    with _env_lock:
        values = {v.strip() for k, v in os.environ.items()
                  if len((v or "").strip()) >= _MIN_SECRET_LEN and _SECRET_KEY.search(k)}
        _env_secrets = tuple(sorted(values, key=len, reverse=True))
        _env_secrets_at = now
    return _env_secrets


def redact_text(text: str) -> str:
    if not text:
        return text
    out = text
    for pattern, replacement in _SECRET_SHAPES:
        out = pattern.sub(replacement, out)
    for value in _environment_secrets():
        if value in out:
            out = out.replace(value, REDACTED)
    return out


class _Redacted:
    __slots__ = ("_name", "_fields")

    def __init__(self, name, fields):
        self._name, self._fields = name, fields

    def __repr__(self):
        return f"{self._name}({', '.join(f'{k}={v!r}' for k, v in self._fields.items())})"

    __str__ = __repr__

    def as_dict(self):
        return {"_type": self._name, **self._fields}


_MAX_DEPTH, _MAX_ATTRS = 4, 40


def scrub(value, _depth: int = 0):
    if _depth > _MAX_DEPTH:
        return "…"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: (REDACTED if isinstance(k, str) and _SECRET_KEY.search(k) else scrub(v, _depth + 1))
                for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        s = [scrub(v, _depth + 1) for v in value]
        return tuple(s) if isinstance(value, tuple) else s
    if is_dataclass(value) and not isinstance(value, type):
        return _Redacted(type(value).__name__,
                         {f.name: (REDACTED if _SECRET_KEY.search(f.name) else scrub(getattr(value, f.name, None), _depth + 1))
                          for f in dataclass_fields(value)})
    attrs = getattr(value, "__dict__", None)
    if isinstance(attrs, dict) and 0 < len(attrs) <= _MAX_ATTRS:
        return _Redacted(type(value).__name__,
                         {k: (REDACTED if _SECRET_KEY.search(k) else scrub(v, _depth + 1))
                          for k, v in attrs.items() if not k.startswith("_")})
    return redact_text(str(value))


_STANDARD = {"name", "msg", "args", "levelname", "levelno", "pathname", "filename", "module",
             "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created", "msecs",
             "relativeCreated", "thread", "threadName", "processName", "process", "taskName",
             "message", "asctime"}
_PROMOTED = ("user_id", "task_id", "execution_id", "agent", "tool", "correlation_id")


def _classify(exc):
    if exc is None:
        return None
    out = {"type": type(exc).__name__, "message": redact_text(str(exc))[:400], "class": None, "action": None}
    try:
        from agentic_core.orchestrator.errors import classify
        c = classify(str(exc))
        out["class"], out["action"] = c.cls.value, c.action
    except Exception:
        pass
    return out


def _user_id():
    try:
        from agentic_core.security import principal
        p = principal.current()
        return p.user_id if p else None
    except Exception:
        return None


class JsonFormatter(logging.Formatter):
    def __init__(self, *, service: str = "agentic-core"):
        super().__init__()
        self.service = service

    def format(self, record):  # noqa: A003
        try:
            return json.dumps(self._payload(record), ensure_ascii=False, default=self._fallback)
        except Exception as e:
            return json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "severity": record.levelname,
                               "logger": record.name, "msg": "log line could not be serialised",
                               "env": environments.current(), "formatter_error": type(e).__name__})

    @staticmethod
    def _fallback(obj):
        return obj.as_dict() if isinstance(obj, _Redacted) else redact_text(str(obj))

    def _message(self, record):
        msg = record.msg if isinstance(record.msg, str) else str(scrub(record.msg))
        if record.args:
            try:
                msg = msg % scrub(record.args)
            except Exception:
                msg = f"{msg} {scrub(record.args)!r}"
        return redact_text(msg)[:8000]

    def _payload(self, record):
        ctx = _extra_context.get()
        extra = {k: scrub(v) for k, v in record.__dict__.items()
                 if k not in _STANDARD and not k.startswith("_") and k not in _PROMOTED}
        exc = record.exc_info[1] if record.exc_info else None
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "severity": record.levelname, "service": self.service, "logger": record.name,
            "msg": self._message(record), "env": environments.current(),
            "correlation_id": getattr(record, "correlation_id", None) or _safe(correlation_id),
            "user_id": getattr(record, "user_id", None) or _user_id(),
            "task_id": getattr(record, "task_id", None) or ctx.get("task_id"),
            "execution_id": getattr(record, "execution_id", None) or ctx.get("execution_id"),
            "agent": getattr(record, "agent", None) or ctx.get("agent"),
            "tool": getattr(record, "tool", None) or ctx.get("tool"),
            "error": _classify(exc),
            "source": {"file": record.filename, "line": record.lineno, "func": record.funcName},
        }
        if record.exc_info:
            payload["traceback"] = redact_text(self.formatException(record.exc_info))[:6000]
        if extra:
            payload["extra"] = extra
        return payload


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


_installed = False
_ADOPT = ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "sqlalchemy.engine", "httpx")


def setup_logging(*, level: str | None = None, service: str = "agentic-core", force: bool = False) -> dict:
    global _installed
    if _installed and not force:
        return {"installed": True, "changed": False}
    resolved = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()
    if resolved not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        resolved = "INFO"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service=service))
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(resolved)
    for name in _ADOPT:
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            lg.removeHandler(h)
        lg.propagate = True
    logging.getLogger("sqlalchemy.engine").setLevel(os.environ.get("SQL_LOG_LEVEL", "WARNING").upper())
    _installed = True
    return {"installed": True, "changed": True, "level": resolved, "env": environments.current(), "format": "json"}
