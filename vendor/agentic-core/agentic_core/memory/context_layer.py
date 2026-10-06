"""The shared context layer — short-term memory with a contract.
Lifted from backend/app/services/context_layer/__init__.py.

A folder per module; each document has a title/author/updated/summary front
matter and a body. `digest()` (summaries only, bounded) is appended to every
agent's system prompt, so agents never start from nothing. Files on purpose:
an operator can read them without a screen, and every document says who wrote
it and when."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

MODULES: list[str] = ["intelligence", "analytics", "strategy", "production", "execution", "director"]
_SLUG_RE = re.compile(r"[^a-z0-9\-]+")
_FRONT_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def context_dir() -> str:
    from agentic_core.config.settings import settings
    return os.environ.get("CONTEXT_DIR", os.path.join(settings.data_dir, "context"))


def register_module(name: str) -> None:
    if name not in MODULES:
        MODULES.append(name)


def _slug(name: str) -> str:
    s = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    if not s:
        raise ValueError("empty document name")
    return s[:80]


def _module_dir(module: str) -> str:
    if module not in MODULES:
        raise ValueError(f"unknown module: {module!r} (allowed: {', '.join(MODULES)})")
    return os.path.join(context_dir(), module)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _atomic_write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write(module: str, name: str, *, title: str, body: str, summary: str = "",
          data=None, author: str = "system") -> dict:
    """Same name = new version, not a duplicate. `summary` is ONE sentence — it is
    what enters the digest every agent reads."""
    slug = _slug(name); updated = _now_iso()
    front = f"---\ntitle: {title.strip()}\nauthor: {author}\nupdated: {updated}\nsummary: {(summary or title).strip()}\n---\n"
    _atomic_write(os.path.join(_module_dir(module), f"{slug}.md"), front + body.strip() + "\n")
    if data is not None:
        _atomic_write(os.path.join(_module_dir(module), f"{slug}.json"), json.dumps(data, ensure_ascii=False, indent=1, default=str))
    return {"module": module, "name": slug, "updated": updated}


def append_line(module: str, name: str, line: str, *, keep_last: int = 400) -> None:
    """Journal mode: one line per event, trimmed to the last `keep_last`."""
    slug = _slug(name)
    path = os.path.join(_module_dir(module), f"{slug}.log")
    lines: list[str] = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    lines.append(f"{_now_iso()}  {line.strip()}")
    _atomic_write(path, "\n".join(lines[-keep_last:]) + "\n")


def read_log(module: str, name: str, *, last: int = 50) -> list[str]:
    path = os.path.join(_module_dir(module), f"{_slug(name)}.log")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()[-last:]


def read(module: str, name: str) -> dict | None:
    path = os.path.join(_module_dir(module), f"{_slug(name)}.md")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    meta: dict = {}; body = raw
    m = _FRONT_RE.match(raw)
    if m:
        body = raw[m.end():]
        for ln in m.group(1).splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1); meta[k.strip()] = v.strip()
    return {"title": meta.get("title", name), "author": meta.get("author", ""), "updated": meta.get("updated", ""),
            "summary": meta.get("summary", ""), "body": body.strip()}


def read_data(module: str, name: str):
    path = os.path.join(_module_dir(module), f"{_slug(name)}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def listing() -> dict:
    out: dict = {}
    for module in MODULES:
        d = os.path.join(context_dir(), module); docs = []
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".md"):
                    doc = read(module, fn[:-3])
                    if doc:
                        docs.append({"name": fn[:-3], "title": doc["title"], "author": doc["author"],
                                     "updated": doc["updated"], "summary": doc["summary"], "chars": len(doc["body"])})
        out[module] = docs
    return out


def digest(max_chars: int = 1600) -> str:
    """Summary lines only — the context should steer, not crowd out the prompt."""
    parts = [f"[{module}/{d['name']}] {d['summary']}" for module, docs in listing().items() for d in docs]
    if not parts:
        return ""
    text = "\n".join(parts)
    return text[:max_chars].rsplit("\n", 1)[0] if len(text) > max_chars else text
