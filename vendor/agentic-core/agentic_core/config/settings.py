"""Process-level settings, read from the environment (and a .env file).

Lifted from backend/app/core/config.py, stripped of every marketing key. Only
the knobs the engine itself consumes remain; an application built on the
engine adds its own Settings subclass (see examples/linux_agent/settings.py).

Rules kept from the original:
  * no secret has a working default — every credential defaults to "";
  * the safety switches (`dry_run`, `live_tools`) default to SAFE;
  * `app_env` is separate from the connection string (see security/environments).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── storage ──────────────────────────────────────────────────────────────
    # SQLite by default so the engine runs with zero infrastructure; Postgres
    # in docker-compose. The original defaulted to a Postgres DSN with a
    # baked-in password — that default is deliberately gone.
    database_url: str = "sqlite+aiosqlite:///./agentic_core.db"
    redis_url: str = ""

    # ── app ──────────────────────────────────────────────────────────────────
    app_name: str = "agentic-core"
    fastapi_env: str = "development"      # development | production
    secret_key: str = ""                  # required in production
    # Shared API key. Empty = open API (only acceptable on a trusted LAN).
    api_key: str = ""
    # Master key for credentials-at-rest (security/crypto.py). Empty = the
    # encrypted store refuses to save or read secrets.
    credentials_key: str = ""
    cors_origins: str = "http://localhost:3000"
    # Where runtime overrides, worker cursors and the context layer live.
    data_dir: str = "./data"

    # ── LLM provider ─────────────────────────────────────────────────────────
    # "cli" (the reviewing agent / codex binaries, headless), "ollama", "openai" (any
    # OpenAI-compatible HTTP endpoint), or "template" (deterministic, offline).
    ai_provider: str = "template"
    cli_agent_bin: str = "the reviewing agent"
    cli_agent_model: str = "claude-haiku-4-5"
    cli_agent_timeout: float = 60.0
    cli_agent_max_concurrency: int = 2
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout: float = 120.0
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 800
    # Strict mode: refuse the template fallback for generation; raise instead.
    require_ai: bool = False

    # ── approvals / notifications ────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_approver_chat_id: str = ""
    telegram_poll_enabled: bool = True

    # ── execution safety ─────────────────────────────────────────────────────
    # dry_run=true: side-effecting tools are simulated, never executed.
    dry_run: bool = True
    # Comma-separated tool names cleared to run for real. Empty = nothing
    # side-effecting runs even with dry_run=false. Credentials are not consent;
    # this list is.
    live_tools: str = ""
    # Sandbox for shell-type tools: timeout and allowlist (see security/sandbox).
    sandbox_timeout_s: float = 30.0
    sandbox_allowed_commands: str = "ls,cat,stat,df,du,free,uptime,systemctl status,journalctl,ps,ss,ip,hostname,uname,id,whoami,which,echo,head,tail,grep,wc,find"
    max_actions_per_hour: int = 30

    # ── scheduler / workers ──────────────────────────────────────────────────
    scheduler_enabled: bool = True
    scheduler_poll_seconds: int = 30
    scheduler_max_attempts: int = 3
    scheduler_retry_backoff_minutes: int = 5
    quiet_hours_start: int = 0
    quiet_hours_end: int = 0            # start == end disables quiet hours
    scheduler_timezone: str = "UTC"
    learning_nightly_enabled: bool = True
    learning_run_hour: int = 3

    # ── memory ───────────────────────────────────────────────────────────────
    memory_embeddings: str = "lexical"    # lexical | ollama

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)


settings = Settings()
