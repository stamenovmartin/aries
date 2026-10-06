"""Settings the brief adds. `briefing.*` was defined in Entry 002; this is the
one knob the pipeline needed that was not anticipated then."""
from __future__ import annotations

from aries.settings.schema import SettingDef, define

define(SettingDef("brief.window_hours", float, 24.0, "Look back over",
                  "How far back a brief reaches for news and changes. Should normally match how "
                  "often the brief is produced.",
                  "briefing", control="number", minimum=1.0, maximum=336.0, unit="hours"))
