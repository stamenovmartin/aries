"""WHAT settings exist — declared once, in one place.

Specification section 31 asks for a typed Settings Service so that "agents
should retrieve settings through this service" and not "maintain [their] own
unrelated preference copy". Section 34 asks that configuring ARIES feel like
configuring an operating system, not editing YAML. Both requirements are served
by the same idea: a setting is DATA, declared here, and everything else is
derived from that declaration.

From one `SettingDef` we get:
  * the default value                       (the DEFAULT layer)
  * validation of anything written          (`coerce`)
  * the control the Settings app renders    (`control`, `choices`, `minimum`…)
  * the text an agent reads to understand the knob (`description`)
  * whether a machine may ever write it     (`user_only`)

CONCEPT — a schema registry. Rather than a Python class with attributes (which
would be typed but not introspectable at runtime, and would need code changes in
two places to add a knob), settings are registered into a dictionary keyed by a
dot path. Dot paths give us namespacing for free: `news.*` belongs to the News
section, `ai.*` to the AI section, and a UI can group by prefix without being
told the grouping separately. The cost is that we validate by hand instead of
leaning on pydantic; `coerce()` below is that validation, and it is deliberately
strict — a setting that silently accepts a wrong type becomes a bug in whatever
agent reads it three layers away.

This module holds NO values. It holds the definitions; `store.py` holds values
and `service.py` resolves them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class SettingError(ValueError):
    """A write that the schema refuses."""


@dataclass(frozen=True)
class SettingDef:
    """One configurable knob."""

    key: str                              # dot path, e.g. "news.relevance_threshold"
    type: type                            # bool | int | float | str | list | dict
    default: Any
    title: str                            # short label for the Settings app
    description: str                      # what it does, in a sentence an agent can read
    section: str                          # top-level Settings section: "general", "ai", "news"…
    control: str = "text"                 # text | toggle | number | slider | select | multiselect | list
    choices: tuple[Any, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    advanced: bool = False                # hidden behind "Advanced" in the UI
    user_only: bool = False               # a learning loop may never write this
    restart_required: bool = False
    validator: Callable[[Any], Any] | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def coerce(self, value: Any) -> Any:
        """Validate and normalise a value for this setting, or raise SettingError."""
        v = value
        # bool must be checked before int: in Python, True is an instance of int.
        if self.type is bool:
            if isinstance(v, str):
                low = v.strip().lower()
                if low in ("true", "yes", "on", "1"):
                    v = True
                elif low in ("false", "no", "off", "0"):
                    v = False
                else:
                    raise SettingError(f"{self.key}: expected a boolean, got {value!r}")
            if not isinstance(v, bool):
                raise SettingError(f"{self.key}: expected a boolean, got {type(value).__name__}")
        elif self.type in (int, float):
            if isinstance(v, bool):
                raise SettingError(f"{self.key}: expected a number, got a boolean")
            try:
                v = self.type(v)
            except (TypeError, ValueError):
                raise SettingError(f"{self.key}: expected {self.type.__name__}, got {value!r}") from None
            if self.minimum is not None and v < self.minimum:
                raise SettingError(f"{self.key}: {v} is below the minimum {self.minimum}")
            if self.maximum is not None and v > self.maximum:
                raise SettingError(f"{self.key}: {v} is above the maximum {self.maximum}")
        elif self.type is str:
            if not isinstance(v, str):
                raise SettingError(f"{self.key}: expected a string, got {type(value).__name__}")
            v = v.strip()
        elif self.type is list:
            if isinstance(v, tuple):
                v = list(v)
            if not isinstance(v, list):
                raise SettingError(f"{self.key}: expected a list, got {type(value).__name__}")
        elif self.type is dict:
            if not isinstance(v, dict):
                raise SettingError(f"{self.key}: expected an object, got {type(value).__name__}")

        if self.choices is not None:
            bad = [x for x in v if x not in self.choices] if self.type is list else \
                  ([] if v in self.choices else [v])
            if bad:
                raise SettingError(f"{self.key}: {bad!r} not in {list(self.choices)}")
        if self.validator is not None:
            v = self.validator(v)
        return v

    def describe(self) -> dict:
        """The JSON an API or a Settings UI renders from."""
        return {"key": self.key, "type": self.type.__name__, "default": self.default,
                "title": self.title, "description": self.description, "section": self.section,
                "control": self.control, "choices": list(self.choices) if self.choices else None,
                "minimum": self.minimum, "maximum": self.maximum, "unit": self.unit,
                "advanced": self.advanced, "user_only": self.user_only,
                "restart_required": self.restart_required, "tags": list(self.tags)}


_REGISTRY: dict[str, SettingDef] = {}


def define(d: SettingDef, *, replace: bool = False) -> SettingDef:
    """Register a setting. A duplicate key is a programming error, not a merge."""
    if d.key in _REGISTRY and not replace:
        raise SettingError(f"setting '{d.key}' is already defined")
    d.coerce(d.default)          # a default that fails its own validation is a bug
    _REGISTRY[d.key] = d
    return d


def get_def(key: str) -> SettingDef | None:
    return _REGISTRY.get(key)


def require(key: str) -> SettingDef:
    d = _REGISTRY.get(key)
    if d is None:
        raise SettingError(f"unknown setting '{key}'")
    return d


def all_defs() -> list[SettingDef]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def in_section(section: str) -> list[SettingDef]:
    return [d for d in all_defs() if d.section == section]


def sections() -> list[str]:
    seen: list[str] = []
    for d in all_defs():
        if d.section not in seen:
            seen.append(d.section)
    return seen


def matching(prefix: str) -> list[SettingDef]:
    """Every setting under a dot-path prefix — `matching("news")` → all news.* keys."""
    p = prefix.rstrip(".") + "."
    return [d for d in all_defs() if d.key.startswith(p) or d.key == prefix]
