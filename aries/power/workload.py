"""What kind of work an automation is — the vocabulary the resource policy reads.

Background Mode keeps the machine awake. That is a promise about *availability*,
and on its own it is dangerous: a machine that never sleeps and is free to start
a two-hour GPU job at 3 a.m. is a machine that cooks itself quietly while nobody
is watching the fans.

So Background Mode also has to answer a second question — not "may the machine
stay awake?" but "may *this* run right now?" — and that needs the work to say
what it is. An automation declares its class in its genome, where every other
static fact about it already lives, so the declaration is versioned, diffable,
and visible in the Control Centre next to its permissions.

WHY A DECLARATION AND NOT A MEASUREMENT
---------------------------------------
ARIES could watch what an automation *did* last time and infer that it is heavy.
That is a worse design for a gate: the first run is the one that would hurt, the
inference is wrong for work whose cost depends on its input (a repository scan,
an inference batch), and it makes the rule impossible to read. A declaration is
checkable before anything runs, and being wrong about it is a visible bug in a
spec rather than an invisible property of history.

The classes are deliberately few. Three would not distinguish "a model answering
one short question" from "a model running for an hour"; six would be a taxonomy
nobody could apply consistently.
"""
from __future__ import annotations

from dataclasses import dataclass

# The resources a class is judged against. A class is never judged against a
# resource it cannot meaningfully load: gating a health check on CPU utilisation
# would defer the very measurement that says the machine is busy.
CPU = "cpu"
GPU = "gpu"
TEMPERATURE = "temperature"


@dataclass(frozen=True)
class WorkloadClass:
    name: str
    title: str
    description: str
    heavy: bool
    # Which setting must be ON before this may run unattended. None means the
    # class needs no permission — it is allowed by default, as §11's "nothing is
    # enabled by default" applies to automations, not to the cost of the work an
    # already-enabled automation does.
    permission_setting: str | None
    watches: tuple[str, ...]
    budgeted: bool

    def as_dict(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description,
                "heavy": self.heavy, "permission_setting": self.permission_setting,
                "watches": list(self.watches), "budgeted": self.budgeted}


LIGHT = WorkloadClass(
    "light", "Lightweight",
    "Reading files, fetching feeds, arithmetic over rows. Costs a fraction of one core for "
    "seconds. Always allowed, including while the display is off.",
    heavy=False, permission_setting=None, watches=(), budgeted=False)

INFERENCE_LIGHT = WorkloadClass(
    "inference_light", "Lightweight inference",
    "A model answering a bounded question — classification, a short summary. Allowed while "
    "the display is off; it is not a sustained load.",
    heavy=False, permission_setting=None, watches=(), budgeted=False)

HEAVY_CPU = WorkloadClass(
    "heavy_cpu", "Sustained high CPU",
    "Work that will hold several cores busy for minutes — indexing, a large local model, a "
    "full repository analysis. Blocked while the display is off unless enabled, and budgeted "
    "when it is.",
    heavy=True, permission_setting="power.allow_heavy_cpu",
    watches=(CPU, TEMPERATURE), budgeted=True)

HEAVY_GPU = WorkloadClass(
    "heavy_gpu", "Sustained GPU",
    "Work that will hold the GPU busy — local model inference or training. Blocked while the "
    "display is off unless enabled, and budgeted when it is.",
    heavy=True, permission_setting="power.allow_gpu_jobs",
    watches=(GPU, TEMPERATURE), budgeted=True)

CLASSES: dict[str, WorkloadClass] = {c.name: c for c in
                                     (LIGHT, INFERENCE_LIGHT, HEAVY_CPU, HEAVY_GPU)}
DEFAULT = LIGHT.name

# What the Control Centre and `aries power status` list, in the order a person
# reads them: cheapest first.
ORDER = (LIGHT.name, INFERENCE_LIGHT.name, HEAVY_CPU.name, HEAVY_GPU.name)


def get(name: str | None) -> WorkloadClass:
    """Retain the legacy missing-field default; reject invalid declarations."""
    key = DEFAULT if name is None else name
    if not isinstance(key, str) or key not in CLASSES:
        raise ValueError(f"Unknown workload class: {name!r}")
    return CLASSES[key]


def describe_all() -> list[dict]:
    return [CLASSES[n].as_dict() for n in ORDER]
