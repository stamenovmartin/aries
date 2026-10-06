"""One place that answers "is this behaviour on?" — and nothing else.

WHY A MODULE AND NOT `if os.environ.get(...)` AT EACH SITE
----------------------------------------------------------
The build plan of 2026-10-03 puts every behaviour change behind a flag so that the
measurements afterwards can run with it on and with it off. That only works if the
flags can be enumerated: an ablation that has to grep for its own switches will
miss one, and a missed switch is a measurement that silently compares the wrong
two things. `describe()` exists for exactly that, and the eval harnesses read it.

The same argument applies to language. Before this module, the primary language was
decided in several places at once — `aries/speech/__init__.py` defaulted a reply to
Macedonian with `language or "mk"`, `engines.DEFAULTS` held its own map, and the
voice daemon carried a two-language detection list. English became primary on
2026-10-03 and Macedonian was frozen; doing that by editing each site would have
left exactly the kind of scattered condition this project keeps paying for.

WHAT "FROZEN" MEANS, PRECISELY
------------------------------
Macedonian keeps working and keeps being tested. Nothing new is built on it, and no
measurement reported from here on is taken in Macedonian unless it says so. Frozen
is not removed: `mk_frozen()` being true must never make a Macedonian request fail,
and `tests/frozen_mk/` proves it still answers.

Flags default ON, so a fresh checkout behaves like the system the owner approved.
Turning one off is an explicit act, which is the direction that should take effort.
"""
from __future__ import annotations

import os
import pathlib
import time

# Each entry: the default, and what the flag governs. The text is not decoration —
# it is printed by `describe()` into every evaluation artefact, so a run from three
# months from now still says what was switched on when it was taken.
# NOT LISTED, DELIBERATELY. Three flags were declared here on 2026-10-03 and read
# nowhere — `ARIES_VERIFY_ALL`, `ARIES_REACT_LOOP` and `ARIES_CLARIFY`. A switch that
# governs nothing is worse than no switch: an ablation turns it off, measures no
# change, and records that the behaviour does not matter. That is the same shape as
# the playback thresholds found dead the same morning, so they are removed rather
# than left looking like features.
#
# Each needs its alternative to exist before it can be a flag:
#   ARIES_VERIFY_ALL   verification has no "off" path, and building one would mean
#                      writing a mode that reports unverified work as done.
#   ARIES_REACT_LOOP   the loop is the only planner there has ever been here; the
#                      alternative, a one-shot plan, has never existed in this
#                      codebase and writing a worse one to measure against is not
#                      an experiment.
#   ARIES_CLARIFY      the clarification gate lives in `aries/workspace/service.py`,
#                      held by another agent today. It is switchable, by whoever owns
#                      that file.
FLAGS = {
    "ARIES_TERMINAL_READ_FAILURE": (True, "stop repeated model planning after an actual nonretryable missing-file error for the exact single requested read"),
    "ARIES_CONTRACT_FINISH": (True, "propose completion without another model call when every ordered goal condition has verified evidence; fresh independent recheck still required"),
    "ARIES_CONTEXT_ENGINE": (True, "select memory, recent task history and permitted cached news with provenance, expiry and explicit missing-source coverage"),
    "ARIES_GOAL_TEAMS": (False, "decompose eligible goals into scoped temporary read-only runtime agents in the existing queue"),
    "ARIES_COMPLETION_PROGRESS_GUARD": (True, "stop after two rejected completion proposals without "
                                             "an intervening action; preserve one correction opportunity"),
    "ARIES_VERIFY_FEEDBACK": (True, "the planner is told whether each past step's effect was "
                                    "INDEPENDENTLY OBSERVED, not merely whether the tool returned. "
                                    "Off leaves the loop, the retry policy and the step history "
                                    "untouched and removes only that — the one variable in the "
                                    "state-verification-feedback experiment"),
    "ARIES_STATE_SNAPSHOT": (True, "the planner is given the current desktop state before it plans"),
    "ARIES_CAP_TOPK": (True, "the planner is sent the most relevant capabilities, not all of them"),
    "ARIES_PLAN_MEMORY": (True, "relevant remembered facts are injected into planning"),
    "ARIES_ROUTER_ABSTAIN": (True, "the router may answer ASK or OUT_OF_SCOPE rather than "
                                   "choosing the nearest action; off restores the pre-2026-10-03 "
                                   "instruction to pick the nearest one regardless"),
    "ARIES_TRACE_FEWSHOT": (True, "similar past successful plans are offered to the planner"),
    "ARIES_MK_FROZEN": (True, "Macedonian is frozen: it keeps working and keeps being tested, "
                              "and nothing new is built on it"),
    "ARIES_TYPE_STRICT": (True, "input.type_text refuses any case that would silently lose "
                                "characters — a NUL, a filtered control character, a line break "
                                "into a single-line control, a rejected or partially landed write "
                                "— instead of returning a success carrying landed=false"),
    "ARIES_TILE_HIDPI": (True, "desktop.tile reads the monitor's scale factor from Mutter and "
                               "expects the device-pixel-aligned rectangle, so a correct tile on a "
                               "fractionally scaled display is not reported unverified"),
}

TRUTHY = {"1", "true", "yes", "on"}
FALSEY = {"0", "false", "no", "off"}

