"""ARIES System Health — specification §13/08.

    from aries.health import run_pass, SPEC

Importing this package registers the health settings, the automation genome and
the `aries.health.check` task kind.
"""
from __future__ import annotations

from aries.health import settings as _settings  # noqa: F401  registers the thresholds
from aries.health.automation import AUTOMATION_ID, SPEC, TASK_KIND, EVALUATORS, execute, run_pass
from aries.health.baseline import AriesHealthSample, Baseline
from aries.health.findings import Finding, ProbeResult, Reading, Severity, worst
from aries.health.judge import judge

__all__ = ["run_pass", "execute", "SPEC", "TASK_KIND", "AUTOMATION_ID", "EVALUATORS",
           "Severity", "Reading", "Finding", "ProbeResult", "worst", "judge",
           "Baseline", "AriesHealthSample"]
