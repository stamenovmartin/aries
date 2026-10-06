"""ARIES Background Mode — keep working while the display is off."""
from __future__ import annotations

from aries.power import governor, inhibit, state, workload
from aries.power import settings as _settings  # noqa: F401  registers the settings
from aries.power.service import reconcile, snapshot

__all__ = ["reconcile", "snapshot", "inhibit", "state", "governor", "workload"]
