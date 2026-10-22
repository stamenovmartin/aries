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
    "ARIES_COMPLETION_READ_PARAPHRASE": (True, "the completion contract also recognises read, listing and existence "
                                               "goals said in natural words (exactly one path, nothing else "
                                               "asked) and strips sentence punctuation from paths; done still "
                                               "needs re-checked verified evidence. Off compiles only the "
                                               "anchored sentences, as in ARIES-FINAL-20261006"),
    "ARIES_COMPLETION_TYPED_CONTRACT": (False, "when the fast path gives no completion contract, one "
                                               "grammar-constrained call maps an English request to read, list, "
                                               "exists or none with a path and a name; code accepts it only if "
                                               "the path is the one path the request names, verbatim, and the "
                                               "name is empty or verbatim, as an existing contract shape. The "
                                               "model never decides completion (aries/workspace/typed_contract.py, "
                                               "preregistration H5). Off, the module is never imported"),
    "ARIES_CLARIFY_RESOLVER": (False, "a goal naming one folder gets a code-made, verified listing first; "
                                      "code counts the files whose names fit the request, and only when "
                                      "several fit does one small model call decide, accepted only if it "
                                      "quotes words of the request that fit that file alone, otherwise "
                                      "ARIES asks from a template. Adapted from ClarifyAgent and "
                                      "Ask-before-Plan (aries/workspace/clarify_resolver.py). Off, none of "
                                      "this runs"),
    "ARIES_PLANNER_CLARIFY_GUARD": (False, "with ARIES_PLANNER_CLARIFY: a question carries no capability or "
                                          "arguments (grammar), confirming is ask_approval and asking is "
                                          "only for choosing between observed targets (prompt), and a "
                                          "named but unlisted folder is listed before anything is read in "
                                          "it. Off leaves the clarification grammar and prompt unchanged"),
    "ARIES_PLANNER_CLARIFY": (True, "the planner may stop and ask which target is meant when its own "
                                    "verified observations show several that fit the goal; every choice "
                                    "must name something observed. Off removes the option from the "
                                    "grammar and the prompt"),
    "ARIES_VERIFY_HARDENED": (False, "the 23 verifiers the frozen review classed TRIVIAL, SELF_REPORT or "
                                     "PLANNER_SUPPLIED also require the report to agree with a fresh read "
                                     "(a different channel where one exists, measured drift for volatile "
                                     "values), per-capability invariants, and UNVERIFIED when that read "
                                     "fails (aries/workspace/hardened_verifiers.py, preregistration H8). "
                                     "Read when the registry is imported. Off, every verifier is the "
                                     "frozen function"),
    "ARIES_VERIFY_HARDENED_EXTRA": (False, "exploratory, designed after H8 baseline-2: the same hardening "
                                           "for two INDEPENDENT verifiers, notification.send and "
                                           "system.disk. Not part of the confirmatory H8 test"),
    "ARIES_MEASURE_CHANGE_HOOK": (False, "measurement only (H5 changed_after_read controls): before a finish "
                                         "is re-checked, a goal the runner has armed pauses once so the "
                                         "runner can change a file, then the check proceeds "
                                         "(aries/workspace/measurement_hook.py). Unarmed goals are not "
                                         "affected. Off, the hook module is never imported"),
    "ARIES_READ_PATH_STRICT": (False, "the legacy read_file route takes only the path token: it starts at "
                                      "the first / or ~/, filler words before it are allowed and any "
                                      "other words send the goal to the planner, it ends at the longest "
                                      "existing name or the first component with an extension, and a "
                                      "sentence-final mark is stripped only when the name without it "
                                      "exists or has an extension (docs/AUDIT.md 4a). Off, the capture is "
                                      "the rest of the sentence, as frozen"),
    "ARIES_LOOP_GUARD": (False, "a planner proposal whose capability and canonical arguments match two "
                                "earlier steps of the same goal (its second duplicate) ends the goal "
                                "instead of being rejected and replanned until the step budget is gone; "
                                "same terminal state as budget exhaustion, stop_reason REPEATED_ACTION, "
                                "fingerprint and count recorded (aries/workspace/loop_guard.py, "
                                "docs/AUDIT.md 4b). Off, the loop is unchanged"),
    "ARIES_PLAN_DISPATCH_FIX": (False, "when the planner context's own audit metadata (one omitted_items "
                                       "entry per memory dropped for budget, source_status, preferences) "
                                       "exceeds the 2,500-character budget, it is compacted (counts instead "
                                       "of entries, then source_status dropped, then preferences shortened) "
                                       "instead of failing the goal before its first planner call with "
                                       "'Context metadata exceeds planner budget' (docs/AUDIT.md 7.2: the six "
                                       "never-planned held-out goals). Off, the error is raised as frozen"),
    "ARIES_VERIFY_SCOPE": (False, "exploratory, designed after H8: the 14 capabilities of the H8 "
                                  "side_effect_outside_scope operator snapshot their declared scope "
                                  "before the executor runs (parent folder of each path, the other "
                                  "windows, the notification table) and their verifier fails when "
                                  "anything in it other than the target changed; an unreadable scope "
                                  "is UNVERIFIED (aries/workspace/scope_verifiers.py, docs/AUDIT.md "
                                  "4e). Read when the registry is imported. Off, every verifier is the "
                                  "frozen function"),
    "ARIES_CONTRACT_FILENAME_JOIN": (False, "designed after H5: a read or existence goal that names one folder and "
                                           "one bare file name (\"read notes.txt in ~/x\") gets a contract for "
                                           "the file in that folder, not for the folder; a read naming a folder "
                                           "and no single file gets no contract, and \"show me\" a path with an "
                                           "extension is a read, not a listing (aries/workspace/contracts.py). "
                                           "Off, the folder is the target, as in the H5 run"),
    "ARIES_TYPED_CONTRACT_CODE_PATH": (False, "designed after H5, with ARIES_COMPLETION_TYPED_CONTRACT: the model "
                                             "returns only the goal type and a verbatim name, and code supplies "
                                             "the one path the request names; a read of a folder with no name is "
                                             "rejected (aries/workspace/typed_contract.py). Off, the model copies "
                                             "the path, as in the H5 run"),
    "ARIES_RESOLVER_CODE_SELECT": (False, "designed after H4b, with ARIES_CLARIFY_RESOLVER: no model call decides "
                                         "between candidates; code selects the one candidate a request word or "
                                         "order word singles out (the same check that guarded the model's "
                                         "span), otherwise ARIES asks (aries/workspace/clarify_resolver.py). "
                                         "Off, the decision call runs, as in the H4b run"),
    "ARIES_ROUTER_CAPABILITY_GATE": (False, "designed after R1: when a local router decision would act, one "
                                           "grammar-constrained call names the registered capability that "
                                           "fulfils the request completely, or OUT_OF_SCOPE, which turns the "
                                           "decision into OUT_OF_SCOPE; it never turns an abstention into an "
                                           "action (aries/intelligence/capability_gate.py). Off, the module is "
                                           "never imported"),
    "ARIES_ROUTER_SURFACE_CONSISTENT": (False, "designed after R1: the router's abstention text no longer says "
                                              "the listed capabilities are never OUT_OF_SCOPE, says a request "
                                              "needing something none of them does is OUT_OF_SCOPE, and names "
                                              "email and calendar as having no capability. Off, the frozen A1 "
                                              "text"),
    "ARIES_PLANNER_PER_CAP_GRAMMAR": (False, "designed after R1: the planner grammar has one branch per "
                                            "capability with that capability's own required arguments, so an "
                                            "action missing a required argument cannot be generated "
                                            "(aries/workspace/agent_planner.py). Off, the flat grammar"),
    "ARIES_PLANNER_OOS_ACTION": (False, "designed after R1: when fail is allowed, the planner is told to choose "
                                       "fail with reason OUT_OF_SCOPE when no capability fulfils the goal "
                                       "completely, instead of the nearest capability. Off, no such message"),
    "ARIES_PLANNER_GATE_HINT": (False, "with ARIES_ROUTER_CAPABILITY_GATE: the planner is told which capability "
                                      "the gate chose as the first step. Off, the planner does not see it"),
    "ARIES_MEMORY_HYBRID_RRF": (False, "designed after LoCoMo: semantic-v3 memory retrieval fuses the cosine "
                                      "ranking with a BM25 ranking of the same rows by Reciprocal Rank Fusion "
                                      "(k=60) as its similarity term; recency, importance and layer are added "
                                      "as before (aries/workspace/retrieval.py). Off, cosine only"),
    "ARIES_LEARNING_RELATIVE_CTR": (False, "designed after MIND: the ordinary learning path judges a topic against "
                                          "this user's pooled engagement rate, each bar the smaller of its setting "
                                          "and 2x (engaged) or 0.5x (ignored) that rate (aries/learning/"
                                          "statistics.py). Off, the absolute settings 0.4 and 0.1"),
    "ARIES_NEWS_DIVERSE_TOPK": (False, "designed after MIND: the briefing picks by Maximal Marginal Relevance "
                                      "(lambda 0.7, topic redundancy) instead of round-robin over topics "
                                      "(aries/news/selection.py). Off, round-robin"),
    "ARIES_MEMORY_SIMILARITY_RANK": (False, "designed after M1 (LoCoMo): semantic-v3 memory retrieval orders by the "
                                           "similarity term alone (with ARIES_MEMORY_HYBRID_RRF, the fused rank); "
                                           "recency, importance and layer only break ties (aries/workspace/"
                                           "retrieval.py). Off, the weighted sum"),
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
