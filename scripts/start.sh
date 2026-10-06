#!/usr/bin/env bash
# Run the ARIES API locally: the engine's routes plus the Control Centre.
#
# Binds to 127.0.0.1 on purpose. API_KEY defaults to empty, which means an open
# API — acceptable on loopback, never on a LAN. Set API_KEY (and mint per-person
# tokens) before changing the host.
#
# The shell deliberately does NOT parse .env. pydantic-settings reads it directly
# (`env_file=".env"`), and shell-exporting it is both redundant and fragile: the
# engine's SANDBOX_ALLOWED_COMMANDS value contains a space ("systemctl status"),
# which any unquoted `export $(...)` or `source <(grep ...)` splits into a
# command. Anything ARIES needs to default is written into .env once, below.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/vendor/agentic-core:$PWD/vendor:$PWD:${PYTHONPATH:-}"

if [ ! -f .env ]; then
  cp .env.example .env
  {
    echo ""
    echo "# --- ARIES defaults (added by scripts/start.sh on first run) ---"
    echo "DATABASE_URL=sqlite+aiosqlite:///$PWD/var/aries.db"
    echo "DATA_DIR=$PWD/var"
  } >> .env
  echo "created .env from .env.example"
fi

mkdir -p var
HOST="${HOST:-127.0.0.1}"; PORT="${1:-8000}"
echo "ARIES API → http://$HOST:$PORT/docs   (Control Centre under /api/aries)"
exec .venv/bin/uvicorn aries.api.app:app --host "$HOST" --port "$PORT"
