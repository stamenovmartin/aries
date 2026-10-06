"""ARIES Operator — natural language that produces verified action.

    desktop.py   what is actually on this machine right now
    goals.py     what "done" means, and how strong the evidence for it can be
    tools.py     how ARIES acts — four gated tools, and nothing else
    plan.py      request → steps, router first, local model second, refusal third
    service.py   the loop, and the two numbers it never merges
    settings.py  the switches, off by default

The claim this package has to earn is not "ARIES can open YouTube". It is
"ARIES knows whether it opened YouTube" — and says so when it does not.
"""
from __future__ import annotations

from aries.operator import desktop, goals, plan, service
from aries.operator import settings as _settings   # noqa: F401  registers settings
from aries.operator import tools as _tools         # noqa: F401  registers the tools

__all__ = ["desktop", "goals", "plan", "service"]
