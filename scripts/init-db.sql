-- Runs once on first Postgres boot. The application creates its own tables at
-- startup (agentic_core.database.migrate); this only guarantees the database.
SELECT 'CREATE DATABASE agentic_core OWNER agentic'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'agentic_core')\gexec
