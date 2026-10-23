"""Versioned selection of experience and of memory.

THREE VERSIONS, ONE SCHEME
--------------------------
`overlap-v1` and `focused-v2` already existed and are unchanged in behaviour.
`semantic-v3` joins them rather than arriving as a parallel mechanism, so the
same `learning_eval.paired_statistics` comparison, the same
`workspace.review_retrieval` switch and the same rollback path apply to it.

WHY EXACT WORD MATCHING WAS BROKEN
----------------------------------
Both older versions compare whole words. Macedonian is inflected: `сакам`,
`сакаше` and `сакав` are the same verb and share no exact form, so a user who
says "сакам кафе" and later asks "што сакав" retrieves nothing. The bug was not
that the threshold was wrong; it is that `w == w` is the wrong predicate for
this language. `stem()` below is the lexical repair — conservative,
suffix-stripping, tested — and `semantic-v3` is the real answer, since it never
compares strings at all.

SCORING, per Park et al. (arXiv:2304.03442)
-------------------------------------------
    w_sim·similarity + w_recency·decay + w_importance·importance + w_layer·layer

with two departures, both deliberate and both visible in the numbers:

  * the decay constant is PER KIND (`models.HALF_LIFE_HOURS`) — one constant
    cannot be right for "I am doing a master's" and for "open YouTube";
  * `importance` is a fixed prior per kind and 1.0 for anything the user asked
    for explicitly. Park scores importance with an LLM call per memory; that is
    one model call per turn for a number nobody can audit.

`layer` is where the two tables meet, and the only place they do: at equal
similarity a USER utterance (60) outranks a LEARNED conclusion (30), so what
ARIES inferred can inform an answer but never outrank what the user said.
"""
import math
import re
import unicodedata
from datetime import datetime

VERSIONS = ('overlap-v1', 'focused-v2', 'semantic-v3')
_GENERIC = set('build create run make again new task please show open find read report final page title the and for with from this that a an to in of my your aries do use list installed http https www com org net io docs document documentation napravi otvori prikazi proveri zadaca sakam napravi mi za da so vo na se sto ова тоа отвори направи прикажи задача провери сакам'.split())

# Park et al. weight all four terms equally; these are spread so that similarity
# still dominates and the rest break ties, which is what "relevant, and recent,
# and mine" means in practice.
W_SIM, W_RECENCY, W_IMPORTANCE, W_LAYER = 1., .5, .3, .4
MAX_LAYER = 80.                       # Layer.SECURITY — the scale, not a member


def focused_words(text):
    terms = set(re.findall(r'\w+', text.casefold())) - _GENERIC
    # A small English normalization, not translation or semantic embeddings.
    return {w[:-1] if len(w)>4 and w.endswith('s') and not w.endswith('ss') else w
            for w in terms if len(w)>2}


# ── the inflection repair ────────────────────────────────────────────────────
# Verb personal endings collapse onto the theme vowel: сакам/сакаш/сакаше/
# сакав/сакале/сакаат -> сака. The theme vowel is KEPT, because dropping it
# too ('сак') collides with unrelated roots.
_MK_VERB = re.compile(r'([аеиоу])(вме|вте|ше|ме|те|ле|ла|ло|ат|ам|аш|ав|ал|м|ш|в|л|а)$')
_EN_SUFFIX = ('ings', 'ing', 'ies', 'es', 'ed', 's', 'y')
_MIN_STEM = 4


def stem(word):
    """Fold one word to a form its other inflections also fold to.

    Macedonian marks case, gender, number, tense, person AND definiteness with
    suffixes, and stacks them: `работа` / `работата` / `работите`. A rule per
    suffix does not converge — whichever order they fire in, some pair of forms
    of one lemma ends up with different stems, which is the bug this replaces.
    So: normalise the verb ending onto its theme vowel (which is the one case a
    truncation gets wrong, `сакам` being shorter than `сакаше`), then truncate
    to four characters.

    Four-character truncation is CRUDE, and it is recorded as crude: it folds
    `проект` and `проекција` together. It is the lexical fallback. The actual
    answer to an inflected language is `semantic-v3`, which compares meanings
    and never looks at a suffix — and the experiment in `experiments/iis/memory/`
    exists to show by how much.

    Latin script keeps the earlier English suffix rules; truncating English to
    four characters would merge `programming` with `progress` for no gain,
    because English barely inflects.
    """
    w = unicodedata.normalize('NFC', word).casefold()
    if any('Ѐ' <= c <= 'ӿ' for c in w):
        changed = _MK_VERB.sub(r'\1', w)
        if len(changed) >= _MIN_STEM:
            w = changed
        return w[:_MIN_STEM]
    for suffix in _EN_SUFFIX:
        if w.endswith(suffix) and len(w) - len(suffix) >= _MIN_STEM:
            return w[:-len(suffix)]
    return w


