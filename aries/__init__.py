"""ARIES — Artificial Responsive Intelligent Execution System.

An AI-native, adaptive, agentic computing environment built on Linux and on the
`agentic_core` orchestration engine.

Layering, from the bottom:

    Linux / systemd                     the operating system
    agentic_core                        orchestration: tasks, lifecycle, agents,
                                        tools, workflows, evaluators, memory,
                                        scheduler, security, observability, API
    aries                               the ARIES environment: settings, sources,
                                        interests, notifications, automations,
                                        agents and the shell

Nothing in `agentic_core` knows about ARIES, exactly as nothing in it knows
about the marketing system it was extracted from. ARIES is an application on the
engine, and that boundary is what lets the engine's guarantees keep holding.

Importing this package registers ARIES's database tables and settings schema, so
`agentic_core.database.migrate.run_migrations()` creates them.
"""
from __future__ import annotations

__version__ = "0.1.0"

# Import order is registration order, and it is load-bearing: `settings` must be
# importable on its own (nothing in it may reach into a feature package), and each
# feature package registers its own settings, tables and task kinds as it is
# imported here.
from aries import settings as settings          # noqa: F401  settings service + table
from aries import notify as notify              # noqa: F401  notification policy + table
from aries import automations as automations    # noqa: F401  the automation registry
from aries import sources as sources            # noqa: F401  Sources Registry: types, table, settings
from aries import interests as interests        # noqa: F401  Interest Profile: table, settings
from aries import health as health              # noqa: F401  System Health: settings, genome, task kind
from aries import news as news                  # noqa: F401  News Radar: settings, table, workflow, genome
from aries import learning as learning          # noqa: F401  Learning loop: settings, genome
from aries import brief as brief                # noqa: F401  Morning Brief: settings, table, workflow, genome
from aries import integrations as integrations  # noqa: F401  Connection Hub (§23)
from aries import power as power                # noqa: F401  Background Mode: inhibitor, resource policy, table
from aries import connect as connect          # noqa: F401  the integrations boundary (§21/§23)
from aries import intelligence as intelligence  # noqa: F401  which model, and where it runs
from aries import operator as operator      # noqa: F401  plan, act, verify (§32)
from aries import lifecycle as lifecycle      # noqa: F401  retention policy, working set, cleaner
from aries import workspace as workspace  # goal dashboards and explicit context
from aries import shell as shell                # noqa: F401  ARIES Shell: intents, search, status, settings, tokens
