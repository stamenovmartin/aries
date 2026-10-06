"""Deciding whether a piece of text is about something the user cares about.

Deterministic, no model. Same reasoning as the health judge: this runs on every
item from every source, it must work with the network down, and — most
importantly — it must be able to explain itself. §25 requires the user be able
to inspect and override what ARIES concluded about their interests, and "the
model thought so" is not something anyone can inspect.

THE SUBSTRING TRAP
------------------
The obvious implementation is `if topic in text`. It is wrong, and quietly so.
The user's topic "ai" would match:

    s-ai-d   ·   em-ai-l   ·   camp-ai-gn   ·   Ukr-ai-ne   ·   ag-ai-nst

An interest profile built on substring matching declares almost everything
relevant, the user sees noise, and the failure looks like bad ranking rather
than a broken matcher. So every term is matched on WORD BOUNDARIES, and
multi-word terms are matched as phrases with flexible whitespace.

SYNONYMS
--------
Entry 005 left topic matching as exact strings, so "ai" and "artificial
intelligence" were different topics and an article tagged with one was invisible
to a user who asked for the other. Synonyms live here rather than in the Sources
Registry because they are a fact about what the USER MEANS, not about where
information comes from — the same reason §25 puts them in the interest profile.

SCORING — noisy-OR, not a sum
-----------------------------
When several interests match, their evidence combines as

    score = 1 - ∏ (1 - weight_i)

rather than as a sum. Three reasons, and the third is the one that matters:

  * a sum needs an arbitrary cap to stay in [0, 1], and the cap decides the
    answer more than the weights do;
  * noisy-OR saturates naturally — two strong matches are more convincing than
    one, five are barely more convincing than four, which is how evidence
    actually behaves;
  * it is monotonic and explainable. Every match can only raise the score, and
    each one's contribution can be shown to the user as its own number.

It reads as "the chance that at least one of these interests is genuinely the
subject", which is exactly the question being asked.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


# Decimal places kept in a relevance score. Far finer than any threshold a user
# would set, and coarse enough to absorb binary floating-point error.
ROUNDING = 9


def normalise(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace.

    Accent folding means "Björk" and "Bjork", "café" and "cafe" are one term —
    a user typing a topic without accents should still match the accented form.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped.lower()).strip()


# A term becomes a compiled regular expression. `re.escape` removes any ReDoS
# risk from metacharacters, but nothing bounded LENGTH — and a 100,000-character
# synonym is CPU and memory spent on every item scored, forever. Bounded here as
# well as at the HTTP edge, because the CLI and in-process callers do not pass
# through the edge.
MAX_TERM_CHARS = 120


def term_pattern(term: str) -> re.Pattern | None:
    """A word-boundary regex for one term. Multi-word terms match as phrases.

    `\\b` on each end is what stops "ai" matching "said". For a phrase, the
    internal whitespace becomes `\\s+` so "llm  agents" and "llm\\nagents" match
    the term "llm agents" — text from a feed has unpredictable whitespace.
    """
    t = normalise(term)[:MAX_TERM_CHARS]
    if not t:
        return None
    words = [re.escape(w) for w in t.split(" ")]
    body = r"\s+".join(words)
    # A term that starts or ends with a non-word character (C++, .NET) cannot
    # carry a word boundary there — \b would never match.
    left = r"\b" if re.match(r"\w", t[0]) else ""
    right = r"\b" if re.search(r"\w$", t) else ""
    try:
        return re.compile(left + body + right)
    except re.error:
        return None


@dataclass
class Term:
    """One way of saying a topic.

    Normalisation and the length bound are applied HERE, so `text` and `pattern`
    can never disagree. Truncating only inside `term_pattern` left the stored
    text at its original length while the compiled pattern matched the first
    120 characters — a divergence that would have shown up as an explanation
    naming a term that is not what actually matched.
    """

    text: str
    pattern: re.Pattern | None = None

    def __post_init__(self):
        self.text = normalise(self.text)[:MAX_TERM_CHARS]
        if self.pattern is None:
            self.pattern = term_pattern(self.text)

    def find(self, haystack: str) -> int:
        """How many times this term occurs. 0 when it does not."""
        return len(self.pattern.findall(haystack)) if self.pattern else 0


@dataclass
class Matchable:
    """An interest reduced to what matching needs: its terms, weight and stance."""

    key: str                       # the canonical topic
    terms: list[Term]
    weight: float                  # 0..1
    avoid: bool = False
    source: str = "user"           # "user" | "learned" — for the explanation

    @classmethod
    def build(cls, key: str, synonyms: list[str], weight: float, *, avoid: bool = False,
              source: str = "user") -> "Matchable":
        seen, terms = set(), []
        for raw in [key, *(synonyms or [])]:
            n = normalise(raw)
            if n and n not in seen:
                seen.add(n)
                terms.append(Term(n))
        return cls(key=key, terms=terms, weight=weight, avoid=avoid, source=source)

    def hits(self, haystack: str) -> list[dict]:
        out = []
        for t in self.terms:
            n = t.find(haystack)
            if n:
                out.append({"term": t.text, "occurrences": n})
        return out


@dataclass
class Relevance:
    """A scored judgement, with its reasoning attached."""

    score: float
    matched: list[dict] = field(default_factory=list)
    excluded_by: dict | None = None
    explanation: str = ""

    @property
    def excluded(self) -> bool:
        return self.excluded_by is not None

    def as_dict(self) -> dict:
        return {"score": round(self.score, 3), "matched": self.matched,
                "excluded_by": self.excluded_by, "excluded": self.excluded,
                "explanation": self.explanation}


def score(text: str, interests: list[Matchable]) -> Relevance:
    """How relevant is this text, and why?

    An AVOID interest disqualifies outright rather than subtracting. §25 lists
    "topics I do not care about" as its own category, and the user means "not
    this", not "this, but less" — a strong enough positive score should never be
    able to outvote an explicit exclusion.
    """
    hay = normalise(text)
    if not hay:
        return Relevance(0.0, explanation="nothing to match against")

    for m in interests:
        if not m.avoid:
            continue
        hits = m.hits(hay)
        if hits:
            return Relevance(
                0.0, excluded_by={"topic": m.key, "hits": hits, "source": m.source},
                explanation=f"excluded: '{m.key}' is on the list of topics to ignore "
                            f"(matched {hits[0]['term']!r})")

    matched, inverse = [], 1.0
    for m in interests:
        if m.avoid:
            continue
        hits = m.hits(hay)
        if not hits:
            continue
        w = max(0.0, min(1.0, m.weight))
        matched.append({"topic": m.key, "weight": round(w, 3), "source": m.source, "hits": hits})
        inverse *= (1.0 - w)

    if not matched:
        return Relevance(0.0, explanation="no topic of interest appears in it")

    matched.sort(key=lambda x: -x["weight"])
    # Rounded, and not merely for tidiness. In binary floating point
    # `1 - (1 - 0.2)` is 0.19999999999999996, so a single topic weighted 0.2
    # would score just under 0.2 — and a threshold test written as
    # `score >= 0.2` would fail for the one weight it was obviously meant to
    # pass. The artifact bites 0.2 and 0.01 but not 0.6 or 0.9, which is the
    # worst kind: it looks like a flaky threshold rather than a rounding error.
    # Rounding here makes "one match scores exactly its weight" true.
    total = round(1.0 - inverse, ROUNDING)
    names = ", ".join(f"{x['topic']} ({x['weight']:.2f})" for x in matched[:4])
    return Relevance(total, matched=matched,
                     explanation=f"matches {len(matched)} topic(s): {names}")