def stems(text):
    """Content stems of a request, with the generic command vocabulary removed."""
    return {stem(w) for w in re.findall(r'\w+', unicodedata.normalize('NFC', text).casefold())
            if w not in _GENERIC and len(w) > 2} - {stem(g) for g in _GENERIC}


def lexical_similarity(request_stems, text):
    """Jaccard over stems. The fallback when nothing can be embedded."""
    other = stems(text)
    if not request_stems or not other:
        return 0.
    return len(request_stems & other) / len(request_stems | other)


def rank(rows, request, version):
    """Select at most three reviewed episodes. Side-effect free."""
    if version not in VERSIONS:
        raise ValueError('Unknown review retrieval version')
    if version == 'semantic-v3':
        selected = _semantic_rank(rows, request)
        if selected is not None:
            return selected
        version = 'focused-v2'          # no embedder on this machine; degrade, do not guess
    from aries.workspace.reviews import words
    tokenizer = words if version == 'overlap-v1' else focused_words
    terms = tokenizer(request)
    if not terms:
        return []
    scored = []
    documents = [tokenizer(r['episode']['request']) for r in rows]
    for row, document in zip(rows, documents):
        overlap = terms & document
        if version == 'overlap-v1':
            accepted = len(overlap) >= min(2, len(terms))
            score = len(overlap)
        else:
            # Generic commands alone never retrieve experience. A one-word
            # topic must identify one record, rather than three arbitrary ones.
            unique = len(terms)==1 and sum(bool(terms & d) for d in documents)==1
            accepted = bool(overlap) and (unique or len(overlap)>=2) and len(overlap)/len(terms)>=0.5
            score = (len(overlap)/len(terms), len(overlap)/max(1,len(terms | document)))
        if accepted:
            scored.append((score, row))
    scored.sort(key=lambda item:item[0], reverse=True)
    return [r for _,r in scored[:3]]


# The accept floor for semantic review selection, on the rescaled similarity of
# `_rescale` — not on raw cosine, which for e5 never approaches zero.
SEMANTIC_ACCEPT = .5


def semantic_available():
    """Whether `semantic-v3` can actually run here, rather than degrade.

    A comparison that silently measured focused-v2 twice and labelled one of
    them semantic-v3 would be worse than no comparison.
    """
    from aries.workspace.memory import embedding
    return embedding.available()


def _semantic_rank(rows, request):
    """`rank` for semantic-v3, or None when no embedder is installed."""
    from aries.workspace.memory import embedding
    if not rows:
        return []
    try:
        embedder = embedding.get()
    except Exception:                                   # noqa: BLE001
        return None
    texts = [r['episode']['request'] for r in rows]
    similarity = embedder.passages(texts) @ embedder.query(request)
    scaled = _rescale(similarity.tolist())
    chosen = sorted(((s, r) for s, r in zip(scaled, rows) if s >= SEMANTIC_ACCEPT),
                    key=lambda item: -item[0])[:3]
    return [r for _, r in chosen]


def _rescale(values):
    """Min-max a similarity column onto [0, 1].

    e5 puts every pair of short sentences between about 0.78 and 0.95, so an
    absolute threshold on raw cosine is both meaningless and specific to one
    model. Rescaling against the candidates actually present makes the weight
    `W_SIM` mean the same thing for e5, for bge-m3 and for Jaccard.
    """
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-9:
        return [1. if high > 0 else 0.] * len(values)
    return [(v - low) / (high - low) for v in values]


def decay(row, now):
    """Exponential forgetting with a half-life chosen by the memory's kind.

    The clock starts at the LAST RETRIEVAL, not at creation: a memory that keeps
    being useful is a memory that is still current, and that is the one signal
    of continued relevance that costs nothing to collect.
    """
    from aries.workspace.models import HALF_LIFE_HOURS
    last = row.get('last_retrieved_at') or row.get('created_at')
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    if last is None:
        return 1.
    hours = max(0., (now - last).total_seconds() / 3600.)
    return math.pow(.5, hours / HALF_LIFE_HOURS.get(row.get('kind') or 'fact', 24 * 365.))


# ── ARIES_MEMORY_HYBRID_RRF ─────────────────────────────────────────────────────
# LoCoMo (experiments/iis/real-data/locomo): plain BM25 found the evidence in the top 5 for
# 50.0% of 1,982 questions, ARIES semantic-v3 with e5 for 37.7%, and the two missed
# different questions (e5 was better on multi-hop by +0.106). Reciprocal Rank Fusion
# (Cormack, Clarke and Buettcher, SIGIR 2009) combines the two rankings without tuning a
# weight between incomparable scores: each row gets sum 1/(RRF_K + rank) over the BM25
# and the cosine ranking. The fused score replaces the similarity term; recency,
# importance and layer are added as before.
RRF_K = 60
BM25_K1, BM25_B = 1.2, .75
_TOKEN = re.compile(r'\w+')


