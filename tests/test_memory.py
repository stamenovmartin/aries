"""Semantic memory: the layer rule, the four timestamps, and the cached matrix.

The rules checked here are structural, not behavioural, and that is deliberate.
Whether the local model labels one sentence well is measured in
`experiments/memory/`, against a baseline, with statistics. What is asserted
here is what must hold even when the model is wrong: a machine may not write the
user layer, nothing is deleted, a conclusion without provenance cannot exist,
and a contradiction is reviewed explicitly before the clock orders confirmed facts.

Everything that needs the 279 MB embedder or a running ollama is guarded and
reported as skipped, because `./scripts/test.sh` must pass on a machine that has
neither.
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
from tests._bootstrap import bootstrap, check, reset_db, run_module  # noqa: E402

bootstrap("aries-memory")
import numpy as np  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from agentic_core.database.base import async_session, engine  # noqa: E402
from aries.settings import SettingsService  # noqa: E402
from aries.settings.layers import Layer  # noqa: E402
from aries.workspace import retrieval, service  # noqa: E402
from aries.workspace.memory import embedding, extraction, migration, store, vectors  # noqa: E402
from aries.workspace.memory import calibration  # noqa: E402
from aries.workspace.models import (  # noqa: E402
    WorkspaceConclusion, WorkspaceConclusionSource, WorkspaceMemory,
)

HAVE_EMBEDDER = embedding.available()


async def fresh():
    await reset_db()
    store.reset_cache()


# ── schema and migration ─────────────────────────────────────────────────────

def test_migration_is_additive_and_idempotent_against_the_installed_shape():
    """Run against the table shape the live var/aries.db actually has."""
    import asyncio
    import sqlite3
    import tempfile

    from sqlalchemy.ext.asyncio import create_async_engine
    from agentic_core.database.base import Base

    installed = ("CREATE TABLE aries_workspace_memories (id VARCHAR(40) NOT NULL, "
                 "text TEXT NOT NULL, source VARCHAR(120) NOT NULL, "
                 "created_at DATETIME NOT NULL, PRIMARY KEY (id))")
    path = Path(tempfile.mkdtemp()) / "installed.db"
    raw = sqlite3.connect(path)
    raw.execute(installed)
    raw.execute("insert into aries_workspace_memories values(?,?,?,?)",
                ("keep", "Сакам кафе наутро.", "user", "2026-09-01 10:00:00"))
    raw.commit(); raw.close()

    async def run():
        old = create_async_engine(f"sqlite+aiosqlite:///{path}")
        first = await migration.upgrade(old)
        migration._done = False
        second = await migration.upgrade(old)
        await old.dispose()
        fresh_path = Path(tempfile.mkdtemp()) / "fresh.db"
        new = create_async_engine(f"sqlite+aiosqlite:///{fresh_path}")
        async with new.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            nothing = await conn.run_sync(migration.upgrade_sync)
        await new.dispose()
        return first, second, nothing, fresh_path

    first, second, nothing, fresh_path = asyncio.run(run())
    check("the migration adds every missing column on an installed database", len(first) == 12)
    check("running it twice changes nothing", second == [])
    check("a database built by create_all needs no migration", nothing == [])
    columns = lambda p: {r[1] for r in sqlite3.connect(p).execute(  # noqa: E731
        "pragma table_info(aries_workspace_memories)")}
    check("migrated and create_all shapes are identical", columns(path) == columns(fresh_path))
    row = sqlite3.connect(path).execute(
        "select text, layer, expired_at from aries_workspace_memories").fetchone()
    check("an existing row survives, at the user layer, unexpired",
          row == ("Сакам кафе наутро.", int(Layer.USER), None))
    check("no ALTER statement drops or renames anything",
          all(s.startswith("ALTER TABLE") and " ADD COLUMN " in s for s in first))


# ── the layer rule, enforced on the write path ───────────────────────────────

async def test_a_machine_may_not_write_the_user_layer():
    await fresh()
    async with async_session() as db:
        try:
            await store.record(db, "ARIES concluded this on its own", source="aries:memory")
            refused = False
        except store.MemoryRefused:
            refused = True
        check("an inference cannot be written into the utterance table", refused)

        spoken = await store.record(db, "Живеам во Скопје.", source="voice")
        check("a human channel can", spoken.layer == int(Layer.USER) and spoken.source == "voice")

        for layer in (Layer.USER, Layer.INSTRUCTION, Layer.RESTRICTION, Layer.SECURITY):
            try:
                await store.conclude(db, text="x", sources=[spoken.id], decision="APPEND",
                                     confidence=1., rationale="r", stage="test", layer=layer)
                allowed = True
            except store.MemoryRefused:
                allowed = False
            check(f"a conclusion may not claim {Layer(layer).label}", not allowed)

        try:
            await store.conclude(db, text="x", sources=[], decision="APPEND", confidence=1.,
                                 rationale="r", stage="test")
            unexplained = True
        except store.MemoryRefused:
            unexplained = False
        check("a conclusion with no source utterance cannot exist", not unexplained)


async def test_provenance_is_a_foreign_key_not_a_convention():
    await fresh()
    async with async_session() as db:
        first = await store.record(db, "Мојот ментор е професор Иванов.", source="user")
        second = await store.record(db, "Менторот се смени.", source="user")
        drawn = await store.conclude(db, text=second.text, sources=[first.id, second.id],
                                     decision="SUPERSEDE", confidence=.9,
                                     rationale="stage=model", stage="model")
        sources = await store.provenance(db, drawn.id)
        check("a conclusion names the utterances it was drawn from",
              {s["id"] for s in sources} == {first.id, second.id})
        check("the conclusion carries a confidence and a rationale the utterance does not",
              drawn.confidence == .9 and drawn.rationale
              and not hasattr(first, "confidence") and not hasattr(first, "rationale"))
        check("the conclusion is at the learned layer", drawn.layer == int(Layer.LEARNED))
        rows = (await db.execute(select(WorkspaceConclusionSource))).scalars().all()
        check("provenance rows exist in their own join table", len(rows) == 2)


async def test_what_the_user_said_is_never_rewritten_or_translated():
    await fresh()
    spoken = "Сакам вестите да ми ги читаш на македонски, не на англиски."
    async with async_session() as db:
        row = await store.record(db, spoken, source="voice")
        check("the utterance is stored verbatim", row.text == spoken)
        check("its language is recorded as the script it was spoken in", row.lang == "mk")
        drawn = await store.conclude(db, text=row.text, sources=[row.id], decision="APPEND",
                                     confidence=.8, rationale="stage=model", stage="model",
                                     lang=row.lang)
        cyrillic = sum(1 for c in drawn.text if "Ѐ" <= c <= "ӿ")
        check("the conclusion is a copy, in the same script — no model wrote these words",
              drawn.text == spoken and cyrillic > 0)


# ── never delete, four timestamps ────────────────────────────────────────────

async def test_forgetting_expires_and_keeps_the_row():
    await fresh()
    async with async_session() as db:
        row = await store.record(db, "Одам на пливање во четврток.", source="user")
        drawn = await store.conclude(db, text=row.text, sources=[row.id], decision="APPEND",
                                     confidence=.7, rationale="stage=novelty", stage="novelty")
        check("forget reports success", await store.forget(db, row.id))
        after = await db.get(WorkspaceMemory, row.id)
        check("the row is still there", after is not None)
        check("it carries a system-time expiry and a world-time invalidity",
              after.expired_at is not None and after.invalid_at is not None)
        check("it no longer appears in the live list",
              row.id not in {r.id for r in await store.utterances(db)})
        check("it is still there when expired rows are asked for",
              row.id in {r.id for r in await store.utterances(db, include_expired=True)})
        withdrawn = await db.get(WorkspaceConclusion, drawn.id)
        check("a conclusion whose evidence was forgotten is withdrawn too",
              withdrawn.expired_at is not None)


async def test_contradiction_is_settled_by_the_clock_not_by_an_opinion():
    await fresh()
    async with async_session() as db:
        source = await store.record(db, "Работам навечер.", source="user")
        old = await store.conclude(db, text="Работам навечер.", sources=[source.id],
                                   decision="APPEND", confidence=.9, rationale="r", stage="model",
                                   valid_at=datetime(2026, 1, 1))
        new = await store.conclude(db, text="Работам наутро.", sources=[source.id],
                                   decision="SUPERSEDE", confidence=.9, rationale="r", stage="model",
                                   valid_at=datetime(2026, 6, 1))
        loser, reason = await store.arbitrate(db, new, f"{store.CONCLUSION}:{old.id}", commit=True, confirmed=True)
        check("the earlier statement loses", loser.id == old.id and "superseded" in reason)
        check("the loser points at what replaced it", loser.superseded_by == new.id)
        check("its world-time validity ends when the newer one began",
              loser.invalid_at == new.valid_at and loser.expired_at is not None)
        check("the winner is untouched", new.expired_at is None)

        # And the case that proves the model is not choosing: hand arbitration a
        # 'winner' that is older than what it claims to replace.
        stale = await store.conclude(db, text="Работам навечер, пак.", sources=[source.id],
                                     decision="SUPERSEDE", confidence=1., rationale="r",
                                     stage="model", valid_at=datetime(2026, 3, 1))
        loser, reason = await store.arbitrate(db, stale, f"{store.CONCLUSION}:{new.id}", commit=True, confirmed=True)
        check("a 'winner' older in world time is the one that expires",
              loser.id == stale.id and "stands" in reason)
        check("the newer stored belief survives a wrong supersession",
              (await db.get(WorkspaceConclusion, new.id)).expired_at is None)


async def test_a_machine_supersession_never_unsays_what_the_user_said():
    await fresh()
    async with async_session() as db:
        said = await store.record(db, "Мојот ментор е професор Иванов.", source="user")
        drawn = await store.conclude(db, text=said.text, sources=[said.id], decision="APPEND",
                                     confidence=.9, rationale="r", stage="model")
        newer = await store.record(db, "Менторот ми се смени.", source="user")
        replacement = await store.conclude(db, text=newer.text, sources=[newer.id],
                                           decision="SUPERSEDE", confidence=.9, rationale="r",
                                           stage="model")
        target = await store._live_conclusion_for(db, f"{store.MEMORY}:{said.id}")
        check("the withdrawable row behind an utterance is its conclusion", target.id == drawn.id)
        await store.arbitrate(db, replacement, f"{store.CONCLUSION}:{target.id}", commit=True, confirmed=True)
        check("the utterance the user spoke is untouched",
              (await db.get(WorkspaceMemory, said.id)).expired_at is None)
        check("only the learned conclusion is withdrawn",
              (await db.get(WorkspaceConclusion, drawn.id)).expired_at is not None)
        check("confirmed supersession does not hide the USER utterance",
              said.id not in await store.withdrawn_sources(db))
        check("the utterance that replaced it is still offered",
              newer.id not in await store.withdrawn_sources(db))


# ── stage 1: the gate ────────────────────────────────────────────────────────

def test_the_gate_refuses_what_must_never_be_remembered():
    refusals = {
        "secret": "Мојата лозинка за вај-фај е mk12345678.",
        "card": "Бројот на картичката ми е 4111 1111 1111 1111.",
        "private key": "-----BEGIN OPENSSH PRIVATE KEY-----",
        "api key": "my api key = sk-abcdefghijklmnop12345",
        "command": "отвори YouTube и пушти песна",
        "english command": "play some music.",
        "too short": "да",
    }
    for label, spoken in refusals.items():
        verdict = extraction.gate(spoken)
        check(f"refused: {label}", verdict is not None and verdict.action == "ABORT")
    check("an excluded topic is refused on the machine write path",
          extraction.gate("Одам на терапија секој вторник.", excluded=["терапија"]) is not None)
    check("privacy.remember_conversations off refuses everything",
          extraction.gate("Живеам во Скопје.", allowed=False) is not None)
    check("an ordinary statement passes", extraction.gate("Живеам во Скопје, во Аеродром.") is None)
    check("the gate costs no model call and no embedding",
          extraction.gate("play some music.").stage == "gate")


async def test_the_excluded_topic_setting_is_enforced_on_the_machine_path():
    await fresh()
    async with async_session() as db:
        await SettingsService(db).set("privacy.excluded_memory_topics", ["терапија"], set_by="user")
        await db.commit()
        result = await store.observe(db, "Одам на терапија секој вторник наутро.", source="voice")
        check("nothing was written", result["stored"] is None)
        check("and the reason names the setting", "excluded topic" in result["verdict"]["reason"])
        check("no row exists", not (await store.utterances(db)))
        result = await store.observe(db, "Мојата лозинка за вај-фај е mk12345678.", source="voice")
        check("a credential is refused before anything is embedded",
              result["stored"] is None and result["verdict"]["stage"] == "gate")


# ── stage 2: the band ────────────────────────────────────────────────────────

def test_only_the_uncertain_middle_band_escalates():
    cascade = extraction.Cascade(redundant_above=.97, novel_below=.85)
    check("nothing stored means keep it, with no model call",
          cascade.novelty([]).action == "APPEND")
    check("a restatement is a NOOP", cascade.novelty([("m:1", .99, "x")]).action == "NOOP")
    check("something unrelated is kept outright",
          cascade.novelty([("m:1", .80, "x")]).action == "APPEND")
    check("only the middle escalates", cascade.novelty([("m:1", .91, "x")]).action == "ESCALATE")
    check("no model was called by any of those", cascade.calls == 0)


async def test_a_restatement_bumps_recency_instead_of_writing_a_row():
    if not HAVE_EMBEDDER:
        check("SKIPPED — no embedder installed (./scripts/aries-fetch-embedder)", True)
        return
    await fresh()
    async with async_session() as db:
        cascade = extraction.Cascade(redundant_above=.97, novel_below=.85)
        spoken = "Сакам кафе наутро, без шеќер."
        first = await store.observe(db, spoken, source="voice", cascade=cascade)
        check("the first time it is kept", first["stored"] is not None)
        before = len(await store.utterances(db))
        again = await store.observe(db, spoken, source="voice", cascade=cascade)
        check("saying exactly the same thing writes no new row",
              again["stored"] is None and len(await store.utterances(db)) == before)
        check("it is recorded as a NOOP decided without a model",
              again["verdict"]["action"] == "NOOP" and again["verdict"]["stage"] == "novelty")
        bumped = await db.get(WorkspaceMemory, first["stored"]["memory"]["id"])
        conclusion = await db.get(WorkspaceConclusion, first["stored"]["conclusion"]["id"])
        check("restating it refreshed the recency of what was already known",
              (bumped.retrievals or 0) + (conclusion.retrievals or 0) == 1)
        check("no model was called at any point", cascade.calls == 0)


async def test_observation_degrades_rather_than_guesses():
    await fresh()
    async with async_session() as db:
        await SettingsService(db).set("workspace.semantic_memory", False, set_by="user")
        await db.commit()
        result = await store.observe(db, "Живеам во Скопје, во Аеродром.", source="voice")
        check("with the setting off nothing is written and the reason says why",
              result["stored"] is None and "semantic_memory" in result["verdict"]["reason"])
    cascade = extraction.Cascade(endpoint="http://127.0.0.1:1")     # nothing listens there
    verdict = cascade.run("Мојот ментор е професорка Петрова.", [("m:1", .90, "Ментор Иванов.")])
    check("an unreachable model keeps the statement rather than dropping it",
          verdict.action == "APPEND")
    check("and says so, with the cosine as its confidence",
          "no local model" in verdict.reason and 0. < verdict.confidence < 1.)


def test_the_debounce_keeps_the_cascade_off_the_voice_path():
    import time
    store._pending.clear()
    started = time.perf_counter()
    queued = store.observe_later("Живеам во Скопје.", source="voice")
    elapsed = (time.perf_counter() - started) * 1000
    check("queueing an utterance outside a loop does not start work", queued is False)
    check("and returns in well under a millisecond", elapsed < 1.)
    check("the text is queued, not written", store._pending == [("Живеам во Скопје.", "voice")])
    store._pending.clear()
    check("empty speech is not queued", store.observe_later("   ") is False and not store._pending)


# ── stage 3: the calibrated enum ─────────────────────────────────────────────

def test_the_label_is_recovered_even_when_the_model_explains_itself():
    """A local model asked for one word sometimes writes a sentence. The trie
    walk must still score the label it began with — reading it as 'not emitted'
    produced a 0.250 confidence on a decision made with no hesitation at all."""
    import json
    import urllib.request
    from unittest.mock import patch

    steps = [{"token": "SUPERSEDE", "logprob": -0.01,
              "top_logprobs": [{"token": "SUPERSEDE", "logprob": -0.01},
                               {"token": "APPEND", "logprob": -4.6},
                               {"token": "COEXIST", "logprob": -6.9},
                               {"token": "ABORT", "logprob": -9.2}]},
             {"token": " -", "logprob": -0.7, "top_logprobs": [{"token": " -", "logprob": -0.7}]},
             {"token": " the", "logprob": -0.2, "top_logprobs": [{"token": " the", "logprob": -0.2}]}]

    class Response:
        def read(self): return json.dumps({"logprobs": steps}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    with patch.object(calibration, "open_local", lambda *a, **k: Response()):
        result = calibration.classify("prompt", extraction.LABELS,
                                      endpoint="http://127.0.0.1:11434", model="m")
    check("the label the model began with is the label", result["label"] == "SUPERSEDE")
    check("its confidence reflects the logits, not the explanation", result["confidence"] > .9)
    check("the explanation is preserved for the audit row", result["emitted"].startswith("SUPERSEDE -"))
    check("probabilities are a distribution over the four labels",
          abs(sum(result["probs"].values()) - 1.) < 1e-9 and set(result["probs"]) == set(extraction.LABELS))
    check("labels are names, never letters", all(len(x) > 4 for x in extraction.LABELS))


# ── the cached matrix ────────────────────────────────────────────────────────

def test_the_vector_cache_grows_without_copying_the_whole_matrix():
    cache = vectors.VectorCache(8, capacity=2)
    rows = np.random.default_rng(7).normal(size=(40, 8)).astype(np.float32)
    rows /= np.linalg.norm(rows, axis=1, keepdims=True)
    buffers = set()
    for i, row in enumerate(rows):
        cache.add(f"m:{i}", row)
        buffers.add(id(cache._rows))
    check("all forty rows are present", len(cache) == 40)
    check("the buffer doubled a handful of times, not forty", len(buffers) <= 6)
    check("capacity is a power-of-two multiple of the start", cache._rows.shape[0] == 64)
    query = rows[13]
    exact = np.argsort(-(rows @ query))[:5]
    check("search returns exactly what brute force does",
          [i for i, _ in cache.search(query, 5)] == [f"m:{i}" for i in exact])
    check("the nearest row to itself is itself, at cosine one",
          cache.nearest(query)[0] == "m:13" and abs(cache.nearest(query)[1] - 1.) < 1e-5)
    check("replacing a row keeps its slot", cache.add("m:0", rows[1]) is None and len(cache) == 40)
    check("dropping a row removes it and only it",
          cache.drop("m:13") and len(cache) == 39 and "m:13" not in cache.ids)
    check("dropping something absent is not an error", cache.drop("m:13") is False)
    check("the matrix view is the live rows only", cache.matrix.shape == (39, 8))
    check("a wrong-width vector is refused",
          _raises(lambda: cache.add("m:x", np.zeros(4, np.float32)), ValueError))


def _raises(fn, kind):
    try:
        fn()
    except kind:
        return True
    return False


def test_the_embedder_is_a_function_of_its_text_alone():
    """Dynamic int8 quantisation computes its scales from the tensor it is
    given, so a padded batch used to change the answer — measured at cosine
    0.947 between the same sentence embedded alone and in a batch of 45. A
    vector that depends on its neighbours cannot be compared with one stored
    last week."""
    if not HAVE_EMBEDDER:
        check("SKIPPED — no embedder installed (./scripts/aries-fetch-embedder)", True)
        return
    embedder = embedding.get()
    texts = ["play some music.", "Сакам кафе наутро, без шеќер.",
             "Докторот ми рече да не пијам кафе после шест часот навечер, затоа сега пијам чај."]
    together = embedder.passages(texts)
    alone = np.vstack([embedder.passages([t]) for t in texts])
    check("batched and single embeddings are bit-identical",
          float(np.abs(together - alone).max()) == 0.)
    check("vectors are unit length",
          np.allclose(np.linalg.norm(together, axis=1), 1., atol=1e-5))
    check("query and passage prefixes are applied, and differ",
          float(embedder.query(texts[1]) @ embedder.passages([texts[1]])[0]) < 1.)
    check("the model-card example reproduces",
          float(embedder.encode(["how much protein should a female eat"], kind="query")[0]
                @ embedder.encode(["As a general guideline, the CDC's average requirement of protein "
                                   "for women ages 19 to 70 is 46 grams per day."], kind="passage")[0]) > .9)


def test_an_absent_embedder_is_reported_not_guessed():
    check("an unknown backend is refused",
          _raises(lambda: embedding.get("no-such-model"), embedding.EmbedderUnavailable))
    check("a missing model directory is refused",
          _raises(lambda: embedding.OnnxE5(directory="/nonexistent"), embedding.EmbedderUnavailable))
    vector = np.arange(4, dtype=np.float32)
    check("vectors round-trip through the blob column",
          np.array_equal(embedding.unpack(embedding.pack(vector), 4), vector))
    check("a vector of the wrong width is rejected rather than reshaped",
          embedding.unpack(embedding.pack(vector), 8) is None)


# ── retrieval ────────────────────────────────────────────────────────────────

def test_inflected_forms_of_one_verb_finally_match():
    """`сакам` / `сакаше` / `сакав` are one verb. Exact word matching never
    linked them, which made a Macedonian speaker's own memory unreachable."""
    for forms in (("сакам", "сакаш", "сакаше", "сакав", "сакале", "сакаат", "сака", "сакаме"),
                  ("работа", "работата", "работи", "работите"),
                  ("проект", "проектот", "проекти", "проектите"),
                  ("песна", "песната", "песни", "песните"),
                  ("вест", "вести", "вестите"),
                  ("meeting", "meetings", "meet"),
                  ("study", "studies")):
        stems = {retrieval.stem(w) for w in forms}
        check(f"one stem for {forms[0]} and its {len(forms)-1} other forms", len(stems) == 1)
    check("unrelated words stay apart", retrieval.stem("мастер") != retrieval.stem("маса"))
    check("the old predicate really did miss it",
          "сакав" not in {w for w in "сакам кафе".split() if len(w) > 3})
    check("generic command words carry no content",
          not (retrieval.stems("отвори го") & retrieval.stems("прикажи ми")))