# WHY A FILE AND NOT JUST THE ENVIRONMENT
#
# The ablation in Part B turns each flag off one at a time — ten runs against a
# long-lived service. Reaching the service through the environment means editing
# the unit and restarting `aries-core` ten times, and a restart is not neutral: it
# drops the route cache, interrupts whatever the scheduler was doing, and makes the
# source hashes in two consecutive results differ for a reason that has nothing to
# do with the flag. So a running process can also be told through a file, which it
# re-reads when it changes.
#
# The environment still wins. A measurement harness that sets a variable in its own
# process must not be silently overruled by a file somebody left behind.
OVERRIDE_FILE = pathlib.Path(
    os.environ.get("ARIES_FLAG_FILE") or (pathlib.Path(__file__).resolve().parents[1] / "var/flags.env"))
_FILE_CACHE: dict = {"read_at": 0.0, "mtime": None, "values": {}}
_FILE_TTL = 2.0


def _from_file() -> dict:
    """KEY=VALUE lines, re-read when the file changes. Unparseable lines are ignored.

    Ignored rather than raised on: this file is edited by a harness mid-run, and a
    half-written line should not take the assistant down.
    """
    now = time.monotonic()
    if now - _FILE_CACHE["read_at"] < _FILE_TTL:
        return _FILE_CACHE["values"]
    try:
        stamp = OVERRIDE_FILE.stat().st_mtime_ns
    except OSError:
        _FILE_CACHE.update(read_at=now, mtime=None, values={})
        return {}
    if stamp != _FILE_CACHE["mtime"]:
        values = {}
        try:
            for line in OVERRIDE_FILE.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
        except OSError:
            values = {}
        _FILE_CACHE.update(mtime=stamp, values=values)
    _FILE_CACHE["read_at"] = now
    return _FILE_CACHE["values"]


def source_of(name: str) -> str:
    """Where this flag's value came from. Printed into every evaluation artefact."""
    if name in os.environ:
        return "environment"
    if name in _from_file():
        return f"file {OVERRIDE_FILE.name}"
    return "default"

#: Languages ARIES will recognise and answer in. Order is not significance; the
#: primary language is `primary_language()`.
SUPPORTED = ("en", "mk")

#: Whisper builds present on this machine. `turbo` is faster and is an English
#: choice; which one ships is a Part B measurement, not a preference.
WHISPER_MODELS = {
    "large-v3": "var/models/faster-whisper-large-v3",
    "large-v3-turbo": "var/models/faster-whisper-large-v3-turbo",
    "base": "var/models/faster-whisper-base",
}


def enabled(name: str) -> bool:
    """Is this flag on? Unknown names raise rather than quietly reading False.

    A typo in a flag name would otherwise disable a behaviour and look like a
    measurement, which is the worst available outcome.
    """
    if name not in FLAGS:
        raise KeyError(f"unknown flag {name!r}; add it to aries.flags.FLAGS with its description")
    raw = os.environ.get(name)
    if raw is None:
        raw = _from_file().get(name)
    if raw is None:
        return FLAGS[name][0]
    value = raw.strip().casefold()
    if value in TRUTHY:
        return True
    if value in FALSEY:
        return False
    raise ValueError(f"{name}={raw!r} is neither true nor false; use 1/0")


def primary_language() -> str:
    """The language ARIES speaks and listens in unless told otherwise.

    English since 2026-10-03. An unsupported value is a configuration error worth
    raising on: silently falling back to English would hide it for weeks.
    """
    code = (os.environ.get("ARIES_PRIMARY_LANG") or _from_file().get("ARIES_PRIMARY_LANG")
            or "en").strip().casefold()
    if code not in SUPPORTED:
        raise ValueError(f"ARIES_PRIMARY_LANG={code!r} is not one of {SUPPORTED}")
    return code


def mk_frozen() -> bool:
    return enabled("ARIES_MK_FROZEN")


def listen_languages() -> tuple[str, ...]:
    """Which languages the speech recogniser may choose between.

    When English is primary the recogniser is given English alone. That is not
    tidiness: left to choose among 99 languages Whisper answered Macedonian speech
    with Portuguese, Bulgarian, Romanian, Croatian and Polish, and our own filter
    then discarded seven of ten real commands (measured 2026-10-03). One language
    cannot be misdetected.
    """
    code = primary_language()
    return (code,) if code == "en" else (code, "en")


def whisper_model() -> str:
    """Path to the recogniser build. `ARIES_WHISPER_MODEL` selects by name."""
    name = (os.environ.get("ARIES_WHISPER_MODEL") or _from_file().get("ARIES_WHISPER_MODEL")
            or "large-v3").strip()
    if name not in WHISPER_MODELS:
        raise ValueError(f"ARIES_WHISPER_MODEL={name!r} is not one of {sorted(WHISPER_MODELS)}")
    return WHISPER_MODELS[name]


def describe() -> dict:
    """Everything a result file needs to say what it was measuring.

    Includes flags left at their default, because "not set" and "set to the default"
    are the same behaviour and an ablation table that omits one of them is unreadable.
    """
    return {
        "primary_language": primary_language(),
        "listen_languages": list(listen_languages()),
        "whisper_model": os.environ.get("ARIES_WHISPER_MODEL") or "large-v3",
        "override_file": str(OVERRIDE_FILE),
        "flags": {name: {"on": enabled(name), "default": default,
                         "source": source_of(name), "governs": governs}
                  for name, (default, governs) in sorted(FLAGS.items())},
    }
