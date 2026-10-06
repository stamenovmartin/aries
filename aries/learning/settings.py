"""Settings for the medium learning loop (§16)."""
from __future__ import annotations

from aries.settings.schema import SettingDef, define

S = "learning"

define(SettingDef("learning.enabled", bool, False, "Learn from what I read",
                  "Whether ARIES adjusts topic weights and thresholds from what the user opens "
                  "and dismisses. Learned values never override one the user has set.",
                  S, control="toggle"))
# user_only: whether inferences are APPLIED or only proposed is a control decision,
# never one the system may make about itself.
define(SettingDef("learning.apply_changes", bool, True, "Apply what it learns",
                  "When off, ARIES works out what it would change and records the proposals "
                  "without acting on them — useful for watching it before trusting it.",
                  S, control="toggle", user_only=True))
define(SettingDef("learning.interval_hours", int, 24, "How often to learn",
                  "How often the learning pass runs.",
                  S, control="number", minimum=1, maximum=720, unit="hours"))
define(SettingDef("learning.window_days", int, 30, "Evidence window",
                  "How far back the loop looks at what was delivered.",
                  S, control="number", minimum=1, maximum=365, unit="days"))
define(SettingDef("learning.min_observations", int, 10, "Minimum evidence",
                  "How many delivered items about a topic before ARIES will change its weight. "
                  "Below this, one click looks like a trend.",
                  S, control="number", minimum=3, maximum=1000, unit="items"))
define(SettingDef("learning.engaged_threshold", float, 0.4, "Engaging above",
                  "Engagement rate above which a topic is treated as worth more, judged at the "
                  "pessimistic end of the confidence interval.",
                  S, control="slider", minimum=0.05, maximum=1.0, advanced=True))
define(SettingDef("learning.ignored_threshold", float, 0.1, "Ignored below",
                  "Engagement rate below which a topic is treated as noise, judged at the "
                  "optimistic end of the confidence interval.",
                  S, control="slider", minimum=0.0, maximum=0.9, advanced=True))
define(SettingDef("learning.noisy_threshold", float, 0.3, "Too much noise above",
                  "Share of delivered items dismissed before ARIES offers to raise the relevance "
                  "bar. It only ever offers to be quieter, never louder.",
                  S, control="slider", minimum=0.05, maximum=1.0, advanced=True))
define(SettingDef("learning.max_step", float, 0.15, "Largest single change",
                  "How far one learning pass may move any weight. A bug in the evidence should "
                  "cost a nudge, not a configuration.",
                  S, control="slider", minimum=0.01, maximum=0.5, advanced=True))

define(SettingDef("learning.max_reversals", int, 3, "Give up after changing my mind",
                  "How many times ARIES may reverse a previous adjustment to the same thing "
                  "before it stops adjusting it and leaves the decision to the user. 0 disables "
                  "freezing, and the damping alone slows an oscillation.",
                  S, control="number", minimum=0, maximum=20, unit="reversals"))
define(SettingDef("learning.damping", float, 0.5, "Damping per reversal",
                  "How much smaller each change becomes after ARIES turns around on the same "
                  "target. 0.5 halves the allowed step per reversal, so an oscillation decays "
                  "instead of continuing at full amplitude.",
                  S, control="slider", minimum=0.1, maximum=1.0, advanced=True))

# ── reversal (policy reversal-v1) ───────────────────────────────────────────
define(SettingDef("learning.reversal_hysteresis", float, 0.4, "Harder to reverse than to keep",
                  "How much stricter the evidence must be to REVERSE an established preference "
                  "than to continue it, from 0 to 1. 0 makes reversing as easy as forming a "
                  "preference, which is how learned values start oscillating.",
                  S, control="slider", minimum=0.0, maximum=0.9))
define(SettingDef("learning.reversal_min_observations_factor", float, 2.0,
                  "Evidence needed to reverse",
                  "Multiple of the normal minimum observations required before an established "
                  "preference may be reversed.",
                  S, control="number", minimum=1.0, maximum=10.0, unit="×", advanced=True))
define(SettingDef("learning.reversal_confirmations", int, 2, "Passes before reversing",
                  "How many consecutive learning passes must reach the same conclusion before a "
                  "reversal is applied. This is what separates a change of mind from a bad "
                  "fortnight.",
                  S, control="number", minimum=1, maximum=10, unit="passes"))
define(SettingDef("learning.established_margin", float, 0.1, "What counts as established",
                  "How far a learned value must sit from neutral before reversing it is treated "
                  "as reversing something, rather than as ordinary adjustment.",
                  S, control="slider", minimum=0.01, maximum=0.5, advanced=True))
define(SettingDef("learning.fatigue_step", float, 0.05, "Fading interest step",
                  "How much a weight decays per pass when interest is declining steadily rather "
                  "than contradicted outright.",
                  S, control="slider", minimum=0.01, maximum=0.3, advanced=True))
