"""Provider dispatch. Lifted from backend/app/services/ai/__init__.py.

Four providers behind one `chat(messages)`:
  cli      an installed agentic CLI in headless mode (`the reviewing agent -p`, `codex exec`),
           run in an empty scratch cwd, its own process group, a hard timeout,
           a bounded semaphore, and a fallback to the OTHER binary if present.
  ollama   local HTTP.
  openai   any OpenAI-compatible chat endpoint (OpenAI, Groq, vLLM, LM Studio…).
  template a deterministic offline responder so the pipeline never hard-fails.

Rules preserved: retry only what a retry can fix (classify); strict mode
(`require_ai`) raises instead of falling back to the template; telemetry records
every call; the system prompt gets the operator's instructions + the shared
context digest appended.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time

import httpx

from agentic_core.config import runtime
from agentic_core.config.settings import settings
from agentic_core.llm import telemetry
from agentic_core.orchestrator.errors import classify

logger = logging.getLogger(__name__)


class AIGenerationError(RuntimeError):
    """Strict mode: the provider failed and the template fallback is refused."""


def strict() -> bool:
    return runtime.get_require_ai() and runtime.get_ai_provider() != "template"


def _cli_path(bin_name: str | None = None) -> str | None:
    return shutil.which(bin_name or settings.cli_agent_bin)


def _alt_cli_path() -> str | None:
    primary = os.path.basename(settings.cli_agent_bin).lower()
    return shutil.which("the reviewing agent" if "codex" in primary else "codex")


def available() -> bool:
    p = runtime.get_ai_provider()
    if p == "template":
        return False
    if p == "ollama":
        return True
    if p == "cli":
        return _cli_path() is not None
    if p == "openai":
        return bool(settings.openai_api_key or "localhost" in settings.openai_base_url)
    return False


def describe() -> dict:
    p = runtime.get_ai_provider()
    return {"provider": p, "available": available(), "strict": strict(),
            "model": {"cli": settings.cli_agent_model, "ollama": settings.ollama_model,
                      "openai": settings.openai_model, "template": None}.get(p),
            "temperature": settings.llm_temperature, "max_tokens": settings.llm_max_tokens,
            "cli_binary": _cli_path() if p == "cli" else None}


def system_prompt(base: str) -> str:
    """The agent's prompt + operator instructions + the shared context digest."""
    prompt = runtime.get_system_prompt_override() or base
    op = runtime.get_operator_prompt()
    if op.strip():
        prompt += "\n\n=== OPERATOR INSTRUCTIONS (mandatory) ===\n" + op.strip()
    try:
        from agentic_core.memory.context_layer import digest
        ctx = digest()
        if ctx:
            prompt += "\n\n=== SHARED CONTEXT (written by other agents, read before acting) ===\n" + ctx
    except Exception:
        logger.exception("Context digest unavailable")
    return prompt


# ── the one entry point ──────────────────────────────────────────────────────

async def chat(messages: list[dict], *, purpose: str = "chat", timeout: float | None = None,
               images: list[str] | None = None, retries: int = 3) -> str:
    """Provider-agnostic completion with classified retries. Raises on final
    failure — callers that want a fallback wrap it (see `complete`)."""
    provider = runtime.get_ai_provider()
    last_err = None
    for attempt in range(1, retries + 1):
        t0 = time.monotonic(); ok = False; err_cls = None
        try:
            if provider == "ollama":
                out = await _ollama_chat(messages, timeout=timeout)
            elif provider == "cli":
                out = await _cli_chat(messages, timeout=timeout, images=images)
            elif provider == "openai":
                out = await _openai_chat(messages, timeout=timeout)
            else:
                out = _template_chat(messages)
            ok = True
            return out
        except asyncio.CancelledError:
            raise
        except Exception as e:
            last_err = e
            verdict = classify(str(e)); err_cls = verdict.cls.value
            logger.warning("LLM call failed (%s) attempt %d/%d [%s]: %s", provider, attempt, retries, err_cls, e)
            if not verdict.retryable:
                break
        finally:
            telemetry.record(provider=provider, purpose=purpose, ms=int((time.monotonic() - t0) * 1000),
                             ok=ok, error_class=err_cls, attempt=attempt)
    raise RuntimeError(f"LLM provider '{provider}' failed: {last_err}")


async def complete(system: str, user: str, *, purpose: str = "complete", timeout: float | None = None,
                   images: list[str] | None = None) -> str | None:
    """Single-shot completion that returns None instead of raising when no
    provider is available or the call fails — callers supply a deterministic
    fallback so the pipeline never hard-fails. In strict mode it raises."""
    if not available():
        if strict():
            raise AIGenerationError("AI provider not available")
        return None
    try:
        text = await chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                          purpose=purpose, timeout=timeout, images=images)
        return (text or "").strip() or None
    except Exception as e:
        if strict():
            raise AIGenerationError(f"provider failed: {e}") from e
        logger.warning("complete() failed on %s; caller will fall back", runtime.get_ai_provider(), exc_info=True)
        return None


# ── providers ────────────────────────────────────────────────────────────────

