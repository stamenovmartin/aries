"""Local-first inference compatibility API and settings.

Rules and OS probes remain deterministic. Legacy callers are always local;
foreground M14 planners may use explicitly enabled cloud routing. No runtime
failure itself authorizes sending data remotely. Concrete runtime adapters,
usage accounting and the constrained router live in this package.
"""
from __future__ import annotations

import logging
import subprocess

from aries.settings.schema import SettingDef, define

from . import settings as router_settings
from . import models as models
from .providers import loopback_url

logger = logging.getLogger(__name__)

S = "intelligence"

define(SettingDef("intelligence.location", str, "local", "Where ARIES thinks",
                  "'local' enables the local model. Separate cloud_enabled policy controls "
                  "explicit foreground escalation; background workers remain local. "
                  "'none' switches language models off "
                  "entirely; ARIES keeps every deterministic capability.",
                  S, control="choice", choices=["local", "none"], user_only=True))

define(SettingDef("intelligence.local_model", str, "qwen2.5:7b", "The local model",
                  "Which model the configured local runtime should use. It must exist — ARIES will "
                  "not download several gigabytes without being asked.",
                  S, control="text"))

define(SettingDef("intelligence.local_url", str, "http://127.0.0.1:11434",
                  "Where the local model answers",
                  "Local runtime address. Only literal loopback URLs are accepted, preventing access from "
                  "the network.",
                  S, control="text", advanced=True, validator=loopback_url))


async def arm(db) -> dict:
    """Point the engine at the model ARIES's settings name. Returns what is now true.

    Called at the point of use rather than at startup, so changing the setting
    takes effect on the next request instead of the next restart.
    """
    from agentic_core.config import runtime
    from agentic_core.config.settings import settings

    from aries.settings import SettingsService
    s = SettingsService(db)
    location = str(await s.get("intelligence.location"))
    model = str(await s.get("intelligence.local_model"))
    url = loopback_url(str(await s.get("intelligence.local_url")))

    if location == "local":
        # Mutated rather than re-read from the environment: these are pydantic
        # settings fields, and the alternative is asking the user to edit a
        # .env file to change a preference that has a switch in Settings.
        settings.ollama_model = model
        settings.ollama_base_url = loopback_url(str(await s.get("intelligence.gateway_url"))) if await s.get("intelligence.gateway_enabled") else url
        runtime.set_ai_provider("ollama")
    else:
        runtime.set_ai_provider("template")

    return {"location": location, "provider": runtime.get_ai_provider(),
            "model": model, "url": url}


async def local_structured(db, messages, schema, *, purpose, max_tokens=4096):
    """Compatibility API: always local, including legacy background consumers."""
    from .generation import generate
    result = await generate(db, messages, schema, purpose=purpose, max_tokens=max_tokens, force_local=True)
    return result


async def structured(db, messages, schema, *, purpose, max_tokens=4096, route=None, provenance=None):
    """Foreground planner; explicit task routing may authorize cloud inference."""
    from .generation import generate
    return await generate(db, messages, schema, purpose=purpose, max_tokens=max_tokens, route=route,
                          provenance=provenance)


def status(*, model: str = "", url: str = "", backend: str = "ollama") -> dict:
    """Is the local model actually there? Measured, not remembered.

    Asked over HTTP rather than by looking for a process: a running `ollama`
    that has not loaded the model answers this correctly and a process check
    does not.
    """
    from .providers import local_status
    try:
        return {**local_status(backend,url or "http://127.0.0.1:11434",model),"gpu":_gpu()}
    except Exception as exc:
        return {"reachable":False,"models":[],"has_model":False,
                "detail":type(exc).__name__,"gpu":_gpu()}


def _gpu() -> dict:
    """Whether there is a GPU for this to run on. Honest when there is not —
    a 7B model on CPU is a different product, and the user should be told."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {"available": False, "reason": "nvidia-smi is not installed"}
    if out.returncode != 0:
        return {"available": False, "reason": (out.stderr or "").strip()[:120]}
    line = (out.stdout or "").strip().splitlines()[:1]
    if not line:
        return {"available": False, "reason": "no GPU reported"}
    name, total, used = [p.strip() for p in line[0].split(",")][:3]
    return {"available": True, "name": name,
            "memory_total_mb": int(total), "memory_used_mb": int(used)}
