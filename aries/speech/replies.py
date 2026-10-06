"""Turning an outcome into an answer — the difference between working and feeling intelligent.

THE BUG THIS EXISTS FOR
-----------------------
On 2026-09-30 the whole voice loop was verified end to end: "Ари, колку место има
на дискот" was heard correctly, passed the wake gate, planned, executed
`system.storage`, and the step reached `state=verified` — independently checked.
Then ARIES said, out loud:

    "Task queued."

and the step's own summary was "Independently verified". Meanwhile the result
already held, in `execution_result.filesystems[0]`:

    metric disk.used_pct · subject / · value 8.5 % · free_gib 396.28 · size_gib 433.09

Every layer worked and none of it reached the person in words. The user's verdict
was exactly right: *"не гледам интелигентен Linux"* — they could not see an
intelligent Linux, because ARIES was not inarticulate about the answer, it was
articulate about its own process.

So: **a spoken reply answers the question. It never describes the machinery.**
"Task queued", "Independently verified", "1 results", "2 cards" are statements
about ARIES's internals. A person who asked how much disk space they have wants a
number, and if there is no number the honest reply is short and plain, not a
status word.

HOW THE ANSWER IS FOUND
-----------------------
Not per capability. ARIES already records measurements in one uniform shape, used
by the health probes, the storage probe and the system readings alike. The producer
(`Reading.as_dict()` in aries/health/findings.py) emits six keys — `metric`,
`subject`, `value`, `unit`, `detail` and `unavailable`; this consumes the first five
and ignores `unavailable`, because a reading that reports its own absence has no
number to say. So this walks the result for readings and speaks those,
which means a capability added later is covered without touching this file.

Cards are the second source, because a card is already written for a person.
`summary` is the last resort and is filtered, because that is where the process
language lives.

Numbers are left as digits on purpose. RHVoice and espeak-ng both expand them
correctly in Macedonian — "30%" is read "триесет посто", measured — so spelling
them out here would only introduce a second, worse number formatter.
"""
import re

# Never spoken. Each of these is ARIES talking about itself, and every one of them
# was observed being said out loud instead of an answer.
PROCESS_WORDS = (
    "task queued", "independently verified", "queued", "verification met",
    "no verification", "unconfirmed", "state: done", "accepted",
)
_COUNT_ONLY = re.compile(r"^\d+\s+(results?|cards?|items?|rows?|entries)\.?$", re.I)

# A reading's metric name is a dotted machine word. These are the ones a person
# actually asks about; anything else is spoken with its subject as a fallback.
READINGS = {
    "disk.used_pct": ("Дискот{subject} е на {value}%", "Disk{subject} is {value}% full"),
    "memory.used_pct": ("Меморијата е на {value}%", "Memory is {value}% used"),
    "cpu.used_pct": ("Процесорот е на {value}%", "The processor is at {value}%"),
    "cpu.temperature": ("Процесорот е на {value} степени", "The processor is at {value} degrees"),
    "gpu.used_pct": ("Графичката е на {value}%", "The GPU is at {value}%"),
    "gpu.temperature": ("Графичката е на {value} степени", "The GPU is at {value} degrees"),
    "uptime.days": ("Машината работи {value} дена", "The machine has been up {value} days"),
}
FREE_SPACE = ("Слободни ти се {free} гигабајти од {size}",
              "You have {free} gigabytes free of {size}")

NOTHING = ("Не најдов одговор на тоа.", "I did not find an answer to that.")
DONE = ("Готово.", "Done.")
FAILED = ("Не успеа. {why}", "It failed. {why}")
HELD = ("Чека твое одобрување.", "It is waiting for your approval.")


def _pick(pair, language):
    return pair[0] if language == "mk" else pair[1]


def _readings(node, found=None):
    """Every measurement anywhere in a result, in the order encountered.

    Deliberately shape-driven rather than path-driven: a reading is any mapping
    with a `metric` and a `value`, wherever it sits. A capability that nests its
    output differently is still heard.
    """
    found = [] if found is None else found
    if isinstance(node, dict):
        if "metric" in node and node.get("value") is not None:
            found.append(node)
        for value in node.values():
            _readings(value, found)
    elif isinstance(node, list):
        for item in node[:40]:                 # bounded: a reply is a sentence, not a report
            _readings(item, found)
    return found


def _is_process_talk(text):
    low = " ".join((text or "").split()).casefold().rstrip(".")
    return (not low) or low in PROCESS_WORDS or bool(_COUNT_ONLY.match(low))


def _number(value):
    """8.5 stays 8.5; 8.0 becomes 8. A trailing .0 read aloud is noise."""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return str(value)


# A mount point read aloud is noise. "/" is "the disk" to a person, and nobody
# asked about /boot/efi — it is 500 MB of firmware and it is always nearly empty.
BORING_MOUNTS = ("/boot", "/boot/efi", "/efi", "/snap", "/var/snap", "/run")


def _spoken_subject(subject):
    if subject in ("/", ""):
        return ""
    return " " + subject