async def _ollama_chat(messages, *, timeout=None) -> str:
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {"model": settings.ollama_model, "messages": messages, "stream": False,
               "options": {"temperature": settings.llm_temperature, "num_predict": settings.llm_max_tokens}}
    async with httpx.AsyncClient(timeout=timeout or settings.ollama_timeout) as client:
        resp = await client.post(url, json=payload); resp.raise_for_status(); data = resp.json()
    content = (data.get("message", {}) or {}).get("content", "").strip()
    if not content:
        raise RuntimeError("Ollama returned empty content")
    return content


async def _openai_chat(messages, *, timeout=None) -> str:
    url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.openai_api_key:
        headers["Authorization"] = f"Bearer {settings.openai_api_key}"
    payload = {"model": settings.openai_model, "messages": messages,
               "temperature": settings.llm_temperature, "max_tokens": settings.llm_max_tokens}
    async with httpx.AsyncClient(timeout=timeout or 90.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
    usage = (data.get("usage") or {}).get("total_tokens")
    if usage is not None:
        telemetry.record(provider="openai", purpose="usage", ms=0, ok=True, tokens=int(usage))
    content = (data["choices"][0]["message"]["content"] or "").strip()
    if not content:
        raise RuntimeError("provider returned empty content")
    return content


_semaphores: dict = {}


def _cli_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _semaphores.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(max(1, settings.cli_agent_max_concurrency)); _semaphores[loop] = sem
    return sem


def _kill_process_tree(proc) -> None:
    import signal
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def _cli_chat(messages, *, timeout=None, images=None) -> str:
    sys_msg = next((m["content"] for m in messages if m.get("role") == "system"), "")
    prompt = "\n\n".join(m["content"] for m in messages if isinstance(m.get("content"), str) and m.get("role") != "system")
    try:
        return await _cli_run(sys_msg, prompt, images=images, timeout=timeout)
    except asyncio.CancelledError:
        raise
    except Exception as primary_err:
        alt = _alt_cli_path()
        if not alt:
            raise
        logger.warning("CLI agent %s failed (%s) — retrying with %s", settings.cli_agent_bin, str(primary_err)[:160], alt)
        return await _cli_run(sys_msg, prompt, images=images, timeout=timeout, bin_path=alt)


async def _cli_run(system_prompt_text: str, user_prompt: str, *, images=None, timeout=None, bin_path=None) -> str:
    bin_path = bin_path or _cli_path()
    if not bin_path:
        raise RuntimeError(f"CLI agent binary '{settings.cli_agent_bin}' not found on PATH")
    is_codex = "codex" in os.path.basename(bin_path).lower()
    parts = [system_prompt_text, "", user_prompt]
    if images and not is_codex:
        parts += ["", "Read these image files and take them into account:\n" + "\n".join(f"- {p}" for p in images)]
    parts += ["", "Return ONLY the final answer — no explanation, no quotes, no preamble."]
    full_prompt = "\n".join(parts)
    last_msg_file = None
    if is_codex:
        fd, last_msg_file = tempfile.mkstemp(suffix=".txt", prefix="codex_out_"); os.close(fd)
        argv = [bin_path, "exec", "--skip-git-repo-check", "--color", "never", "--sandbox", "read-only", "-o", last_msg_file]
        if images:
            argv += ["-i", *images, "--"]
        argv.append(full_prompt)
    else:
        argv = [bin_path, "-p", full_prompt, "--model", settings.cli_agent_model]
        if images:
            argv += ["--allowedTools", "Read"]
    agent_cwd = os.path.join(tempfile.gettempdir(), "agentic-agent-cwd")
    os.makedirs(agent_cwd, exist_ok=True)
    sem = _cli_semaphore()
    await sem.acquire()
    try:
        proc = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, cwd=agent_cwd,
                                                    start_new_session=True)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout or settings.cli_agent_timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            _kill_process_tree(proc); await proc.wait()
            if isinstance(e, asyncio.CancelledError):
                raise
            raise RuntimeError(f"CLI agent timed out after {timeout or settings.cli_agent_timeout}s")
        if proc.returncode != 0:
            raise RuntimeError(f"CLI agent exited {proc.returncode}: {(stderr or b'').decode(errors='replace').strip()[:500]}")
        content = ""
        if last_msg_file and os.path.exists(last_msg_file):
            with open(last_msg_file, encoding="utf-8", errors="replace") as f:
                content = f.read().strip()
        if not content:
            content = (stdout or b"").decode(errors="replace").strip()
    finally:
        sem.release()
        if last_msg_file and os.path.exists(last_msg_file):
            try:
                os.unlink(last_msg_file)
            except OSError:
                pass
    if len(content) >= 2 and content[0] == content[-1] and content[0] in "\"'«":
        content = content[1:-1].strip()
    if not content:
        raise RuntimeError("CLI agent returned empty content")
    return content


def _template_chat(messages) -> str:
    """Deterministic offline responder. If the user prompt asks for JSON with a
    recognisable shape it echoes a minimal valid object; otherwise a short
    acknowledgement. Never fails, never touches the network."""
    user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    if "JSON" in user or "json" in user:
        return '{"template": true, "note": "offline template provider — no model was called"}'
    return "[template] " + (user.strip().splitlines() or ["ok"])[0][:200]