def test_retrieval_versions_are_named_and_unknown_ones_refused():
    check("semantic-v3 joined the existing scheme",
          retrieval.VERSIONS == ("overlap-v1", "focused-v2", "semantic-v3"))
    check("an unknown review version is refused",
          _raises(lambda: retrieval.rank([], "q", "nope"), ValueError))
    check("an unknown memory version is refused",
          _raises(lambda: retrieval.score_memories([{"text": "x"}], "q", "nope"), ValueError))


def test_what_the_user_said_outranks_what_aries_inferred():
    now = datetime(2026, 9, 29, 12, 0, 0)
    common = {"text": "Сакам кафе наутро.", "kind": "preference", "importance": .7,
              "created_at": now - timedelta(hours=1), "last_retrieved_at": None}
    rows = [{"id": "learned", "layer": int(Layer.LEARNED), **common},
            {"id": "said", "layer": int(Layer.USER), **common}]
    ranked = retrieval.score_memories(rows, "што сакав наутро", "focused-v2", now=now)
    check("at equal similarity the user layer wins", ranked[0][1]["id"] == "said")
    check("and it wins by the layer term alone",
          abs((ranked[0][0] - ranked[1][0])
              - retrieval.W_LAYER * (Layer.USER - Layer.LEARNED) / retrieval.MAX_LAYER) < 1e-9)

    old = dict(common, id="old", layer=int(Layer.USER), kind="plan",
               created_at=now - timedelta(days=60))
    recent = dict(common, id="recent", layer=int(Layer.USER), kind="plan")
    ranked = retrieval.score_memories([old, recent], "што сакав наутро", "focused-v2", now=now)
    check("a stale plan loses to a fresh one of the same kind", ranked[0][1]["id"] == "recent")
    check("an identity claim decays far slower than a plan",
          retrieval.decay(dict(recent, kind="identity"), now + timedelta(days=60))
          > retrieval.decay(dict(recent, kind="plan"), now + timedelta(days=60)))


