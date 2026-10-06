"""A catalogue of feeds the user can pick from — "where do I want news from?"

The Sources Registry (§24) lets any feed be added, but only if you know its URL.
Nobody knows the URL of a feed. §34 asks that configuring ARIES feel like
configuring an operating system rather than an AI framework, and typing
`https://feeds.bbci.co.uk/news/rss.xml` from memory is the opposite of that.

So: a curated list, grouped by subject, each entry pre-tagged with the topics it
covers so adding it also tells the Interest Profile what it is for.

WHAT IS IN HERE, AND WHY YOU CAN TRUST IT
-----------------------------------------
Every entry below was **fetched and parsed on this machine** before being
included. Two candidates were dropped because they did not work (CISA's advisory
feed returns 403 to an unknown user agent; the NVD RSS URL is dead), and they are
listed in `UNAVAILABLE` rather than silently omitted, so the next person does not
waste time rediscovering them.

This is a suggestion list, not a policy. Nothing here is enabled, and nothing is
special: a catalogue entry becomes an ordinary row in the registry, subject to
exactly the same validation as a URL typed by hand.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CatalogueEntry:
    id: str
    name: str
    url: str
    category: str
    description: str
    topics: tuple[str, ...] = ()
    language: str = "en"
    type: str = "rss"
    suggested_priority: str = "normal"
    suggested_trust: str = "normal"
    note: str = ""
    coverage_topics: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "url": self.url, "category": self.category,
                "description": self.description, "topics": list(self.topics),
                "language": self.language, "type": self.type,
                "suggested_priority": self.suggested_priority,
                "suggested_trust": self.suggested_trust, "note": self.note,
                "coverage_topics": list(self.coverage_topics)}


CATEGORIES = {
    "ai": "AI and machine learning",
    "tech": "Technology news",
    "security": "Security and vulnerabilities",
    "programming": "Programming and languages",
    "science": "Science",
    "world": "World news",
    "balkans": "Balkans and North Macedonia",
    "sports": "Sports",
}

CATALOGUE: tuple[CatalogueEntry, ...] = (
    CatalogueEntry("huggingface", "Hugging Face Blog",
                   "https://huggingface.co/blog/feed.xml", "ai",
                   "Models, datasets, training, inference and open ML research.", ("ai",), coverage_topics=("ai",)),
    CatalogueEntry("managing-madrid", "Managing Madrid",
                   "https://www.managingmadrid.com/rss/index.xml", "sports",
                   "Independent Real Madrid reporting and commentary; not the official club.",
                   ("real madrid",), coverage_topics=("real madrid",)),
    CatalogueEntry("makfax-makedonija", "Макфакс — Македонија",
                   "https://makfax.com.mk/makedonija/feed/", "balkans",
                   "Domestic news from the publisher's Macedonia section.",
                   ("macedonia news", "macedonia"), language="mk",
                   note="Keep article links and attribution; publisher permits noncommercial RSS use.",
                   coverage_topics=("macedonia news",)),
    # ── AI ──────────────────────────────────────────────────────────────────
    CatalogueEntry("arxiv-cs-ai", "arXiv — Artificial Intelligence",
                   "http://export.arxiv.org/rss/cs.AI", "ai",
                   "New AI preprints, the day they are posted. High volume.",
                   ("ai", "agents", "research"), suggested_trust="trusted"),
    CatalogueEntry("arxiv-cs-lg", "arXiv — Machine Learning",
                   "http://export.arxiv.org/rss/cs.LG", "ai",
                   "New machine-learning preprints. High volume.",
                   ("ai", "machine learning", "research"), suggested_trust="trusted",
                   note="arXiv category feeds are empty on days with no new submissions."),
    CatalogueEntry("arxiv-cs-cl", "arXiv — Computation and Language",
                   "http://export.arxiv.org/rss/cs.CL", "ai",
                   "NLP and language-model preprints.",
                   ("ai", "llm", "nlp", "research"), suggested_trust="trusted",
                   note="Empty on days with no new submissions."),
    CatalogueEntry("google-ai", "Google AI blog", "https://blog.google/technology/ai/rss/", "ai",
                   "Announcements and research write-ups from Google.", ("ai", "research")),
    CatalogueEntry("mit-tr-ai", "MIT Technology Review — AI",
                   "https://www.technologyreview.com/topic/artificial-intelligence/feed", "ai",
                   "Reported journalism on AI rather than announcements.", ("ai",)),

    # ── tech ────────────────────────────────────────────────────────────────
    CatalogueEntry("hacker-news", "Hacker News", "https://news.ycombinator.com/rss", "tech",
                   "The front page. Broad, opinionated, often early.",
                   (), suggested_priority="high"),
    CatalogueEntry("ars-technica", "Ars Technica",
                   "https://feeds.arstechnica.com/arstechnica/index", "tech",
                   "Technology reporting with technical depth.", ()),
    CatalogueEntry("the-verge", "The Verge", "https://www.theverge.com/rss/index.xml", "tech",
                   "Consumer technology and industry news.", ()),
    CatalogueEntry("github-blog", "GitHub blog", "https://github.blog/feed/", "tech",
                   "Platform changes, engineering posts, security advisories.",
                   ("programming", "security")),

    # ── security ────────────────────────────────────────────────────────────
    CatalogueEntry("krebs", "Krebs on Security", "https://krebsonsecurity.com/feed/", "security",
                   "Investigative reporting on breaches and cybercrime.",
                   ("security",), suggested_trust="trusted"),
    CatalogueEntry("schneier", "Schneier on Security", "https://www.schneier.com/feed/atom/",
                   "security", "Analysis and commentary on security and privacy.",
                   ("security", "privacy"), suggested_trust="trusted"),

    # ── programming ─────────────────────────────────────────────────────────
    CatalogueEntry("python-insider", "Python Insider",
                   "https://blog.python.org/feeds/posts/default", "programming",
                   "Official Python releases and announcements.",
                   ("python", "programming"), suggested_trust="trusted"),
    CatalogueEntry("rust-blog", "Rust blog", "https://blog.rust-lang.org/feed.xml", "programming",
                   "Official Rust releases and project news.",
                   ("rust", "programming"), suggested_trust="trusted"),
    CatalogueEntry("lwn", "LWN.net", "https://lwn.net/headlines/rss", "programming",
                   "Linux kernel and free-software development.",
                   ("linux", "programming"), suggested_trust="trusted"),

    # ── science ─────────────────────────────────────────────────────────────
    CatalogueEntry("nature", "Nature", "https://www.nature.com/nature.rss", "science",
                   "Research across the sciences.", ("science", "research"),
                   suggested_trust="trusted"),
    CatalogueEntry("phys-org", "Phys.org", "https://phys.org/rss-feed/", "science",
                   "Daily science and research news. High volume.", ("science",)),

    # ── world ───────────────────────────────────────────────────────────────
    CatalogueEntry("bbc-news", "BBC News", "https://feeds.bbci.co.uk/news/rss.xml", "world",
                   "World news.", (), suggested_trust="trusted"),
    CatalogueEntry("al-jazeera", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml",
                   "world", "World news with a different centre of gravity than most.", ()),
    CatalogueEntry("dw", "Deutsche Welle", "https://rss.dw.com/rdf/rss-en-all", "world",
                   "European and world news in English. High volume.", ()),

    # ── Balkans / North Macedonia ───────────────────────────────────────────
    CatalogueEntry("balkan-insight", "Balkan Insight", "https://balkaninsight.com/feed/",
                   "balkans", "Regional reporting across the Balkans, in English.",
                   ("balkans",), suggested_trust="trusted"),
    CatalogueEntry("meta-mk", "Мета.мк", "https://meta.mk/feed/", "balkans",
                   "Independent reporting and fact-checking from North Macedonia.",
                   ("macedonia", "balkans"), language="mk"),
    CatalogueEntry("sloboden-pecat", "Слободен Печат", "https://www.slobodenpecat.mk/feed/",
                   "balkans", "Daily news from North Macedonia.",
                   ("macedonia", "balkans"), language="mk"),
    CatalogueEntry("telma", "Телма", "https://telma.com.mk/feed/", "balkans",
                   "Television news from North Macedonia.",
                   ("macedonia", "balkans"), language="mk"),
)

# Checked and rejected, recorded so nobody re-checks them.
UNAVAILABLE: tuple[tuple[str, str, str], ...] = (
    ("CISA advisories", "https://www.cisa.gov/cybersecurity-advisories/all.xml",
     "HTTP 403 — refuses an unknown user agent"),
    ("NVD recent CVEs", "https://nvd.nist.gov/feeds/xml/cve/misc/nvd-rss.xml",
     "HTTP 404 — the feed has moved or been retired"),
    ("МИА (mia.mk)", "https://mia.mk/feed/",
     "connection times out — it answered on a first check and stopped answering "
     "shortly after, so it is not dependable enough to suggest"),
)

_BY_ID = {e.id: e for e in CATALOGUE}


def get(entry_id: str) -> CatalogueEntry | None:
    return _BY_ID.get(entry_id)


def all_entries(*, category: str | None = None, language: str | None = None,
                search: str | None = None) -> list[CatalogueEntry]:
    out = list(CATALOGUE)
    if category:
        out = [e for e in out if e.category == category]
    if language:
        out = [e for e in out if e.language == language]
    if search:
        q = search.strip().lower()
        out = [e for e in out
               if q in e.name.lower() or q in e.description.lower()
               or any(q in t for t in e.topics)]
    return out


def categories() -> list[dict]:
    return [{"id": c, "title": CATEGORIES[c],
             "count": sum(1 for e in CATALOGUE if e.category == c)}
            for c in CATEGORIES]
