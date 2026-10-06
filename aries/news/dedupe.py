"""Recognising that two items are the same story — §13/03's cluster step.

The same event reaches ARIES several times: the same feed polled twice, a story
syndicated across outlets, a publisher emitting a corrected copy an hour later.
Telling the user three times is how a news feature becomes noise, so items are
grouped into clusters and only a cluster's representative is ever delivered.

TWO KINDS OF SAMENESS, AND ONLY ONE IS EXACT
--------------------------------------------
  * IDENTITY. The same link, or the same feed-supplied guid, is the same item.
    Cheap, certain, and handles the ordinary case of re-polling a feed.
  * SIMILARITY. Different outlets write different headlines about one event:
    "OpenAI releases GPT-5" and "GPT-5 released by OpenAI today". No exact key
    matches, and they are the same story.

For similarity, titles are reduced to a set of significant words and compared by
JACCARD SIMILARITY — the size of the intersection over the size of the union.
Two headlines sharing most of their meaningful words are the same story; sharing
a few common ones is not enough.

CONCEPT — why a word SET and not a sequence. Word order carries little
information in a headline and varies freely between outlets, while the
vocabulary barely changes. Comparing sets makes the measure indifferent to
ordering, which is exactly the invariance wanted here. It is also cheap: sets and
one intersection, no alignment or edit distance.

Stopwords are removed first, or every pair of headlines would share "the", "a",
"to" and score as vaguely similar. Very short titles are compared more strictly,
since with three words left a single shared word is a large fraction of the union.

This is deliberately not clever. It is deterministic, explainable, and works
offline — the same reasoning as the health judge and the interest matcher. A
semantic model would catch more, and could not tell the user why two things were
merged.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from aries.interests.matching import normalise
from aries.news.models import fingerprint

# Words carrying no topical information. Kept short on purpose: an aggressive
# list starts removing words that distinguish stories ("new", "first", "report").
STOPWORDS = frozenset("""
a an the and or but if then than that this these those of in on at to for from by with
is are was were be been being has have had do does did will would can could should may
says say said new after before over under as it its their his her
today yesterday tomorrow
""".split())

_WORD = re.compile(r"[a-z0-9][a-z0-9'+.-]*")


def stem(word: str) -> str:
    """A deliberately timid suffix strip, used ONLY for duplicate detection.

    The Interest Profile refuses stemming outright (see aries/interests/
    matching.py), and this module does it anyway. The two are not inconsistent —
    the trade-off genuinely points the other way:

      * In INTERESTS, a wrong stem widens a topic invisibly. The user asked to
        follow one thing and quietly starts receiving another, with no signal
        that anything is wrong. The cost lands on every future item.
      * In DEDUPLICATION, headlines about one event differ in tense as a matter
        of routine — "OpenAI releases GPT-5" against "GPT-5 released by OpenAI".
        Without stemming those score 0.40 and are shown twice. A wrong merge
        costs the user one story, once, and the cluster records what it merged
        and why, so it is visible.

    The same decision, made twice, with opposite answers, because the failure
    modes are not symmetric. The rules below stay conservative: only the endings
    that are almost always inflection, and only on words long enough that the
    stem is still a word.
    """
    w = word
    if w.endswith("'s"):
        w = w[:-2]
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 5 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 4 and w.endswith("es"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def significant(text: str) -> set[str]:
    """The words of a title that carry its meaning, stemmed for comparison."""
    return {stem(w) for w in _WORD.findall(normalise(text))
            if len(w) > 2 and w not in STOPWORDS}


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of two titles' significant words, in [0, 1]."""
    sa, sb = significant(a), significant(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


@dataclass
class Candidate:
    """An item offered for clustering."""

    item_id: str
    title: str
    link: str = ""
    guid: str = ""
    source_id: str = ""
    weight: float = 0.0        # how strongly this source should represent a story
    extra: dict = field(default_factory=dict)


@dataclass
class Cluster:
    cluster_id: str
    representative: Candidate
    members: list[Candidate] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.members)

    def as_dict(self) -> dict:
        return {"cluster_id": self.cluster_id, "representative": self.representative.item_id,
                "size": self.size, "members": [m.item_id for m in self.members],
                "sources": sorted({m.source_id for m in self.members}),
                "reasons": self.reasons}


def _identity_keys(c: Candidate) -> set[str]:
    keys = set()
    if c.link:
        # Strip tracking parameters and fragments, or the same article shared
        # with a campaign tag looks like a different one.
        cleaned = re.sub(r"[?#].*$", "", c.link.strip().lower().rstrip("/"))
        if cleaned:
            keys.add("link:" + cleaned)
    if c.guid:
        keys.add("guid:" + c.guid.strip().lower())
    return keys


def cluster(candidates: list[Candidate], *, threshold: float = 0.6,
            short_title_threshold: float = 0.8) -> list[Cluster]:
    """Group items telling the same story.

    Candidates are processed in the order given; the caller sorts so that the
    preferred representative comes first (higher-priority, more trusted sources).
    The first member of a cluster is its representative.
    """
    clusters: list[Cluster] = []
    seen_keys: dict[str, Cluster] = {}

    for cand in candidates:
        keys = _identity_keys(cand)
        hit = next((seen_keys[k] for k in keys if k in seen_keys), None)
        reason = "same link or guid"

        if hit is None:
            words = significant(cand.title)
            limit = short_title_threshold if len(words) <= 4 else threshold
            best, best_score = None, 0.0
            for cl in clusters:
                score = similarity(cand.title, cl.representative.title)
                if score > best_score:
                    best, best_score = cl, score
            if best is not None and best_score >= limit:
                hit, reason = best, f"titles {best_score:.0%} similar"

        if hit is None:
            cl = Cluster(cluster_id=fingerprint(cand.item_id), representative=cand, members=[cand])
            clusters.append(cl)
            for k in keys:
                seen_keys[k] = cl
        else:
            hit.members.append(cand)
            hit.reasons.append(f"{cand.item_id}: {reason}")
            for k in keys:
                seen_keys.setdefault(k, hit)

    return clusters
