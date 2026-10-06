"""Parsing RSS and Atom, from bytes an attacker controls.

NO NEW DEPENDENCY
-----------------
`feedparser` is the obvious choice and was not taken. §3 asks that every
dependency be justified on purpose, maintenance, architecture fit and security
rather than adopted for popularity. RSS and Atom are small, stable XML formats;
the parsing below is about 150 lines against Python's standard library, and it
means one fewer package parsing hostile input in this process. If ARIES later
needs the long tail of malformed real-world feeds that feedparser handles, that
is the moment to reconsider — with a reason.

WHY DTDs ARE REFUSED OUTRIGHT
-----------------------------
Verified on this machine rather than assumed, because the answer is not what the
usual advice implies:

    billion laughs  -> EXPANDED (vulnerable)
    XXE             -> refused: "undefined entity &x;"

So `xml.etree.ElementTree` is safe against external entity expansion — it will
not read `/etc/passwd` — but it *will* expand nested internal entities, which is
the billion-laughs denial of service: a few hundred bytes of XML expanding to
gigabytes of memory.

The fix is not a size cap on the input (the expansion happens after) but to
refuse the construct entirely. No legitimate RSS or Atom feed needs a DOCTYPE,
so any document containing one is rejected before parsing begins. That is a
smaller, more honest rule than trying to bound expansion.

EVERYTHING IS TEXT
------------------
Every field is treated as text and never as markup. Titles routinely contain
HTML; it is stripped, not rendered, not stored as markup, and never given to
anything that interprets it. The content of a feed is attacker-controlled data
and stays data.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# Namespaces real feeds use.
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rss1": "http://purl.org/rss/1.0/",
}

_DOCTYPE = re.compile(rb"<!DOCTYPE", re.I)
# The first element start-tag. Everything before it is the XML prolog, and a
# DOCTYPE is only a DOCTYPE there.
_FIRST_ELEMENT = re.compile(rb"<[A-Za-z]")
_TAG = re.compile(r"<[^>]{0,2000}>")
_WS = re.compile(r"\s+")


class FeedError(ValueError):
    """A document that is not a feed ARIES will parse."""


@dataclass
class FeedItem:
    """One entry, reduced to what ARIES uses."""

    title: str
    link: str = ""
    summary: str = ""
    published: datetime | None = None
    author: str = ""
    guid: str = ""
    categories: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Title and summary together — what relevance is scored against."""
        return f"{self.title}. {self.summary}".strip()

    def as_dict(self) -> dict:
        return {"title": self.title, "link": self.link, "summary": self.summary,
                "published": self.published.isoformat() if self.published else None,
                "author": self.author, "guid": self.guid, "categories": self.categories}


@dataclass
class Feed:
    title: str = ""
    link: str = ""
    description: str = ""
    items: list[FeedItem] = field(default_factory=list)
    kind: str = ""                 # rss | atom | rdf


def clean(raw: str | None, *, limit: int = 2000) -> str:
    """Strip markup and entities, collapse whitespace, bound the length.

    Order matters: tags are removed first, THEN entities are unescaped. Doing it
    the other way lets `&lt;script&gt;` become a real tag after the stripper has
    already run.
    """
    if not raw:
        return ""
    text = _TAG.sub(" ", raw)
    text = html.unescape(text)
    text = _TAG.sub(" ", text)          # a second pass: unescaping can reveal markup
    return _WS.sub(" ", text).strip()[:limit]


