"""Shared registry types; implementations do not import registry initialization."""
from dataclasses import dataclass
from typing import Callable, Awaitable
from pydantic import BaseModel, ConfigDict

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


@dataclass(frozen=True)
class Capability:
    name: str
    description: str
    input_model: type[Input]
    executor: Callable[..., Awaitable[dict]]
    verifier: Callable[..., Awaitable[dict]]
    risk_level: str = 'low'
    requires_approval: bool = False
    timeout_seconds: int = 30
    effect: str = 'read'

    def describe(self):
        return dict(name=self.name, description=self.description, input_schema=self.input_model.model_json_schema(),
                    risk_level=self.risk_level, requires_approval=self.requires_approval,
                    timeout_seconds=self.timeout_seconds, effect=self.effect)