def bm25_scores(request, texts, k1=BM25_K1, b=BM25_B):
    """Okapi BM25 of `request` against each text (casefolded \\w+ tokens, no stemming)."""
    docs = [_TOKEN.findall(t.casefold()) for t in texts]
    if not docs:
        return []
    avgdl = (sum(map(len, docs)) / len(docs)) or 1.
    df = {}
    for d in docs:
        for w in set(d):
            df[w] = df.get(w, 0) + 1
    n, terms = len(docs), _TOKEN.findall(request.casefold())
    out = []
    for d in docs:
        tf = {}
        for w in d:
            tf[w] = tf.get(w, 0) + 1
        score = 0.
        for w in terms:
            f = tf.get(w)
            if f:
                idf = math.log(1 + (n - df[w] + .5) / (df[w] + .5))
                score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(d) / avgdl))
        out.append(score)
    return out


def rrf(*score_lists, k=RRF_K):
    """Reciprocal Rank Fusion of several score lists over the same items (higher score = better rank).

    An item with score 0 in a lexical list is unranked there (BM25 found none of its words)."""
    fused = [0.] * len(score_lists[0][0])
    for scores, lexical in score_lists:
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
        for rank, i in enumerate(order, 1):
            if lexical and scores[i] <= 0:
                continue
            fused[i] += 1. / (k + rank)
    return fused


def _flag(name):
    from aries import flags
    return flags.enabled(name)


def hybrid_enabled(version):
    return version == 'semantic-v3' and _flag('ARIES_MEMORY_HYBRID_RRF')


# ── ARIES_MEMORY_SIMILARITY_RANK ────────────────────────────────────────────────
# M1 on LoCoMo (experiments/iis/real-data/locomo/results/locomo-20261022T193500Z.json): with
# the recency, importance and layer terms removed, the same e5 rows reach hit@5 0.603
# (cosine) and 0.621 (fused with BM25), against 0.377 with them. In conversations that last
# months, a 72-hour half-life pushes every early session down whatever its relevance. With
# the flag the similarity term decides the order and the other terms only break ties.
TIE_BREAK = 1e-3


def score_memories(rows, request, version, *, now=None, query_vector=None, limit=8):
    """Rank memories and conclusions together. Returns [(score, row, parts)].

    `rows` carry `text`, `kind`, `layer`, `importance`, `created_at`,
    `last_retrieved_at` and, for semantic-v3, `vector`. Nothing here writes;
    refreshing recency is `store.touch`, which the caller does with the ids it
    actually used.
    """
    if version not in VERSIONS:
        raise ValueError('Unknown memory retrieval version')
    now = now or datetime.utcnow()
    if not rows:
        return []
    if version == 'semantic-v3':
        vectors = [r.get('vector') for r in rows]
        if query_vector is None or any(v is None for v in vectors):
            version = 'focused-v2'        # unembedded rows would score 0 and vanish
        else:
            cosine = [float(v @ query_vector) for v in vectors]
            if hybrid_enabled(version):
                lexical = bm25_scores(request, [r['text'] for r in rows])
                similarity = _rescale(rrf((cosine, False), (lexical, True)))
            else:
                similarity = _rescale(cosine)
    if version != 'semantic-v3':
        terms = stems(request)
        # A request of nothing but generic command words carries no topic, so
        # every memory is equally (ir)relevant and the other three terms decide.
        similarity = _rescale([lexical_similarity(terms, r['text']) for r in rows]) if terms else [0.] * len(rows)

    similarity_rank = version == 'semantic-v3' and _flag('ARIES_MEMORY_SIMILARITY_RANK')
    scored = []
    for row, sim in zip(rows, similarity):
        parts = {'similarity': sim, 'recency': decay(row, now),
                 'importance': float(row.get('importance') or 0.),
                 'layer': float(row.get('layer') or 0) / MAX_LAYER}
        total = (W_SIM * parts['similarity'] + W_RECENCY * parts['recency']
                 + W_IMPORTANCE * parts['importance'] + W_LAYER * parts['layer'])
        if similarity_rank:
            # ARIES_MEMORY_SIMILARITY_RANK: similarity decides; the other three only break ties.
            total = parts['similarity'] + TIE_BREAK * (W_RECENCY * parts['recency'] + W_IMPORTANCE * parts['importance']
                                                       + W_LAYER * parts['layer'])
        scored.append((total, row, parts))
    scored.sort(key=lambda item: -item[0])
    return scored[:limit]