async def test_memory_list_has_no_cap_and_recency_refreshes_on_retrieval():
    await fresh()
    async with async_session() as db:
        for i in range(210):
            db.add(WorkspaceMemory(id=f"m{i:04d}", text=f"Факт број {i} за проектот.",
                                   source="user", created_at=datetime(2026, 9, 1) + timedelta(minutes=i),
                                   layer=int(Layer.USER), kind="fact", importance=.6))
        await db.commit()
        listed = await service.memory_list(db)
        check("every memory is listed — the 200-row cap is gone", len(listed) == 210)
        check("brute force over them all is still versioned selection",
              len(await store.relevant(db, "факт за проектот", version="focused-v2", limit=5)) == 5)
        refreshed = (await db.execute(
            select(WorkspaceMemory).where(WorkspaceMemory.last_retrieved_at.isnot(None)))).scalars().all()
        check("the memories actually used had their recency refreshed", len(refreshed) == 5)
        check("and their retrieval counts incremented", all(r.retrievals == 1 for r in refreshed))


async def test_the_dashboard_keeps_the_two_tables_apart():
    await fresh()
    async with async_session() as db:
        said = await store.record(db, "Мојот проект се вика АРИЕС.", source="user")
        await store.conclude(db, text=said.text, sources=[said.id], decision="APPEND",
                             confidence=.8, rationale="stage=model", stage="model")
        snapshot = await service.snapshot(db)
        check("utterances and conclusions are separate keys in one snapshot",
              len(snapshot["memories"]) == 1 and len(snapshot["conclusions"]) == 1)
        check("the utterance carries no confidence", "confidence" not in snapshot["memories"][0])
        check("the conclusion carries one, with its layer named",
              snapshot["conclusions"][0]["confidence"] == .8
              and snapshot["conclusions"][0]["layer_name"] == "learned preference")
        check("the Control Centre's existing keys still resolve",
              set(snapshot["memories"][0]) >= {"id", "text", "source", "created_at"})


