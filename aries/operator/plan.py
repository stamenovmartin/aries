"""From what a person said to a plan ARIES can check afterwards.

THREE WAYS TO UNDERSTAND A REQUEST, IN ORDER OF HONESTY
-------------------------------------------------------
1. **The deterministic router.** `aries/shell/intents.py` already resolves
   "run a health check" and "open news" exactly, for free, offline, with no
   model and no variance. If it matches, that is the plan. Reaching for a model
   first would be slower, less reliable and unfalsifiable — and it would make
   the experiment dishonest, since the baseline it is measured against *is* this
   router.
2. **The local model.** Everything the router does not know goes to a model
   running on this machine, asked to choose from a **fixed vocabulary of goals**
   — never to write a command. It cannot invent a step, because a step ARIES
   cannot verify is a step ARIES will not take.
3. **Refusal.** If neither produces a plan, ARIES says what it cannot do and
   names what it can. It never substitutes something plausible, which is the
   same rule the command bar has had since M11 and the one that makes the
   other two answers worth anything.

WHY THE MODEL PICKS GOALS RATHER THAN COMMANDS
----------------------------------------------
A model that emits shell is a model whose output cannot be checked before it
runs, cannot be checked after it runs, and cannot be refused by a permission
system that does not know what the command will do. A model that emits
`{"goal": "open_url", "url": "..."}` produces something with a schema, a
permission, an audit line and — crucially — a verifier that decides whether it
worked, independently of anything the model claims.

That constraint is the design. It costs the Operator the ability to do
arbitrary things, and buys the ability to be honest about the things it does.

WHY LOCAL BY DEFAULT
--------------------
What a person asks their computer to do is as private as what is in their mail.
`operator.model_location` defaults to `local`, and when it is `local` the
planner refuses to run at all against a non-local provider rather than quietly
sending the request elsewhere. A privacy default that degrades silently under
load is not a default, it is a decoration.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from aries.operator import goals

logger = logging.getLogger(__name__)

# The model gets one attempt plus one corrective retry showing it its own error.
# More than that is a model that is not going to get there, spending the user's
# GPU on it.
MAX_MODEL_ATTEMPTS = 2

# A plan longer than this is not a desktop request, it is a script. v0.1 refuses
# rather than executing something nobody scoped.
MAX_STEPS = 5

LOCAL_PROVIDERS = ("ollama",)


@dataclass(frozen=True)
class Step:
    """One thing to do, and the goal it is supposed to make true.

    The tool and the goal are separate fields on purpose. They are usually the
    obvious pair, and when they are not — a URL opened to reach a page whose
    goal is really "a browser is on that site" — keeping them apart is what
    stops the verification from becoming a restatement of the action.
    """

    goal: str                     # a kind from goals.GOALS
    params: dict
    tool: str
    payload: dict
    why: str = ""

    def as_dict(self) -> dict:
        return {"goal": self.goal, "params": self.params, "tool": self.tool,
                "payload": self.payload, "why": self.why}


@dataclass
class Plan:
    """What ARIES intends to do, or why it will not."""

    request: str
    steps: list[Step] = field(default_factory=list)
    source: str = ""              # router | model | refused
    refusal: str = ""             # the sentence a person reads when there is no plan
    alternatives: list[dict] = field(default_factory=list)
    model: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.steps)

    def as_dict(self) -> dict:
        return {"request": self.request, "steps": [s.as_dict() for s in self.steps],
                "source": self.source, "refusal": self.refusal,
                "alternatives": self.alternatives, "model": self.model}


# ── 1. the deterministic router ─────────────────────────────────────────────

def _from_router(request: str) -> Plan | None:
    """A plan from the existing intent table, or None.

    Only the actions that map onto a goal ARIES can verify are taken here. The
    router knows other things — filling the command bar with a draft, for
    instance — and those are not Operator work: nothing about them is true or
    false afterwards.
    """
    from aries.workspace.capabilities import desktop_plan
    direct = desktop_plan(request)
    if direct is not None:
        return direct
    from aries.shell import intents

    resolved = intents.resolve(request)
    # ONLY an exact pattern match. `resolve()` also returns near matches ranked
    # by keyword, and those are suggestions for a person to pick from, not a
    # decision — taking the top one turned "send an email to my boss" into
    # "open the Connections screen", which is precisely the plausible
    # substitution this whole milestone exists to stop. When the router is not
    # certain, the model gets its turn, and when neither is certain ARIES says
    # so.
    if not resolved.get("exact"):
        return None
    results = resolved.get("results") or []
    if not results:
        return None
    top = results[0]
    action = top.get("action") or {}
    kind = action.get("kind")

    if kind == "navigate" and action.get("section"):
        section = action["section"]
        return Plan(request=request, source="router", steps=[Step(
            goal="open_section", params={"section": section},
            tool="aries.open_section", payload={"section": section},
            why=top.get("title", ""))])

    if kind == "run_automation" and action.get("automation_id"):
        automation_id = action["automation_id"]
        return Plan(request=request, source="router", steps=[Step(
            goal="run_automation", params={"automation_id": automation_id},
            tool="aries.run_automation", payload={"automation_id": automation_id},
            why=top.get("title", ""))])

    return None


# ── 2. the local model ──────────────────────────────────────────────────────

def _vocabulary() -> str:
    """The goal list, written for a model. Generated, so it cannot drift from
    the goals that actually exist and have verifiers."""
    lines = []
    for goal in goals.GOALS:
        params = ", ".join(f'"{p}": "…"' for p in goal.params)
        lines.append(f'  {{"goal": "{goal.kind}", {params}}}')
    return "\n".join(lines)


# The Control Centre's sections, named once. The prompt lists them and the
# validator enforces them from the SAME list, so a section that exists in the
# instructions and not in the product is impossible rather than merely unlikely.
AUTOMATIONS: tuple[str, ...] = (
    "aries.health", "aries.news", "aries.brief", "aries.learning", "aries.data")

SECTIONS: tuple[str, ...] = (
    "monitor", "files", "applications",
    "home", "dashboard", "operator", "brief", "news", "interests", "learning",
    "automations", "system", "connections", "data", "analytics", "settings")

SYSTEM_PROMPT = """You translate a person's request into a plan for ARIES, a Linux desktop assistant.

