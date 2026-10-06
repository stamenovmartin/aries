"""WHO decided a setting — and therefore who wins.

Section 30 of the ARIES specification fixes a precedence model. It is not a
suggestion: it is the rule that keeps an adaptive system trustworthy. A system
that learns is only tolerable if the user can always overrule what it learned,
so the ordering below is encoded once, here, and every read of every setting
resolves through it.

    1. Security policy          — a hard constraint; nothing overrides it
    2. Explicit user restriction— "never do X"; beats even a later preference
    3. Explicit user setting    — what the user configured in the UI
    4. Current explicit instruction — "for this run, do Y"
    5. Project preference       — scoped to one project
    6. Learned preference       — inferred from behaviour, with a confidence
    7. Historical behaviour     — a weak statistical prior
    8. Default                  — what ships in the schema

CONCEPT — layered configuration. A single key (say `news.relevance_threshold`)
may hold a value at several layers at once: a default of 0.6 in the schema, a
learned 0.72 from the user ignoring low scorers, and an explicit 0.5 the user
typed into Settings. Resolution walks from the strongest layer down and returns
the first value it finds, together with the layer it came from. Nothing is
deleted when it is overridden — the learned value stays recorded, it simply
loses. That matters for two reasons: the UI can show "you set 0.5; ARIES would
have guessed 0.72", and if the user later clears their explicit value the
learned one takes over again without having to be re-learned.

The numbers are deliberately spaced so layers can be inserted later without
renumbering stored rows.
"""
from __future__ import annotations

from enum import IntEnum


class Layer(IntEnum):
    """Precedence of a stored setting value. Higher wins."""

    DEFAULT = 10             # 8. schema default
    HISTORICAL = 20          # 7. weak prior from past behaviour
    LEARNED = 30             # 6. inferred preference, carries a confidence
    PROJECT = 40             # 5. preference scoped to one project
    INSTRUCTION = 50         # 4. "for this task, do Y"
    USER = 60                # 3. explicit configuration in the UI
    RESTRICTION = 70         # 2. explicit prohibition by the user
    SECURITY = 80            # 1. security policy — absolute

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def is_user_authored(self) -> bool:
        """True when a human stated it. Machine layers may never overwrite these."""
        return self in (Layer.INSTRUCTION, Layer.USER, Layer.RESTRICTION, Layer.SECURITY)

    @property
    def is_inferred(self) -> bool:
        """True when ARIES concluded it on its own."""
        return self in (Layer.HISTORICAL, Layer.LEARNED)


_LABELS: dict[Layer, str] = {
    Layer.DEFAULT: "default",
    Layer.HISTORICAL: "historical behaviour",
    Layer.LEARNED: "learned preference",
    Layer.PROJECT: "project preference",
    Layer.INSTRUCTION: "explicit instruction",
    Layer.USER: "user setting",
    Layer.RESTRICTION: "user restriction",
    Layer.SECURITY: "security policy",
}

# The layers an automated writer (the learning loops of specification section 16)
# is allowed to write. Anything else must come from a human or the security
# policy, and `SettingsService.set` enforces it.
MACHINE_WRITABLE: frozenset[Layer] = frozenset({Layer.DEFAULT, Layer.HISTORICAL, Layer.LEARNED})


def resolve(values: dict[Layer, object]) -> tuple[Layer, object] | None:
    """Return the winning (layer, value) from everything stored for one key."""
    if not values:
        return None
    winner = max(values)
    return winner, values[winner]
