"""Deterministic routing rules — routing must work without a model.
Lifted from backend/app/orchestration/router.py (_RULES + _HUMAN_WORDS).

A rule table maps keyword groups to an agent; `HUMAN_WORDS` are verbs that mean
the task spends, deletes or reaches the outside world — such a task always
needs a human whatever agent gets it."""
from __future__ import annotations

# (keywords, agent, confidence). First match wins; order = specificity.
RULES: list[tuple[tuple[str, ...], str, float]] = [
    (("research", "find out", "investigate", "inspect", "diagnose", "check", "status", "why"), "researcher", 0.8),
    (("plan", "strategy", "approach", "prioritise", "prioritize", "how should"), "planner", 0.8),
    (("review", "verify", "validate", "evaluate", "audit"), "reviewer", 0.8),
    (("fix", "repair", "regenerate", "rewrite", "correct"), "repairer", 0.75),
    (("learn", "distil", "distill", "rules from"), "distiller", 0.9),
    (("write", "generate", "produce", "create", "build", "make", "run", "execute", "apply", "install", "restart"), "executor", 0.7),
]

# Verbs that mean the task spends, deletes, or leaves the machine → human.
HUMAN_WORDS = ("delete", "remove", "publish", "send", "deploy", "restart", "reboot", "shutdown",
               "format", "wipe", "purge", "pay", "charge", "launch", "drop", "kill", "uninstall")

DEFAULT_AGENT = "planner"    # an unclear task goes to the planner — someone must break it down


def route_rules(task: str) -> tuple[str, float] | None:
    t = (task or "").lower()
    for words, agent, conf in RULES:
        if any(w in t for w in words):
            return agent, conf
    return None


def needs_human(task: str, agent: str, *, ships_without_human: bool = True) -> tuple[bool, str]:
    t = (task or "").lower()
    if any(w in t for w in HUMAN_WORDS):
        return True, "the task spends, deletes, or reaches outside — a human must approve"
    if not ships_without_human:
        return True, f"'{agent}' delivers outward — approval mandatory"
    return False, "internal work — the result stays a proposal in the system"


def add_rule(keywords: tuple[str, ...], agent: str, confidence: float = 0.8, *, first: bool = False) -> None:
    entry = (tuple(k.lower() for k in keywords), agent, confidence)
    RULES.insert(0, entry) if first else RULES.append(entry)
