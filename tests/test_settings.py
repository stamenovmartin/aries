"""What the Settings Service must guarantee.

The central one is specification section 30: learned behaviour never overrides
an explicit user preference. It is pinned from both directions — the read path
(a user value outranks a learned one) and the write path (a machine author
cannot write a user layer at all), because read-side precedence alone would be
defeated by a learning loop that simply wrote the stronger layer.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-settings")          # MUST precede every agentic_core / aries import

from agentic_core.database.base import async_session  # noqa: E402

from aries.settings import Layer, SettingError, SettingsService, all_defs, sections  # noqa: E402


async def test_defaults_and_schema():
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        check("a default resolves without any stored row",
              await s.get("news.relevance_threshold") == 0.6)
        check("every shipped default validates against its own schema",
              all(d.coerce(d.default) is not None or d.default in ([], {}, "", 0, 0.0, False)
                  for d in all_defs()))
        check("sections are discoverable for the Settings app",
              "news" in sections() and "autonomy" in sections())
        check("an unknown key raises rather than guessing",
              await _raises(s.get("news.nonexistent")))
        check("an unknown key with an explicit fallback returns it",
              await s.get("news.nonexistent", fallback=42) == 42)


async def test_validation():
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        check("a float out of range is refused",
              await _raises(s.set("news.relevance_threshold", 1.4)))
        check("a wrong type is refused",
              await _raises(s.set("news.enabled", "maybe")))
        check("a string boolean is accepted and normalised",
              (await s.set("news.enabled", "yes"))["written"] is True)
        check("a value outside the declared choices is refused",
              await _raises(s.set("general.theme", "neon")))
        check("a valid choice is accepted",
              (await s.set("general.theme", "dark"))["written"] == "dark")


async def test_user_beats_learned():
    """Section 30, the read path."""
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.learn("news.relevance_threshold", 0.72, confidence=0.8,
                      rationale="12 of 15 low scorers were ignored")
        check("a learned value applies when the user has said nothing",
              await s.get("news.relevance_threshold") == 0.72)

        await s.set("news.relevance_threshold", 0.5, set_by="user")
        check("an explicit user value outranks the learned one",
              await s.get("news.relevance_threshold") == 0.5)

        out = await s.learn("news.relevance_threshold", 0.9, confidence=0.95,
                            rationale="the user ignored even more low scorers")
        check("learning again does not move the effective value",
              await s.get("news.relevance_threshold") == 0.5)
        check("and the learner is told its value is shadowed", out["shadowed"] is True)

        await s.clear("news.relevance_threshold", layer=Layer.USER)
        check("clearing the user value promotes the learned one, not the default",
              await s.get("news.relevance_threshold") == 0.9)


async def test_machine_cannot_write_user_layers():
    """Section 30, the write path — the rule that makes the read path honest."""
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        check("a machine author may not write the USER layer",
              await _raises(s.set("news.topics", ["ai"], layer=Layer.USER, set_by="learning")))
        check("a machine author may not write a RESTRICTION",
              await _raises(s.set("news.topics", [], layer=Layer.RESTRICTION, set_by="automation:news")))
        check("a machine author may write the LEARNED layer",
              (await s.set("news.topics", ["ai"], layer=Layer.LEARNED, set_by="learning"))["written"] == ["ai"])
        check("a user-only setting refuses a machine author entirely",
              await _raises(s.learn("autonomy.level", "automated", confidence=0.99, rationale="it went well")))
        check("the user may still set a user-only setting",
              (await s.set("autonomy.level", "assisted", set_by="user"))["written"] == "assisted")


async def test_security_layer_is_absolute():
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("autonomy.max_actions_per_hour", 500, set_by="user")
        check("the user's value applies with no security policy present",
              await s.get("autonomy.max_actions_per_hour") == 500)
        await s.set("autonomy.max_actions_per_hour", 20, layer=Layer.SECURITY, set_by="human:security")
        check("a security policy outranks even an explicit user setting",
              await s.get("autonomy.max_actions_per_hour") == 20)


async def test_scope_overrides_global():
    await reset_db()
    async with async_session() as db:
        await SettingsService(db).set("briefing.length", "standard", set_by="user")
        scoped = SettingsService(db, scope="project:insomnia")
        await scoped.set("briefing.length", "detailed", set_by="user", scope="project:insomnia")
        check("a project scope overrides the global value inside that project",
              await scoped.get("briefing.length") == "detailed")
        check("and the global value is untouched outside it",
              await SettingsService(db).get("briefing.length") == "standard")


async def test_explain_shows_its_work():
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.learn("news.relevance_threshold", 0.72, confidence=0.8, rationale="inferred")
        await s.set("news.relevance_threshold", 0.5, set_by="user")
        e = await s.explain("news.relevance_threshold")
        check("explain names the winning layer", e["source"] == "user" and e["value"] == 0.5)
        check("explain keeps the overridden learned value visible",
              any(x["layer"] == "learned" and x["value"] == 0.72 for x in e["stack"]))
        check("explain carries the learned rationale for the UI",
              any(x["rationale"] == "inferred" for x in e["stack"]))
        check("explain includes the definition so a UI can render a control",
              e["definition"]["control"] == "slider")


async def test_digest_is_agent_readable():
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("news.topics", ["ai agents", "telecom"], set_by="user")
        d = await s.digest("news")
        check("a digest carries the value", d["news.topics"]["value"] == ["ai agents", "telecom"])
        check("a digest carries the meaning, so a model knows what the knob does",
              "relevant" in d["news.topics"]["what"])
        check("a digest is scoped to the requested prefix",
              all(k.startswith("news.") for k in d))


async def test_get_many_is_one_query():
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("news.enabled", True, set_by="user")
        got = await s.get_many(["news.enabled", "news.relevance_threshold", "general.theme"])
        check("get_many mixes stored and default values correctly",
              got == {"news.enabled": True, "news.relevance_threshold": 0.6, "general.theme": "system"})


async def _raises(coro) -> bool:
    try:
        await coro
        return False
    except SettingError:
        return True


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
