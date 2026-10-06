"""Runtime-mutable settings the operator can change without a restart.

Lifted from backend/app/core/runtime.py. `settings` is fixed at process start;
this is a small JSON file under `data_dir` holding the switches that must be
flippable from a UI or an API call: the active provider, strict mode, the
autopilot toggle, dry-run and the live-tool allowlist.

Two rules preserved from the original:
  * atomic writes (tmp + rename) so a crash mid-write cannot reset a switch;
  * under APP_ENV=test the env var is the truth — a test must never read the
    live switch, or every test silently runs against production state.
"""
from __future__ import annotations

import json
import logging
import os

from agentic_core.config.settings import settings

logger = logging.getLogger(__name__)

ALLOWED_PROVIDERS = ("cli", "ollama", "openai", "template")


def _store_path() -> str:
    return os.environ.get("RUNTIME_STORE",
                          os.path.join(settings.data_dir, "runtime.json"))


_state: dict = {}


def _load() -> None:
    global _state
    try:
        with open(_store_path(), encoding="utf-8") as f:
            _state = json.load(f) or {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        _state = {}


def _save() -> None:
    path = _store_path()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, indent=1)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("Could not persist runtime settings to %s: %s", path, e)


def _is_test_env() -> bool:
    return (os.environ.get("APP_ENV") or "").strip().lower() == "test"


_load()


def get(key: str, default=None):
    return _state.get(key, default)


def set_value(key: str, value) -> None:
    _state[key] = value
    _save()


def get_ai_provider() -> str:
    return _state.get("ai_provider") or settings.ai_provider


def set_ai_provider(provider: str) -> str:
    if provider not in ALLOWED_PROVIDERS:
        raise ValueError(f"Unknown provider '{provider}'. Allowed: {', '.join(ALLOWED_PROVIDERS)}")
    set_value("ai_provider", provider)
    return provider


def get_require_ai() -> bool:
    v = _state.get("require_ai")
    return settings.require_ai if v is None else bool(v)


def set_require_ai(value: bool) -> bool:
    set_value("require_ai", bool(value))
    return bool(value)


def get_autopilot() -> bool:
    return bool(_state.get("autopilot", False))


def set_autopilot(value: bool) -> bool:
    set_value("autopilot", bool(value))
    return bool(value)


def get_dry_run() -> bool:
    """Whether side-effecting tools are simulated. In a test process the env
    var wins so a runtime file cannot wire a test to live state."""
    if _is_test_env():
        return bool(settings.dry_run)
    v = _state.get("dry_run")
    return bool(settings.dry_run) if v is None else bool(v)


def set_dry_run(value: bool) -> bool:
    set_value("dry_run", bool(value))
    return bool(value)


def get_live_tools() -> str:
    if _is_test_env():
        return settings.live_tools or ""
    v = _state.get("live_tools")
    return (settings.live_tools or "") if v is None else str(v)


def set_live_tools(value: str) -> str:
    set_value("live_tools", str(value or ""))
    return str(value or "")


def get_system_prompt_override() -> str | None:
    val = _state.get("system_prompt")
    return val if (val and val.strip()) else None


def set_system_prompt_override(text: str) -> str | None:
    text = (text or "").strip()
    if text:
        _state["system_prompt"] = text
    else:
        _state.pop("system_prompt", None)
    _save()
    return get_system_prompt_override()


def get_operator_prompt() -> str:
    """Operator-written instructions appended to every agent's system prompt."""
    return _state.get("operator_prompt") or ""


def set_operator_prompt(text: str) -> str:
    set_value("operator_prompt", (text or "").strip())
    return get_operator_prompt()