def from_readings(result, language):
    """One sentence built from the measurements, or None if there are none."""
    said, spoken_already = [], set()
    for reading in _readings(result):
        metric, subject = str(reading.get("metric", "")), str(reading.get("subject") or "")
        # The same measurement appears more than once in a result — the executor's
        # copy and the verifier's independent re-read are both in there, which is
        # the point of the verifier and not a bug. Saying it twice would be.
        if (metric, subject) in spoken_already:
            continue
        spoken_already.add((metric, subject))
        if metric.startswith("disk.") and subject in BORING_MOUNTS:
            continue
        template = READINGS.get(metric)
        if template:
            said.append(_pick(template, language).format(
                value=_number(reading["value"]), subject=_spoken_subject(subject)).replace("  ", " ").strip())
            # Free space is what a person means by "how much space do I have".
            detail = reading.get("detail") or {}
            if metric == "disk.used_pct" and detail.get("free_gib") and subject in ("/", ""):
                said.append(_pick(FREE_SPACE, language).format(
                    free=_number(round(detail["free_gib"])), size=_number(round(detail.get("size_gib", 0)))))
        elif subject and reading.get("unit"):
            said.append(f"{subject}: {_number(reading['value'])}{reading['unit']}")
        if len(said) >= 3:                     # three facts is a spoken answer; ten is a lecture
            break
    return ". ".join(said) + "." if said else None


def from_cards(result, language):
    """Cards are already written for a person, so they are the next best source."""
    cards = result.get("cards") if isinstance(result, dict) else None
    if not cards:
        return None
    spoken = []
    for card in cards[:2]:
        title, text = str(card.get("title") or "").strip(), str(card.get("text") or "").strip()
        if _is_process_talk(text) or len(text) > 220:
            text = ""
        part = f"{title}: {text}" if title and text else (text or title)
        if part and not _is_process_talk(part):
            spoken.append(part)
    if not spoken:
        return None
    more = len(cards) - len(spoken)
    tail = (f" И уште {more}." if language == "mk" else f" And {more} more.") if more > 0 else ""
    return ". ".join(spoken).rstrip(".") + "." + tail


# Spoken when every step that produced an answer declared itself unverifiable.
# Research is the case: collecting sources cannot confirm that what was collected
# is what the question needed. Before this, such a goal spoke its findings in the
# same tone as a verified measurement — 6 223 steps in the recorded history.
UNVERIFIED = ("Еве што најдов, но не можам да потврдам дека е целосно.",
              "Here is what I found, but I cannot confirm it is complete.")


def _all_unverifiable(outcome):
    """True when any answering step is explicitly unverifiable, including mixtures."""
    steps = [s for s in (outcome.get("steps") or []) if isinstance(s, dict)]
    declaring = [s for s in steps
                 if isinstance(s.get("verification"), dict)
                 and s["verification"].get("unverifiable") is True]
    if not declaring:
        return False
    return bool(declaring)


def sentence(outcome, *, language="mk"):
    """What ARIES should say about this outcome. Never None — silence is not an answer.

    Order is deliberate: measured values first because they are the answer, cards
    next because they were written for a person, and `summary` last and filtered,
    because `summary` is where "Task queued" comes from.
    """
    if not isinstance(outcome, dict):
        return _pick(NOTHING, language)
    state = str(outcome.get("state") or "").casefold()
    if state == 'needs_clarification':
        clarification = outcome.get('clarification') or {}
        question = clarification.get('question') if isinstance(clarification, dict) else None
        if isinstance(question, str) and question.strip():
            return question.strip()
    if state in {"proposed", "held", "awaiting_approval"}:
        return _pick(HELD, language)

    # A failed outcome is reported as failed even when it carries readings.
    # Found by the Codex session on 2026-09-30: an earlier step's measurements
    # survive in the record, so mining readings first made a FAILED goal say
    # "Дискот е на 8.5%" and never mention that it failed. Stale evidence spoken
    # confidently is the exact thing the rest of this project refuses to do.
    if state in {"failed", "refused", "interrupted", "error"}:
        why = str(outcome.get("error") or outcome.get("detail")
                  or outcome.get("summary") or "").strip()
        if _is_process_talk(why):
            why = ""
        return _pick(FAILED, language).format(why=why).strip()

    unverifiable = _all_unverifiable(outcome)
    for source in (from_readings, from_cards):
        said = source(outcome, language)
        if said:
            # The finding is still the answer; the caveat goes in front of it so a
            # person hears the uncertainty before the content, not after.
            return f"{_pick(UNVERIFIED, language)} {said}" if unverifiable else said
    # Steps carry their own results; a goal's answer is usually one level down.
    for step in (outcome.get("steps") or [])[:6]:
        nested = step.get("result") if isinstance(step, dict) else None
        if isinstance(nested, dict):
            said = from_readings(nested, language) or from_cards(nested, language)
            if said:
                return f"{_pick(UNVERIFIED, language)} {said}" if unverifiable else said

    summary = str(outcome.get("summary") or outcome.get("message") or "").strip()
    if summary and not _is_process_talk(summary):
        said = summary if summary.endswith((".", "!", "?")) else summary + "."
        return f"{_pick(UNVERIFIED, language)} {said}" if unverifiable else said
    if state in {"done", "answered", "partial", "verified"}:
        return _pick(UNVERIFIED, language) if unverifiable else _pick(DONE, language)
    return _pick(NOTHING, language)
