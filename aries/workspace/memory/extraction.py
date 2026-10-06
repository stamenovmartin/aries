"""What is worth remembering — three stages, cheapest first.

    1. gate       ~0 ms   excluded topics, secrets, length, privacy switch
    2. novelty    ~8 ms   embed once, cosine against the cached matrix
    3. decide     ~0.1 s  the local model, ONE bare enum, off the voice path

Stage 3 never runs on every turn. Stage 2 resolves anything clearly redundant
(bump the neighbour's retrieval count and stop) and anything clearly novel
(keep it) without a model at all; only the uncertain middle band escalates.
SAGE (arXiv:2605.30711) reports that band skipping 16-18% of LLM calls.

MEASURED HERE IT SAVES LESS THAN THAT, and the honest number is in
`experiments/memory/analysis.md`: over 45 utterances, stage 1 refused 12 (27%),
stage 2 settled 6 more (13%), and **27 still escalated — a 60% escalation
rate**. The reason belongs to the embedder rather than the method. e5 puts every
pair of short sentences between roughly 0.83 and 0.99, so the band that keeps a
contradiction (0.950) out of the "already known" bucket is necessarily wide. A
textbook 0.9 / 0.5 band would have filed both contradictions in this corpus as
duplicates and thrown them away, while judging nothing novel at all, because
nothing scores below 0.5.

NONE OF THIS IS ON THE VOICE PATH. `store.observe_later` debounces and runs it
after the turn has already been acted on.

WHAT THE MODEL IS AND IS NOT ASKED
----------------------------------
It is asked for one of four names. It is never asked which of two conflicting
facts is true — that is decided deterministically by timestamp in `store`, per
Zep (arXiv:2501.13956), because a model asked to arbitrate will prefer the
better-written fact over the more recent one.

    APPEND     worth keeping, and it does not collide with what is stored
    SUPERSEDE  it contradicts something stored; the newer one will win, by clock
    COEXIST    it differs from something stored and both stay true
    ABORT      not worth keeping

COEXIST is the label that earns its place. TANGLE (arXiv:2608.13921) shows that
a preference which varies by circumstance — coffee in the morning, tea at night
— is not a contradiction, and a memory system that resolves every conflict by
picking a winner destroys exactly the knowledge that made it useful.
"""
from __future__ import annotations

import os
import re
import unicodedata

from aries.workspace.memory import calibration

LABELS = ("APPEND", "SUPERSEDE", "COEXIST", "ABORT")
OLLAMA = os.environ.get("ARIES_OLLAMA", "http://127.0.0.1:11434")

# Stage-2 band. Above REDUNDANT the utterance says nothing new; below NOVEL it
# is plainly unrelated to everything stored. Between them, ask the model.
#
# CALIBRATED, NOT ASSUMED, and specific to this embedder. Measured on
# experiments/memory/corpus.jsonl with e5-base-int8: a restatement of a stored
# note scores 0.992, a statement that CONTRADICTS one scores 0.950, one that
# qualifies one scores 0.939, and genuinely unrelated pairs bottom out at 0.827.
# The whole usable range is 0.83-0.99, so a textbook 0.90/0.50 band would call
# a contradiction a duplicate and would never find anything novel. The upper
# bound therefore sits above the highest observed contradiction and the lower
# bound just above the highest observed unrelated pair. A different embedder
# has a different distribution, which is why `Cascade` takes these as arguments
# instead of reading the constants.
REDUNDANT_ABOVE = .97
NOVEL_BELOW = .85

MIN_CHARS, MAX_CHARS = 8, 2000

# Things that must never reach the write path however useful they look. The
# credential store is encrypted and elsewhere; memory is neither.
SECRETS = re.compile(
    r"(?:\b(?:password|passwd|passphrase|api[_ -]?key|secret|token|credential|"
    r"лозинк|лозинка|шифра|парол)\w*\b\s*[:=]?\s*\S+)"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY"
    r"|\bssh-(?:rsa|ed25519|dss)\s+[A-Za-z0-9+/]{20,}"
    r"|\b(?:sk|pk|ghp|gho|xox[baprs])-[A-Za-z0-9_-]{16,}\b"
    r"|\b(?:\d[ -]?){13,19}\b"                       # a card number, spaced or not
    r"|\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b",            # an IBAN
    re.IGNORECASE)

# Commands are not memories. "open YouTube" said four hundred times is a habit,
# and a habit belongs to the learning loop's interest weights, not here. This is
# the deterministic half of what stage 3 would otherwise be asked every turn.
COMMAND = re.compile(
    r"^(?:ari[,.]?\s+)?(?:please\s+|ве\s+молам\s+|те\s+молам\s+)?"
    r"(?:open|launch|start|run|play|show|close|stop|pause|split|mute|search|"
    r"google|otvori|pusti|prikazi|zatvori|najdi|pokreni|"
    r"отвори|пушти|прикажи|затвори|најди|покрени|вклучи|исклучи|стопирај)\b",
    re.IGNORECASE)

