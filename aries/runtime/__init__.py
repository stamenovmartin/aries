"""ARIES as part of the operating environment, not an application (ADR-0005)."""
from __future__ import annotations

from aries.runtime import systemd
from aries.runtime.status import (
    DEGRADED, MEANING, RUNNING, STARTING, STOPPED, Component, Status, describe,
)

__all__ = ["describe", "Status", "Component", "systemd",
           "RUNNING", "DEGRADED", "STOPPED", "STARTING", "MEANING"]
