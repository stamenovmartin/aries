"""Re-export the engine's test harness so ARIES tests use one implementation."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "vendor", "agentic-core", "tests"))

from _harness import bootstrap, check, run_module  # noqa: E402,F401