# Asking for information is not asserting a personal fact. Keep this bounded:
# declarative sentences containing these words and explicit remember() requests
# are unaffected. In particular, do not classify every polite "can you" as noise.
QUESTION = re.compile(
    r"^(?:(?:ari|ари)[,.]?\s+)?(?:"
    r"what|where|when|who|whose|which|why|"
    r"how\s+(?:much|many|do|does|did|is|are|can|should)|"
    r"што|каде|кога|кој|која|кое|кои|зошто|колку|дали|"
    r"како\s+(?:да|се|си|е|можам|можеш)|"
    r"sto|shto|kade|koga|koj|koja|koe|koi|zoshto|zosto|kolku|dali|"
    r"kako\s+(?:da|se|si|e|mozam|mozesh|mozes))\b", re.IGNORECASE)

_PROMPT = """You maintain a personal assistant's long-term memory. Reply with exactly one label and nothing else. Do not explain.
APPEND - worth remembering, and it adds something the stored notes do not already have
SUPERSEDE - it contradicts a stored note: the same thing about the same person is now different
COEXIST - it differs from a stored note but both stay true, because they apply in different circumstances
ABORT - nothing here would be useful to recall later: an instruction to do something right now, chit-chat, transcription noise, or something a stored note already says

A standing rule about how you should behave ("never notify me while I work", "read me the news in Macedonian") IS worth remembering, even though it sounds like an instruction. A one-off command to act now is not.

Judge meaning, not wording. The utterance may be in Macedonian, in English or in both at once; the label is the same in every language, and you must never translate, rewrite or repeat the utterance.

Stored notes:
{context}
Language of the utterance: {lang}
Utterance: {text}
Label:"""

_FEWSHOT = """Examples.
Stored notes: (none)
Utterance: отвори YouTube
Label: ABORT
Stored notes: 1. Сакам кафе наутро.
Utterance: Сакам кафе наутро.
Label: ABORT
Stored notes: 1. Работам на проект што се вика АРИЕС.
Utterance: Мојот мастер е на ФИНКИ.
Label: APPEND
Stored notes: 1. Сакам да работам навечер.
Utterance: Веќе не работам навечер, станувам рано.
Label: SUPERSEDE
Stored notes: 1. Сакам кафе наутро.
Utterance: Навечер пијам чај, не кафе.
Label: COEXIST

"""