# ── end to end, when the machine has the model ───────────────────────────────

async def test_an_unasked_write_stores_both_rows_or_neither():
    if not HAVE_EMBEDDER:
        check("SKIPPED — no embedder installed (./scripts/aries-fetch-embedder)", True)
        return
    await fresh()
    async with async_session() as db:
        cascade = extraction.Cascade(endpoint="http://127.0.0.1:1")   # decide offline
        result = await store.observe(db, "Мастер трудот ми е за адаптивни агентски системи.",
                                     source="voice", cascade=cascade)
        check("an unasked observation wrote something", result["stored"] is not None)
        utterances = await store.utterances(db)
        conclusions = await store.conclusions(db)
        check("exactly one utterance and one conclusion",
              len(utterances) == 1 and len(conclusions) == 1)
        check("the utterance is at the user layer and the conclusion at the learned layer",
              utterances[0].layer == int(Layer.USER) and conclusions[0].layer == int(Layer.LEARNED))
        check("both were embedded by the same model",
              utterances[0].embedding_model == conclusions[0].embedding_model != "")
        check("the conclusion explains itself",
              "stage=" in conclusions[0].rationale and "confidence=" in conclusions[0].rationale)
        check("the conclusion points back at the utterance",
              (await store.provenance(db, conclusions[0].id))[0]["id"] == utterances[0].id)
        refused = await store.observe(db, "отвори Spotify и пушти музика", source="voice", cascade=cascade)
        check("a command writes neither row",
              refused["stored"] is None and len(await store.utterances(db)) == 1)


async def test_retrieval_finds_an_inflected_macedonian_memory_end_to_end():
    if not HAVE_EMBEDDER:
        check("SKIPPED — no embedder installed (./scripts/aries-fetch-embedder)", True)
        return
    await fresh()
    async with async_session() as db:
        for spoken in ("Сакам кафе наутро, без шеќер.",
                       "Живеам во Скопје, во Аеродром.",
                       "Мојот лаптоп има 16 гигабајти рам."):
            await store.record(db, spoken, source="user", cache=await store.warm(db))
        found = await store.relevant(db, "што сакав да пијам наутро", version="semantic-v3", limit=1)
        check("an inflected question reaches the memory that answers it",
              found and found[0][1]["text"].startswith("Сакам кафе"))
        lexical = await store.relevant(db, "што сакав да пијам наутро", version="focused-v2", limit=1)
        check("and the repaired lexical version reaches it too",
              lexical and lexical[0][1]["text"].startswith("Сакам кафе"))


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
