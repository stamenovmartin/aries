"""How long ARIES keeps things — as settings, so the user decides.

Every window here is a real number a person can change, not a constant compiled
into a cleaner. The defaults come from `policy.py`, which is also where the
reason for each one is written down, so a user who wants to know *why* news is
kept for 45 days has somewhere to read rather than a number to guess at.
"""
from __future__ import annotations

from aries.lifecycle.policy import POLICIES
from aries.settings.schema import SettingDef, define

S = "data"

define(SettingDef("data.cleaning_enabled", bool, False, "Delete old data automatically",
                  "Whether ARIES removes data that has passed its retention window. Off "
                  "means nothing is ever deleted — the database grows without limit, and "
                  "`aries data clean` is the only way anything goes.",
                  S, control="toggle", user_only=True))

define(SettingDef("data.dry_run_first", bool, True, "Show before deleting",
                  "Record what a cleaning pass WOULD remove, and act only on the next pass "
                  "if nothing changed. The first run of anything that deletes should be a "
                  "rehearsal.",
                  S, control="toggle", advanced=True))

define(SettingDef("data.clean_interval_hours", int, 24, "How often to check",
                  "How often ARIES looks for data past its window.",
                  S, control="number", minimum=1, maximum=720, unit="hours", advanced=True))

# One window per operational class, declared from the policy so the two cannot
# disagree: a policy with a setting name that has no setting is a policy nobody
# can change, and a setting with no policy is a number that does nothing.
_seen: set[str] = set()
for _policy in POLICIES:
    if not _policy.setting or _policy.setting in _seen:
        continue
    _seen.add(_policy.setting)
    define(SettingDef(
        _policy.setting, int, _policy.default_days,
        _policy.table.replace("aries_", "").replace("_", " ").capitalize(),
        f"{_policy.reason}  Minimum {_policy.minimum_days} days, because "
        f"{', '.join(_policy.dependants)} read it.",
        S, control="number", minimum=_policy.minimum_days, maximum=3650, unit="days"))