def normalise(text):
    """NFC, collapsed whitespace. Nothing else — the words are not ours."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


def detect_language(text):
    """'mk', 'en', 'mixed' or ''. Script counting, not a language model.

    Enough for the one thing it is for: proving afterwards that what was stored
    is in the script it was spoken in.
    """
    cyrillic = sum(1 for c in text if "Ѐ" <= c <= "ӿ")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    if not cyrillic and not latin:
        return ""
    if cyrillic and latin and min(cyrillic, latin) / (cyrillic + latin) > .2:
        return "mixed"
    return "mk" if cyrillic >= latin else "en"


class Verdict:
    """One decision, with everything needed to explain it afterwards."""

    __slots__ = ("action", "stage", "reason", "confidence", "related_to", "similarity", "kind", "lang")

    def __init__(self, action, stage, reason, *, confidence=1., related_to=None,
                 similarity=None, kind="fact", lang=""):
        self.action, self.stage, self.reason = action, stage, reason
        self.confidence, self.related_to, self.similarity = confidence, related_to, similarity
        self.kind, self.lang = kind, lang

    def as_dict(self):
        return {"action": self.action, "stage": self.stage, "reason": self.reason,
                "confidence": round(self.confidence, 4), "related_to": self.related_to,
                "similarity": None if self.similarity is None else round(self.similarity, 4),
                "kind": self.kind, "lang": self.lang}

    def __repr__(self):
        return f"Verdict({self.action} via {self.stage}: {self.reason})"


def gate(text, *, excluded=(), allowed=True):
    """Stage 1. Returns a refusing Verdict, or None to continue.

    This is the enforcement `privacy.excluded_memory_topics` has been owed
    since it was defined, and it sits on the MACHINE write path — the path that
    writes things nobody asked it to write.
    """
    text = normalise(text)
    if not allowed:
        return Verdict("ABORT", "gate", "privacy.remember_conversations is off", confidence=1.)
    if len(text) < MIN_CHARS:
        return Verdict("ABORT", "gate", f"shorter than {MIN_CHARS} characters", confidence=1.)
    if len(text) > MAX_CHARS:
        return Verdict("ABORT", "gate", f"longer than {MAX_CHARS} characters", confidence=1.)
    for topic in excluded:
        if topic and str(topic).casefold() in text.casefold():
            return Verdict("ABORT", "gate", f"matches excluded topic {str(topic)!r}", confidence=1.)
    if SECRETS.search(text):
        return Verdict("ABORT", "gate", "looks like a credential", confidence=1.)
    if COMMAND.match(text):
        return Verdict("ABORT", "gate", "an instruction to act, not a fact to keep", confidence=1.)
    if QUESTION.match(text):
        return Verdict("ABORT", "gate", "an information question, not a stated fact", confidence=1.)
    return None


def classify_kind(text):
    """Which decay constant this memory should age by. Deterministic."""
    low = text.casefold()
    if re.search(r"\b(jas sum|јас сум|i am|i'm|my name|се викам|моето име|живеам|i live)\b", low):
        return "identity"
    if re.search(r"\b(сакам|не сакам|претпочитам|омилен|omilen|sakam|prefer|i like|i hate|i don't like|always|never|секогаш|никогаш)\b", low):
        return "preference"
    if re.search(r"\b(утре|следната|ќе |kje |ke |планирам|tomorrow|next week|i will|i'm going to|plan)\b", low):
        return "plan"
    if re.search(r"\b(вчера|денес|беше|yesterday|today|last night|was|did)\b", low):
        return "episodic"
    return "fact"


class Cascade:
    """The three stages, holding only the thresholds and the model settings."""

    def __init__(self, *, redundant_above=REDUNDANT_ABOVE, novel_below=NOVEL_BELOW,
                 model="qwen2.5:7b", endpoint=OLLAMA, timeout=30, context=4):
        self.redundant_above, self.novel_below = float(redundant_above), float(novel_below)
        self.model, self.endpoint, self.timeout, self.context = model, endpoint, timeout, int(context)
        self.calls = 0                       # how many times stage 3 actually ran

    def novelty(self, neighbours):
        """Stage 2. `neighbours` is [(id, cosine, text)] best-first."""
        if not neighbours:
            return Verdict("APPEND", "novelty", "nothing comparable is stored", similarity=None)
        best_id, best, _ = neighbours[0]
        if best >= self.redundant_above:
            return Verdict("NOOP", "novelty", f"already stored (cosine {best:.3f})",
                           related_to=best_id, similarity=best)
        if best <= self.novel_below:
            return Verdict("APPEND", "novelty", f"unrelated to everything stored (cosine {best:.3f})",
                           related_to=best_id, similarity=best)
        return Verdict("ESCALATE", "novelty", f"uncertain (cosine {best:.3f})",
                       related_to=best_id, similarity=best)

    def decide(self, text, neighbours, *, lang=""):
        """Stage 3. One call, one bare label, a real probability."""
        listed = "\n".join(f"{i}. {t}" for i, (_, _, t) in enumerate(neighbours[:self.context], 1)) or "(none)"
        prompt = _FEWSHOT + _PROMPT.format(context=listed, lang=lang or "unknown", text=text)
        self.calls += 1
        result = calibration.classify(prompt, LABELS, endpoint=self.endpoint,
                                      model=self.model, timeout=self.timeout)
        related = neighbours[0][0] if neighbours else None
        similarity = neighbours[0][1] if neighbours else None
        return Verdict(result["label"], "model",
                       f"model chose {result['label']} over {result['runner_up']} "
                       f"(margin {result['margin']:.3f}, emitted {result['emitted']!r})",
                       confidence=result["confidence"], related_to=related, similarity=similarity), result

    def run(self, text, neighbours, *, excluded=(), allowed=True, lang=None):
        """All three stages. Never raises for a missing model — it degrades.

        A model that is not answering must not become a silent 'keep nothing';
        the uncertain band falls back to APPEND with the stage-2 cosine as its
        confidence, and says so in the rationale.
        """
        text = normalise(text)
        lang = lang if lang is not None else detect_language(text)
        kind = classify_kind(text)
        refused = gate(text, excluded=excluded, allowed=allowed)
        if refused is not None:
            refused.kind, refused.lang = kind, lang
            return refused
        verdict = self.novelty(neighbours)
        if verdict.action != "ESCALATE":
            verdict.kind, verdict.lang = kind, lang
            return verdict
        try:
            decided, _ = self.decide(text, neighbours, lang=lang)
        except calibration.ModelUnavailable as exc:
            fallback = Verdict("APPEND", "novelty", f"no local model ({exc}); kept on cosine alone",
                               confidence=1. - verdict.similarity, related_to=verdict.related_to,
                               similarity=verdict.similarity)
            fallback.kind, fallback.lang = kind, lang
            return fallback
        decided.kind, decided.lang = kind, lang
        return decided
