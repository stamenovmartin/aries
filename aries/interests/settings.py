"""Settings that govern the interest profile as a whole. Per-topic
configuration — weight, synonyms, notification level — lives on the topic."""
from __future__ import annotations

from aries.settings.schema import SettingDef, define

S = "interests"

define(SettingDef("interests.default_weight", float, 0.6, "Default topic weight",
                  "How much a topic counts when neither the user nor ARIES has set a weight "
                  "for it, from 0 to 1.",
                  S, control="slider", minimum=0.0, maximum=1.0))
define(SettingDef("interests.max_topics", int, 300, "Maximum topics",
                  "How many topics the profile may hold.",
                  S, control="number", minimum=1, maximum=5000, unit="topics", advanced=True))
define(SettingDef("interests.learning_enabled", bool, True, "Learn what interests me",
                  "Whether ARIES may infer topic weights from what the user opens and ignores. "
                  "Inferred weights never override one the user set.",
                  S, control="toggle"))
