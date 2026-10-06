"""The Operator's switches — all of them off or safe by default.

The one that matters is `operator.enabled`. ARIES acting on a person's desktop
is the largest capability in this system, and the argument for shipping it off
is the same as for every automation (§11): a capability that arrives switched on
was never consented to.

`model_location` defaults to `local` because what someone asks their computer to
do is as private as what is in their mail, and this machine has a GPU. When it
is `local` the planner refuses rather than quietly falling back to a remote
provider — a privacy default that degrades under load is a decoration.
"""
from __future__ import annotations

from aries.settings.schema import SettingDef, define

S = "operator"

define(SettingDef("operator.enabled", bool, False, "Let ARIES act on this desktop",
                  "Whether ARIES may open applications, pages and screens on your behalf. "
                  "Off means it will still plan and say what it would do, and do nothing.",
                  S, control="toggle", user_only=True))

define(SettingDef("operator.confirm_model_plans", bool, True, "Confirm plans the model made",
                  "When ARIES understood a request with a language model rather than an "
                  "exact match, show the plan and wait. The interesting failure is not a "
                  "model refusing — it is a model answering plausibly.",
                  S, control="toggle", user_only=True))

define(SettingDef("operator.model_location", str, "local", "Where planning happens",
                  "'local' plans on this machine only, and refuses rather than sending the "
                  "request elsewhere. 'any' allows whichever provider is configured.",
                  S, control="choice", choices=["local", "any"], user_only=True))

define(SettingDef("operator.planner", str, "router+model", "How requests are understood",
                  "'router' uses only the exact-match table — offline, deterministic, and "
                  "limited to what ARIES already names. 'router+model' falls back to the "
                  "local model for anything the table does not recognise.",
                  S, control="choice", choices=["router", "router+model"]))

define(SettingDef("operator.max_actions_per_hour", int, 60, "How much ARIES may do in an hour",
                  "A cap on side-effecting actions, counted over a rolling hour. It exists "
                  "so that a loop — a bad plan, a retry storm, an experiment — cannot run "
                  "away with your desktop. Reaching it is not an error: ARIES says it was "
                  "held by the budget, and the run is not counted as a failure to plan.",
                  S, control="number", minimum=1, maximum=10000, unit="actions",
                  advanced=True))

define(SettingDef("operator.settle_seconds", float, 8.0, "How long to wait for proof",
                  "An application takes time to put a window on screen. ARIES keeps looking "
                  "for this long before deciding a goal was not met — the same window for "
                  "every request, so the measurement means something.",
                  S, control="number", minimum=0.0, maximum=60.0, unit="seconds",
                  advanced=True))