def _when(raw: str | None) -> datetime | None:
    """Parse the several date formats feeds actually use. Never guess `now` —
    an item with an unreadable date has an unknown date, which is different."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    try:                                  # RFC 822 (RSS)
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
        except ValueError:
            continue
    return None


def _text(node, *paths: str) -> str:
    for p in paths:
        found = node.find(p, NS) if not p.startswith(".//") else node.find(p, NS)
        if found is not None:
            if found.text and found.text.strip():
                return found.text
            href = found.get("href")
            if href:
                return href
    return ""


def parse(data: bytes | str, *, max_items: int = 200) -> Feed:
    """Parse RSS 2.0, RSS 1.0 (RDF) or Atom. Raises FeedError on anything else."""
    raw = data.encode("utf-8", errors="replace") if isinstance(data, str) else data
    if not raw or not raw.strip():
        raise FeedError("empty document")
    # Before parsing, not after: the expansion happens inside the parser.
    #
    # Only the PROLOG is searched — everything before the first element start-tag.
    # A DOCTYPE is a declaration, and a declaration is only meaningful there; once
    # <rss> or <feed> has opened, the same characters are content. Scanning a flat
    # window instead refused github.blog's perfectly valid feed, because one of its
    # articles quotes `<!DOCTYPE html PUBLIC ...>` in escaped post content. A
    # security check that rejects legitimate input gets turned off, so its
    # precision is a security property too.
    first_element = _FIRST_ELEMENT.search(raw)
    prolog = raw[:first_element.start()] if first_element else raw[:8192]
    if _DOCTYPE.search(prolog):
        raise FeedError("document declares a DOCTYPE in its prolog — refused (entity expansion "
                        "risk); no legitimate RSS or Atom feed needs one")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise FeedError(f"not well-formed XML: {e}") from None

    tag = root.tag.split("}")[-1].lower()
    if tag == "rss":
        return _rss(root, max_items)
    if tag == "feed":
        return _atom(root, max_items)
    if tag == "rdf":
        return _rdf(root, max_items)
    raise FeedError(f"root element <{tag}> is not a feed")


def _rss(root, max_items: int) -> Feed:
    channel = root.find("channel")
    if channel is None:
        raise FeedError("RSS document has no <channel>")
    feed = Feed(title=clean(_text(channel, "title"), limit=300),
                link=clean(_text(channel, "link"), limit=500),
                description=clean(_text(channel, "description"), limit=1000), kind="rss")
    for node in channel.findall("item")[:max_items]:
        title = clean(_text(node, "title"), limit=400)
        summary = clean(_text(node, "description", "content:encoded"))
        if not title and not summary:
            continue
        feed.items.append(FeedItem(
            title=title or summary[:120], link=clean(_text(node, "link"), limit=1000),
            summary=summary, published=_when(_text(node, "pubDate", "dc:date")),
            author=clean(_text(node, "author", "dc:creator"), limit=200),
            guid=clean(_text(node, "guid"), limit=500),
            categories=[clean(c.text, limit=80) for c in node.findall("category") if c.text]))
    return feed


def _atom(root, max_items: int) -> Feed:
    feed = Feed(title=clean(_text(root, "atom:title"), limit=300),
                link=clean(_text(root, "atom:link"), limit=500),
                description=clean(_text(root, "atom:subtitle"), limit=1000), kind="atom")
    for node in root.findall("atom:entry", NS)[:max_items]:
        title = clean(_text(node, "atom:title"), limit=400)
        summary = clean(_text(node, "atom:summary", "atom:content"))
        if not title and not summary:
            continue
        link = ""
        for ln in node.findall("atom:link", NS):
            rel = ln.get("rel", "alternate")
            if rel == "alternate" or not link:
                link = ln.get("href", "")
            if rel == "alternate":
                break
        feed.items.append(FeedItem(
            title=title or summary[:120], link=clean(link, limit=1000), summary=summary,
            published=_when(_text(node, "atom:published", "atom:updated")),
            author=clean(_text(node, "atom:author/atom:name"), limit=200),
            guid=clean(_text(node, "atom:id"), limit=500),
            categories=[c.get("term", "") for c in node.findall("atom:category", NS) if c.get("term")]))
    return feed


def _rdf(root, max_items: int) -> Feed:
    channel = root.find("rss1:channel", NS)
    feed = Feed(title=clean(_text(channel, "rss1:title") if channel is not None else "", limit=300),
                kind="rdf")
    for node in root.findall("rss1:item", NS)[:max_items]:
        title = clean(_text(node, "rss1:title"), limit=400)
        summary = clean(_text(node, "rss1:description"))
        if not title and not summary:
            continue
        feed.items.append(FeedItem(
            title=title or summary[:120], link=clean(_text(node, "rss1:link"), limit=1000),
            summary=summary, published=_when(_text(node, "dc:date")),
            author=clean(_text(node, "dc:creator"), limit=200)))
    return feed