Answer with JSON only, in exactly this shape:
{"steps": [ ... ], "refusal": ""}

Each step must be one of these, and NOTHING else:
%(vocabulary)s

Rules:
- Use the fewest steps that achieve the request. Most requests are one step.
- "url" must be a full http:// or https:// address.
- "app" is an application name as installed, e.g. "firefox", "nautilus".
- "section" is one of: %(sections)s.
- "automation_id" is one of: %(automations)s.
- If the request cannot be expressed with the steps above, answer
  {"steps": [], "refusal": "<one sentence saying what you cannot do>"}.
- REFUSING IS THE RIGHT ANSWER far more often than substituting. If the request
  asks to delete, format, install, uninstall, kill, configure, write, send or
  change anything, refuse: none of those are steps above. Do not open a screen
  that is merely ON THE SUBJECT of the request — opening the System screen is
  not a way of reformatting a disk, and answering that way is worse than
  refusing, because it looks like the request was carried out.
- A step must be something the person would recognise as what they asked for.
- Never invent a step type. Never answer with shell commands or prose.
"""


def _provider_is_local() -> tuple[bool, str]:
    from agentic_core.config import runtime
    provider = runtime.get_ai_provider()
    return provider in LOCAL_PROVIDERS, provider


async def _from_model(request: str, *, require_local: bool) -> Plan:
    from agentic_core.config.settings import settings
    from agentic_core.llm import providers
    from agentic_core.llm.structured import extract_json

    is_local, provider = _provider_is_local()
    if require_local and not is_local:
        return Plan(request=request, source="refused",
                    refusal=(f"ARIES is set to plan only on this machine "
                             f"(operator.model_location = local) and the configured model "
                             f"provider is '{provider}'. Nothing was sent anywhere."))
    if not providers.available():
        return Plan(request=request, source="refused",
                    refusal=("no model is reachable, so ARIES cannot interpret a request "
                             "the deterministic router does not already know"))

    system = SYSTEM_PROMPT % {"vocabulary": _vocabulary(),
                              "sections": ", ".join(SECTIONS),
                              "automations": ", ".join(AUTOMATIONS)}
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": request}]
    model = settings.ollama_model if is_local else (provider or "")

    problems = ""
    for attempt in range(MAX_MODEL_ATTEMPTS):
        if problems:
            messages = messages + [
                {"role": "user",
                 "content": f"That was not usable: {problems}. Answer with JSON only, "
                            f"using only the step types listed."}]
        try:
            raw = await providers.chat(messages, purpose="operator.plan")
        except Exception as exc:                      # noqa: BLE001
            logger.warning("operator planner: provider failed: %s", exc)
            return Plan(request=request, source="refused", model=model,
                        refusal=f"the model could not be reached: {type(exc).__name__}")

        obj = extract_json(raw)
        if obj is None:
            problems = "the reply was not JSON"
            continue

        if obj.get("refusal") and not obj.get("steps"):
            return Plan(request=request, source="model", model=model,
                        refusal=str(obj["refusal"])[:300])

        steps, problems = _steps_from(obj)
        if steps:
            return Plan(request=request, steps=steps, source="model", model=model)

    return Plan(request=request, source="refused", model=model,
                refusal=f"ARIES could not turn that into steps it knows how to check "
                        f"({problems})")


def _steps_from(obj: dict) -> tuple[list[Step], str]:
    """Validate the model's steps against the goal vocabulary.

    Every rejection is specific, because the rejection is fed back to the model
    as its one corrective retry, and "invalid" teaches it nothing.
    """
    raw_steps = obj.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return [], "there were no steps"
    if len(raw_steps) > MAX_STEPS:
        return [], f"{len(raw_steps)} steps is more than the {MAX_STEPS} ARIES will run at once"

    out: list[Step] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            return [], "a step was not an object"
        kind = raw.get("goal")
        goal = goals.get(str(kind))
        if goal is None:
            return [], (f"'{kind}' is not a step ARIES has; the choices are "
                        f"{', '.join(g.kind for g in goals.GOALS)}")
        params = {p: raw.get(p) for p in goal.params}
        missing = [p for p, v in params.items() if not v]
        if missing:
            return [], f"the '{kind}' step is missing {', '.join(missing)}"

        # An enum the prompt states is an enum the validator enforces. The model
        # answered "what is the weather tomorrow" with `open_section: weather` —
        # a step shaped exactly like a real one, naming a screen that does not
        # exist. Asking politely in a prompt is not a constraint.
        if kind == "open_section" and params["section"] not in SECTIONS:
            return [], (f"'{params['section']}' is not a screen ARIES has; "
                        f"the screens are {', '.join(SECTIONS)}")
        if kind == "run_automation" and params["automation_id"] not in AUTOMATIONS:
            return [], (f"'{params['automation_id']}' is not an automation ARIES has; "
                        f"they are {', '.join(AUTOMATIONS)}")
        step = _step_for(goal.kind, params)
        if step is None:
            return [], f"ARIES has no tool for a '{kind}' step"
        out.append(step)
    return out, ""


def _step_for(kind: str, params: dict) -> Step | None:
    """The tool that attempts a goal. One place, so the planner and the executor
    cannot disagree about what a goal means."""
    if kind == "open_url":
        return Step(kind, params, "desktop.open_url", {"url": params["url"]})
    if kind == "open_app":
        return Step(kind, params, "desktop.open_app", {"app": params["app"]})
    if kind == "open_section":
        return Step(kind, params, "aries.open_section", {"section": params["section"]})
    if kind == "run_automation":
        return Step(kind, params, "aries.run_automation",
                    {"automation_id": params["automation_id"]})
    return None


# ── the entry point ─────────────────────────────────────────────────────────

async def make(request: str, *, require_local: bool = True,
               allow_model: bool = True) -> Plan:
    """Understand a request. Router first, model second, refusal third."""
    request = (request or "").strip()
    if not request:
        return Plan(request="", source="refused", refusal="nothing was asked")

    routed = _from_router(request)
    if routed is not None:
        return routed

    if not allow_model:
        return Plan(request=request, source="refused",
                    refusal=("the deterministic router does not recognise that, and the "
                             "model planner is switched off (operator.planner = router)"),
                    alternatives=_alternatives(request))

    plan = await _from_model(request, require_local=require_local)
    if not plan.ok and not plan.alternatives:
        plan.alternatives = _alternatives(request)
    return plan


def _alternatives(request: str) -> list[dict]:
    """What ARIES can actually do, when it could not do this. Never a guess at
    what was meant — the nearest real capabilities, as the command bar does."""
    from aries.shell import intents
    resolved = intents.resolve(request)
    return [{"title": r.get("title"), "example": r.get("example")}
            for r in (resolved.get("results") or [])[:4]]
