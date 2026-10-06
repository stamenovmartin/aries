"""A minimal command line for ARIES, until the shell of §5 exists.

    python -m aries.cli health          run one health pass and print the report
    python -m aries.cli health --json   the same, as JSON
    python -m aries.cli automations     what is registered, enabled and due
    python -m aries.cli settings [pfx]  resolved settings and where each came from

This is a window onto the system, not a second way of running it: `health` goes
through the same task kind and lifecycle the scheduler uses, so what is printed
here is exactly what an automated pass does. One code path, as the engine insists.
"""
from __future__ import annotations

import argparse
import asyncio
import time
import subprocess
import json
import os
import sys

# Escapes are emitted only to a terminal. Piping `aries health` into a file or
# another program must give plain text, or every consumer has to strip ANSI.
_TTY = sys.stdout.isatty()
COLOUR = ({"ok": "\033[32m", "notice": "\033[36m", "warning": "\033[33m", "critical": "\033[31m"}
          if _TTY else {k: "" for k in ("ok", "notice", "warning", "critical")})
BOLD, DIM, RESET = ("\033[1m", "\033[2m", "\033[0m") if _TTY else ("", "", "")


def _paint(text: str, colour: str) -> str:
    return f"{colour}{text}{RESET}" if colour else text


async def _bootstrap():
    import aries  # noqa: F401  registers tables, settings, automations
    from agentic_core.database.base import Base, engine
    from agentic_core.database import models  # noqa: F401
    from aries.workspace.memory import migration as memory_migration
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # `create_all` creates missing TABLES; it never ALTERs an existing one,
        # and there is no alembic here. Semantic memory added columns to
        # `aries_workspace_memories`, which already exists in every installed
        # database, so the ADD COLUMNs are explicit, additive and idempotent.
        await conn.run_sync(memory_migration.upgrade_sync)

    # Point the engine at the model ARIES's settings name. Here rather than in
    # each command: the provider persists across processes and the model name
    # does not, so a command that never armed asked Ollama for a model nobody
    # pulled and got a 404 that read as "the model server is broken".
    from agentic_core.database.base import async_session
    from aries import intelligence
    try:
        async with async_session() as db:
            await intelligence.arm(db)
    except Exception:                               # noqa: BLE001
        pass


async def cmd_health(args) -> int:
    await _bootstrap()
    from agentic_core.database.base import async_session
    from agentic_core.orchestrator.service import create_task
    from agentic_core.scheduler.queue import run_task_now

    from aries.health import TASK_KIND
    from aries.settings import SettingsService

    async with async_session() as db:
        if not await SettingsService(db).get("health.enabled"):
            print("health.enabled is off — run:  python -m aries.cli settings-set health.enabled true")
            return 2
        task = await create_task(db, kind=TASK_KIND, title="System health check",
                                 brief="Check CPU, memory, disk, temperature, GPU and services.")
        task_id = task.id

    out = await run_task_now(task_id, trigger="cli")
    result = (out.get("outcome") or {}).get("result") or {}

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("severity") in ("ok", "notice") else 1

    sev = result.get("severity", "ok")
    print(f"\n{BOLD}System health{RESET}  " + _paint(sev.upper(), COLOUR.get(sev, "")))
    print(f"{DIM}{result.get('summary', '')}{RESET}\n")

    for f in result.get("findings", []):
        mark = {"ok": "·", "notice": "i", "warning": "!", "critical": "!!"}[f["severity"]]
        line = f"  {_paint(mark.rjust(2), COLOUR.get(f['severity'], ''))}  {f['summary']}"
        if f.get("suppressed"):
            line += f"\n      {DIM}↓ {f['suppressed']}{RESET}"
        elif f.get("advice") and f["severity"] != "ok":
            line += f"\n      {DIM}{f['advice']}{RESET}"
        print(line)

    notes = result.get("notifications") or []
    if notes:
        print(f"\n{BOLD}Notifications{RESET}")
        for n in notes:
            print(f"  {n['level']:9} {n['disposition']:22} {DIM}{n['reason']}{RESET}")

    if result.get("probes_unavailable"):
        print(f"\n{DIM}probes unavailable: {', '.join(result['probes_unavailable'])}{RESET}")
    print(f"\n{DIM}{result.get('duration_ms', 0)} ms · {result.get('samples_recorded', 0)} samples "
          f"recorded · task {task_id} · {out.get('outcome', {}).get('verdict')}{RESET}")
    if result.get("requires_approval"):
        print(_paint(f"\n  A critical finding needs a human — proposal "
                     f"#{out['outcome'].get('proposal_id')} is waiting.", COLOUR["critical"]))
    return 0 if sev in ("ok", "notice") else 1


async def cmd_automations(args) -> int:
    await _bootstrap()
    from agentic_core.database.base import async_session

    from aries.automations import all_automations, due, health, is_enabled, last_run
    from aries.settings import SettingsService

    async with async_session() as db:
        s = SettingsService(db)
        print(f"\n{BOLD}Automations{RESET}\n")
        for spec in all_automations():
            enabled = await is_enabled(spec, s)
            ok, why = await due(db, spec, s)
            row = await last_run(db, spec.automation_id)
            h = await health(db, spec.automation_id)
            rate = "—" if h["success_rate"] is None else f"{h['success_rate'] * 100:.0f}%"
            print(f"  {BOLD}{spec.name}{RESET}  {DIM}v{spec.version} · {spec.automation_id}{RESET}")
            print(f"    {spec.purpose}")
            print(f"    enabled: {'yes' if enabled else 'no':4}  trigger: {spec.trigger:9} "
                  f"risk: {spec.risk}")
            print(f"    due now: {'yes' if ok else 'no':4}  {DIM}({why}){RESET}")
            if row:
                print(f"    last run: {row.status} · {row.summary[:70]} {DIM}({row.duration_ms} ms){RESET}")
            else:
                print(f"    last run: {DIM}never{RESET}")
            print(f"    success rate ({h['window_days']}d): {rate}"
                  + (f" {DIM}({h['reason']}){RESET}" if h["reason"] else ""))
            print()
    return 0


async def cmd_worker(args) -> int:
    await _bootstrap()
    from agentic_core.database.base import async_session
    from agentic_core.scheduler import registry

    from aries.automations.worker import WORKER_NAME, dispatch_pass
    from aries.settings import SettingsService

    if args.tick:
        out = await dispatch_pass()
        if "skipped" in out and "ran" not in out:
            print(f"nothing to do: {out['skipped']}")
            return 0
        print(f"ran {out['ran']}, skipped {out['skipped']}")
        for r in out.get("runs", []):
            print(f"  → {r['automation_id']}: {r.get('status')} {DIM}{r.get('summary', '')}{RESET}")
        for s_ in out.get("skips", []):
            print(f"  · {s_['automation_id']}: {DIM}{s_.get('why') or s_.get('reason')}{RESET}")
        return 0

    async with async_session() as db:
        on = await SettingsService(db).get("automations.worker_enabled")
    w = registry.get(WORKER_NAME)
    st = w.status() if w else {"state": "not registered"}
    print(f"\n{BOLD}Automations dispatcher{RESET}")
    print(f"  switch (automations.worker_enabled): {'on' if on else 'off'}")
    print(f"  task state:                         {st.get('state')}")
    print(f"  cadence:                            every {st.get('check_every_s', '?')}s")
    print(f"  {DIM}the switch is the user's setting; the task state is this process{RESET}")
    if not on:
        print(f"\n  turn it on:  ./scripts/aries settings-set automations.worker_enabled true")
    print()
    return 0


async def cmd_sources(args) -> int:
    await _bootstrap()
    from agentic_core.database.base import async_session

    from aries.sources import service as src
    from aries.sources import types as stypes
    from aries.sources.safety import SourceRejected

    async with async_session() as db:
        if args.action == "catalogue":
            from aries.news import catalogue as cat
            entries = cat.all_entries(category=args.category or None,
                                      language=args.language or None,
                                      search=args.search or None)
            have = {r.metadata_dict.get("catalogue_id") for r in await src.list_sources(db)}
            if not args.category and not args.search and not args.language:
                print(f"\n{BOLD}Where would you like news from?{RESET}")
                print(f"{DIM}pick a category with --category, or add one with: "
                      f"aries sources add-from <id>{RESET}\n")
                for c in cat.categories():
                    print(f"  {BOLD}{c['id']:12}{RESET} {c['count']:>2} feeds  {c['title']}")
                print()
            current = None
            for e in entries:
                if e.category != current:
                    current = e.category
                    print(f"\n{BOLD}{cat.CATEGORIES[current]}{RESET}")
                mark = _paint(" added", COLOUR["ok"]) if e.id in have else ""
                lang = f" [{e.language}]" if e.language != "en" else ""
                print(f"  {BOLD}{e.id:16}{RESET} {e.name}{lang}{mark}")
                print(f"  {'':16} {DIM}{e.description}{RESET}")
                if e.topics:
                    print(f"  {'':16} {DIM}topics: {', '.join(e.topics)}{RESET}")
                if e.note:
                    print(f"  {'':16} {DIM}note: {e.note}{RESET}")
            if entries:
                print(f"\n  {DIM}add one:  ./scripts/aries sources add-from {entries[0].id}{RESET}\n")
            return 0

        if args.action == "add-from":
            try:
                row = await src.add_from_catalogue(db, args.source_id)
            except (SourceRejected, ValueError) as e:
                print(_paint(f"refused: {e}", COLOUR["critical"]))
                return 1
            print(f"added {BOLD}{row.name}{RESET} ({row.source_id})")
            print(f"  {DIM}{row.location}{RESET}")
            if row.topics:
                print(f"  {DIM}tagged: {', '.join(row.topics)}{RESET}")
            return 0

        if args.action == "types":
            print(f"\n{BOLD}Source types{RESET}\n")
            for t in stypes.all_types():
                reach = _paint("outbound", COLOUR["warning"]) if t.outbound else "local"
                extra = []
                if t.requires_credentials:
                    extra.append("needs a credential")
                if t.needs_connector:
                    extra.append("connector not built yet")
                print(f"  {BOLD}{t.name:12}{RESET} {reach:9} {t.title}")
                print(f"  {'':12} {DIM}{t.description}{RESET}")
                print(f"  {'':12} {DIM}e.g. {t.example}"
                      + (f"  ({'; '.join(extra)})" if extra else "") + RESET)
                print()
            return 0

        if args.action == "add":
            try:
                row = await src.add(db, name=args.name, type=args.type, location=args.location,
                                    topics=[t for t in (args.topics or "").split(",") if t.strip()],
                                    priority=args.priority, trust=args.trust)
            except (SourceRejected, ValueError) as e:
                print(_paint(f"refused: {e}", COLOUR["critical"]))
                return 1
            t = stypes.get(row.type)
            print(f"added {BOLD}{row.source_id}{RESET} ({row.type}"
                  + (", leaves this machine" if t and t.outbound else ", local") + ")")
            print(f"  {DIM}{row.location}{RESET}")
            return 0

        if args.action == "rm":
            ok = await src.remove(db, args.source_id)
            print(f"removed {args.source_id}" if ok else f"no source '{args.source_id}'")
            return 0 if ok else 1

        if args.action == "resolve":
            wanted = [t for t in (args.topics or "").split(",") if t.strip()]
            rows = await src.for_agent(db, type=args.type, topics=wanted, capability=args.capability)
            print(f"\n{BOLD}What an agent would consult{RESET}  "
                  f"{DIM}type={args.type or 'any'} topics={wanted or 'any'}{RESET}")
            print(f"{DIM}ordered by: your priority, then your trust, then observed "
                  f"usefulness, then reliability{RESET}\n")
            if not rows:
                print("  (nothing matches — add a source, or check it is enabled)\n")
                return 0
            for i, r in enumerate(rows, 1):
                u = "—" if r.useful_rate is None else f"{r.useful_rate:.2f}"
                print(f"  {i}. {BOLD}{r.name}{RESET} {DIM}({r.source_id}){RESET}")
                print(f"     priority={stypes.Priority(r.priority).label} "
                      f"trust={stypes.Trust(r.trust).label} useful={u} "
                      f"topics={','.join(r.topics) or '—'}")
            print()
            return 0

        rows = await src.list_sources(db)
        if not rows:
            print("\nNo sources yet.  ./scripts/aries sources types   to see what can be added\n")
            return 0
        print(f"\n{BOLD}Sources{RESET}\n")
        for r in rows:
            t = stypes.get(r.type)
            h = r.health()
            colour = {"ok": COLOUR["ok"], "failing": COLOUR["critical"],
                      "degraded": COLOUR["warning"], "stale": COLOUR["warning"]}.get(h["state"], "")
            flag = "" if r.enabled else " (disabled)"
            print(f"  {_paint(h['state'].rjust(8), colour)}  {BOLD}{r.name}{RESET}{flag} "
                  f"{DIM}({r.source_id}){RESET}")
            print(f"            {r.type} · {'outbound' if t and t.outbound else 'local'} · "
                  f"priority={stypes.Priority(r.priority).label} · trust={stypes.Trust(r.trust).label}")
            print(f"            {DIM}{r.location[:78]}{RESET}")
            if h["reason"]:
                print(f"            {DIM}{h['reason'][:78]}{RESET}")
        s_ = await src.summary(db)
        print(f"\n  {DIM}{s_['total']} sources, {s_['enabled']} enabled, "
              f"{s_['outbound']} reach off this machine{RESET}\n")
        return 0


async def cmd_interests(args) -> int:
    await _bootstrap()
    from agentic_core.database.base import async_session

    from aries.interests import service as ints
    from aries.interests.service import InterestError
    from aries.settings import SettingsService

    async with async_session() as db:
        default = float(await SettingsService(db).get("interests.default_weight"))

        if args.action == "add":
            try:
                row = await ints.add(db, topic=args.topic, stance=args.stance,
                                     weight=args.weight,
                                     synonyms=[x for x in (args.synonyms or "").split(",") if x.strip()])
            except InterestError as e:
                print(_paint(f"refused: {e}", COLOUR["critical"]))
                return 1
            verb = "avoiding" if row.avoid else "following"
            print(f"{verb} {BOLD}{row.topic}{RESET} "
                  f"(weight {row.effective_weight(default):.2f} from {row.weight_source()})")
            if row.synonyms:
                print(f"  {DIM}also matches: {', '.join(row.synonyms)}{RESET}")
            return 0

        if args.action == "rm":
            ok = await ints.remove(db, args.topic)
            print(f"removed {args.topic}" if ok else f"'{args.topic}' is not in the profile")
            return 0 if ok else 1

        if args.action == "score":
            r = await ints.score_text(db, args.topic)
            colour = COLOUR["critical"] if r.excluded else (
                COLOUR["ok"] if r.score >= 0.6 else COLOUR["warning"])
            print(f"\n  {_paint(f'{r.score:.3f}', colour)}  {args.topic[:60]}")
            print(f"  {DIM}{r.explanation}{RESET}")
            for m in r.matched:
                terms = ", ".join(h["term"] for h in m["hits"])
                print(f"    {DIM}· {m['topic']} weight {m['weight']:.2f} "
                      f"({m['source']}) via {terms}{RESET}")
            print()
            return 0

        rows = await ints.list_interests(db)
        if not rows:
            print("\nNo topics yet.  ./scripts/aries interests add --topic 'LLM agents' --weight 0.9\n")
            return 0
        want = [r for r in rows if not r.avoid]
        avoid = [r for r in rows if r.avoid]
        print(f"\n{BOLD}Topics I care about{RESET}\n")
        for r in sorted(want, key=lambda x: -x.effective_weight(default)):
            w = r.effective_weight(default)
            src = r.weight_source()
            mark = {"user": "", "learned": " (learned)", "default": " (default)"}[src]
            bar = "█" * int(round(w * 20))
            print(f"  {w:.2f} {bar:<20} {BOLD}{r.topic}{RESET}{DIM}{mark}{RESET}")
            if r.synonyms:
                print(f"       {DIM}{', '.join(r.synonyms)}{RESET}")
            if r.learned_weight is not None and r.weight is not None:
                print(f"       {DIM}ARIES would have said {r.learned_weight:.2f} — "
                      f"{(r.learned_rationale or '')[:48]}{RESET}")
        if avoid:
            print(f"\n{BOLD}Topics to ignore{RESET}\n")
            for r in avoid:
                print(f"  {_paint('✕', COLOUR['critical'])}  {r.topic}"
                      + (f"{DIM}  ({', '.join(r.synonyms)}){RESET}" if r.synonyms else ""))
        s_ = await ints.summary(db)
        print(f"\n  {DIM}{s_['wanted']} followed, {s_['avoided']} ignored, "
              f"{s_['learned']} with a learned weight ({s_['shadowed']} overridden by you){RESET}\n")
        return 0


async def cmd_news(args) -> int:
    await _bootstrap()
    from agentic_core.database.base import async_session
    from sqlalchemy import select

    from aries.automations import run_automation
    from aries.news.models import AriesNewsItem
    from aries.settings import SettingsService

    if args.action == "scan":
        async with async_session() as db:
            if not await SettingsService(db).get("news.enabled"):
                print("news.enabled is off — ./scripts/aries settings-set news.enabled true")
                return 2
        out = await run_automation("aries.news", trigger="cli", force=args.force)
        if not out.get("ran"):
            print(_paint(f"did not run: {out.get('reason')}", COLOUR["warning"]))
            if out.get("breaker"):
                print(f"  {DIM}{out['breaker']['means']}{RESET}")
            return 1
        print(f"{BOLD}{out.get('summary') or out.get('verdict')}{RESET}")
        print(f"{DIM}task {out['task_id']} · {out['verdict']}{RESET}")
        return 0 if out["verdict"] == "pass" else 1

    async with async_session() as db:
        q = select(AriesNewsItem).order_by(AriesNewsItem.relevance.desc(),
                                           AriesNewsItem.id.desc())
        if args.action == "briefing":
            q = q.where(AriesNewsItem.disposition.in_(("delivered", "held")))
        elif args.action == "all":
            q = q.where(AriesNewsItem.is_representative.is_(True))
        rows = (await db.execute(q.limit(args.limit))).scalars().all()

    if not rows:
        print("\nNothing yet.  ./scripts/aries news scan\n")
        return 0
    print(f"\n{BOLD}News{RESET}\n")
    for r in rows:
        colour = (COLOUR["ok"] if r.disposition == "delivered" else
                  COLOUR["warning"] if r.disposition == "held" else "")
        tag = {"delivered": "shown", "held": "held", "below_threshold": "quiet",
               "excluded": "ignored", "duplicate": "dup"}.get(r.disposition, r.disposition)
        print(f"  {_paint(f'{r.relevance:.2f}', colour)} {DIM}{tag:8}{RESET} {r.title[:66]}")
        meta = f"{r.source_id}"
        if r.topics:
            meta += " · " + ", ".join(r.topics)
        if r.excluded_by:
            meta += f" · excluded by {r.excluded_by}"
        print(f"       {DIM}{meta}{RESET}")
        if r.link and r.disposition in ("delivered", "held"):
            print(f"       {DIM}{r.link[:74]}{RESET}")
    print()
    return 0


async def cmd_learning(args) -> int:
    await _bootstrap()
    from agentic_core.database.base import async_session

    from aries.automations import run_automation
    from aries.learning import gather, propose
    from aries.settings import SettingsService

    async with async_session() as db:
        if args.action == "evidence":
            ev = await gather(db)
            if not ev:
                print("\nNothing delivered yet — nothing to learn from.\n")
                return 0
            min_obs = int(await SettingsService(db).get("learning.min_observations"))
            print(f"\n{BOLD}What ARIES has seen{RESET}  {DIM}(needs {min_obs} items "
                  f"before a weight may move){RESET}\n")
            for e in sorted(ev.values(), key=lambda x: -x.shown):
                i = e.interval
                ready = "" if e.shown >= min_obs else _paint("  (not enough yet)", COLOUR["warning"])
                rate = "—" if i.point is None else f"{i.point:.0%}"
                print(f"  {BOLD}{e.topic:22}{RESET} shown {e.shown:>3}  opened {e.engaged:>3}  "
                      f"dismissed {e.dismissed:>3}   rate {rate:>4}  "
                      f"{DIM}[{i.lower:.0%}–{i.upper:.0%}]{RESET}{ready}")
            print()
            return 0

        if args.action == "feedback":
            from aries.learning import feedback as fb
            if args.text:
                ctx = {}
                if args.project:
                    ctx["project"] = args.project
                row = await fb.submit(db, args.text, context=ctx)
                d = row.as_dict()
                print()
                print(f"  heard: {BOLD}{d['classification']}{RESET}  "
                      f"{DIM}scope {d['scope']} · confidence {d['confidence']:.0%}{RESET}")
                print(f"  {DIM}{d['reason']}{RESET}")
                if d["ambiguous"]:
                    print()
                    print(f"  {_paint('?', COLOUR['warning'])} {d['question']}")
                    print(f"  {DIM}answer with:  ./scripts/aries learning answer "
                          f"--id {d['id']} --scope current_result|global{RESET}")
                elif d["applied"]:
                    a = d["action"]
                    print(f"  {_paint('applied', COLOUR['ok'])} {a['setting']} = "
                          f"{json.dumps(a['value'])}  {DIM}at the {d['layer']} layer{RESET}")
                elif d["action"]:
                    print(f"  {DIM}not applied{RESET}")
                print()
                return 0

            rows = await fb.recent(db, limit=args.limit, pending_only=args.pending)
            if not rows:
                print("\nNo feedback recorded.  ./scripts/aries learning feedback \"shorter\"\n")
                return 0
            print(f"\n{BOLD}Feedback{RESET}\n")
            for r in rows:
                d = r.as_dict()
                mark = (_paint("?", COLOUR["warning"]) if d["ambiguous"]
                        else _paint("✓", COLOUR["ok"]) if d["applied"] else " ")
                print(f"  {mark} {BOLD}\"{d['text'][:52]}\"{RESET}")
                print(f"      {d['classification']} · {d['scope']} · "
                      f"{DIM}{d['at'][:16].replace('T', ' ')}{RESET}")
                if d["ambiguous"]:
                    print(f"      {DIM}waiting: {d['question']}  (id {d['id']}){RESET}")
                elif d["action"]:
                    print(f"      {DIM}{d['action']['setting']} = "
                          f"{json.dumps(d['action']['value'])}{RESET}")
            print()
            return 0

        if args.action == "answer":
            from aries.learning import feedback as fb
            row = await fb.answer(db, args.id, scope=args.scope)
            d = row.as_dict()
            print(f"scope set to {d['scope']}"
                  + (f" — {d['action']['setting']} = {json.dumps(d['action']['value'])} "
                     f"at the {d['layer']} layer" if d["applied"] else ""))
            return 0

        if args.action == "preferences":
            from aries.learning import preferences as prefs
            p = await prefs(db)
            print(f"\n{BOLD}What ARIES believes{RESET}")
            print(f"{DIM}{p['means']}{RESET}\n")
            if p["settings"]:
                print(f"  {BOLD}Settings{RESET}")
                for x in p["settings"]:
                    tag = (_paint("you", COLOUR["ok"]) if x["explicit"]
                           else _paint("learned", COLOUR["notice"]))
                    print(f"    {x['key']:42} {json.dumps(x['value']):<22} {tag}")
                    if x["rationale"]:
                        print(f"    {'':42} {DIM}{x['rationale'][:70]}{RESET}")
            if p["topics"]:
                print(f"\n  {BOLD}Topics{RESET}")
                for t in p["topics"]:
                    tag = (_paint("you", COLOUR["ok"]) if t["explicit"]
                           else _paint(t["source"], COLOUR["notice"]))
                    stance = "✕" if t["stance"] == "avoid" else " "
                    print(f"    {stance} {t['topic']:24} {t['weight']:.2f}  {tag}")
            print()
            return 0

        if args.action == "explain":
            from aries.learning import explain as explain_one
            e = (await explain_one(db, args.target)).as_dict()
            if not e["available"]:
                print(f"\n  {e['because']}\n")
                return 1
            print(f"\n{BOLD}{e['subject']}{RESET}  {DIM}({e['kind']}){RESET}\n")
            print(f"  now      {BOLD}{json.dumps(e['value'])}{RESET}")
            print(f"  because  {e['because']}")
            print(f"  from     {e['source_label']} "
                  f"({_paint('explicit', COLOUR['ok']) if e['explicit'] else _paint('learned', COLOUR['notice'])})")
            print(f"  scope    {e['scope'] or 'everywhere'}")
            if e["confidence"] is not None:
                print(f"  sure     {e['confidence']:.0%}")
            if e["alternatives"]:
                print(f"\n  {BOLD}Also held{RESET}")
                for a in e["alternatives"]:
                    if a.get("layer") == e["source"]:
                        continue
                    r = f"  {DIM}{(a.get('rationale') or '')[:58]}{RESET}" if a.get("rationale") else ""
                    print(f"    {a.get('layer', '?'):14} {json.dumps(a.get('value'))}{r}")
            ev = e["evidence"] or {}
            if ev.get("overall"):
                o = ev["overall"]
                print(f"\n  {BOLD}Evidence{RESET}")
                print(f"    {o['engaged']}/{o['shown']} engaged over {ev.get('window_days')} days, "
                      f"interval [{o['lower']}, {o['upper']}], trend {ev.get('trend')}")
            elif ev.get("note"):
                print(f"\n  {DIM}{ev['note']}{RESET}")
            if e["history"]:
                print(f"\n  {BOLD}Changed{RESET}")
                for h in e["history"][:5]:
                    when = (h.get("at") or h.get("first_seen") or "")[:16].replace("T", " ")
                    if "from" in h:
                        print(f"    {when}  {h['from']:.2f} → {h['to']:.2f}  "
                              f"{DIM}{h.get('classification') or ''}{RESET}")
                    else:
                        print(f"    {when}  reversal {h.get('status')}  "
                              f"{DIM}{h.get('classification')}{RESET}")
            if e["feedback"]:
                print(f"\n  {BOLD}You said{RESET}")
                for f in e["feedback"][:4]:
                    print(f"    \"{f['text'][:56]}\"  {DIM}{f['classification']}{RESET}")
            print()
            return 0

        if args.action == "reversals":
            from aries.learning import history, reversal
            from aries.learning.loop import propose as _propose, verdicts_for
            from aries.interests import service as _ints

            props = await _propose(db)
            verdicts = {v["target"]: v for v in verdicts_for(props)}
            rows = await reversal.pending(db)
            rate = await reversal.rate(db)

            print(f"\n{BOLD}Reversals{RESET}  {DIM}policy {reversal.POLICY_VERSION}{RESET}")
            print(f"{DIM}an established learned preference may be taken back, but only on "
                  f"stronger evidence than it took to form{RESET}\n")

            contested = [v for v in verdicts.values()
                         if v["classification"] not in ("none", "agrees")]
            if not contested and not rows:
                print("  Nothing contested — every learned preference matches the evidence.\n")
                return 0

            for v in contested:
                row = await _ints.get(db, v["target"])
                learned = row.learned_weight if row else None
                colour = {"sustained": COLOUR["critical"], "fatigue": COLOUR["warning"],
                          "contextual": COLOUR["notice"], "temporary": COLOUR["warning"],
                          "noise": ""}.get(v["classification"], "")
                print(f"  {BOLD}{v['target']}{RESET}  {DIM}believes {learned:.2f}{RESET}"
                      if learned is not None else f"  {BOLD}{v['target']}{RESET}")
                print(f"     {_paint(v['classification'].upper(), colour)}  "
                      f"{DIM}confidence {v['confidence']:.0%}{RESET}")
                ovr = (v.get("evidence") or {}).get("overall") or {}
                if ovr:
                    print(f"     evidence: {ovr.get('engaged')}/{ovr.get('shown')} engaged, "
                          f"interval [{ovr.get('lower')}, {ovr.get('upper')}]")
                print(f"     {DIM}{v['reason']}{RESET}")
                pend = next((r for r in rows if r.target == v["target"]
                             and r.status == reversal.PENDING), None)
                if pend:
                    print(f"     {_paint('PENDING', COLOUR['warning'])} "
                          f"{pend.confirmations}/{pend.required_confirmations} confirmations")
                print()

            done = [r for r in rows if r.status != reversal.PENDING]
            if done:
                print(f"  {BOLD}Recently resolved{RESET}")
                for r in done[:8]:
                    mark = (_paint("applied", COLOUR["ok"]) if r.status == reversal.APPLIED
                            else _paint("withdrawn", COLOUR["warning"]))
                    when = r.resolved_at.strftime("%d %b %H:%M") if r.resolved_at else ""
                    print(f"    {mark:22} {r.target}  {r.established:.2f} → "
                          f"{(r.proposed if r.proposed is not None else r.established):.2f}"
                          f"  {DIM}{when}{RESET}")
                print()
            if rate["applied_rate"] is not None:
                print(f"  {DIM}{rate['total']} suspected, {rate['applied_rate']:.0%} applied — "
                      f"{rate['means']}{RESET}\n")
            return 0

        if args.action == "history":
            from aries.learning import history
            rows = await history.history(db, args.target or None, limit=args.limit)
            if not rows:
                print("\nNothing changed yet.\n")
                return 0
            print(f"\n{BOLD}What ARIES changed{RESET}\n")
            for r in rows:
                d = r.as_dict()
                arrow = "↑" if d["direction"] == "up" else "↓"
                flags = []
                if d["reversal"]:
                    flags.append(_paint("reversal", COLOUR["critical"]))
                if d["shadowed"]:
                    flags.append(_paint("shadowed", COLOUR["warning"]))
                print(f"  {arrow} {BOLD}{d['target']}{RESET}  {d['from']:.2f} → {d['to']:.2f}"
                      + ("  " + " ".join(flags) if flags else ""))
                print(f"     {DIM}{d['at'][:16].replace('T', ' ')} · {d['classification'] or 'ordinary'}"
                      f" · {d['policy_version']}{RESET}")
                print(f"     {DIM}{d['rationale'][:110]}{RESET}")
            print()
            return 0

        if args.action == "propose":
            props = await propose(db)
            if not props:
                print("\nNo change — the evidence is not yet decisive.\n")
                return 0
            print(f"\n{BOLD}What ARIES would change{RESET}  {DIM}(nothing written){RESET}\n")
            for p in props:
                arrow = "↑" if p.direction == "up" else "↓"
                colour = COLOUR["ok"] if p.direction == "up" else COLOUR["warning"]
                print(f"  {_paint(arrow, colour)} {BOLD}{p.target}{RESET}  "
                      f"{p.current:.2f} → {p.proposed:.2f}  {DIM}confidence {p.confidence:.0%}{RESET}")
                print(f"     {DIM}{p.rationale}{RESET}")
            print()
            return 0

    out = await run_automation("aries.learning", trigger="cli", force=args.force)
    if not out.get("ran"):
        print(_paint(f"did not run: {out.get('reason')}", COLOUR["warning"]))
        return 1
    print(out.get("summary") or out.get("verdict"))
    return 0


async def cmd_brief(args) -> int:
    await _bootstrap()
    from agentic_core.database.base import async_session
    from sqlalchemy import select

    from aries.automations import run_automation
    from aries.brief.models import AriesBrief
    from aries.brief.render import render
    from aries.brief.sections import Item, Section

    if args.action == "generate":
        out = await run_automation("aries.brief", trigger="cli", force=True)
        if not out.get("ran"):
            print(_paint(f"did not run: {out.get('reason')}", COLOUR["warning"]))
            return 1
        if out.get("verdict") != "pass":
            print(_paint(f"the brief failed: {out.get('summary')}", COLOUR["critical"]))
            return 1

    async with async_session() as db:
        row = (await db.execute(select(AriesBrief).order_by(
            AriesBrief.id.desc()).limit(1))).scalar_one_or_none()
        if row is None:
            print("\nNo brief yet.  ./scripts/aries brief generate\n")
            return 0
        if args.length and args.length != row.length:
            # Re-render the stored sections at a different length, without
            # collecting again — the sections are kept for exactly this.
            secs = [Section(s["name"], s["title"],
                            [Item(**{k: v for k, v in i.items() if k != "meta"},
                                  meta=i.get("meta", {})) for i in s["items"]],
                            summary=s.get("summary", ""), severity=s.get("severity", "info"),
                            unavailable=s.get("unavailable"))
                    for s in row.sections]
            # created_at is UTC (the database writes it); the brief's timestamp is
            # a statement about the user's morning, so it is shown in LOCAL time.
            # Formatting the UTC value directly made a re-rendered brief claim it
            # was produced two hours before it was — the same two-clocks mistake
            # as the notification cooldown in Entry 003.
            from datetime import datetime, timezone
            when = ""
            if row.created_at:
                local = row.created_at.replace(tzinfo=timezone.utc).astimezone()
                when = local.strftime("%a %d %b, %H:%M")
            text = render(secs, length=args.length, colour=_TTY, when=when)
        else:
            text = row.rendered
        if not row.seen:
            row.seen = True
            await db.commit()

    print()
    print(text)
    print()
    return 0


async def cmd_runtime(args) -> int:
    """status / start / stop / restart — ARIES as part of the environment.

    Deliberately does NOT open the database or import the rest of ARIES. This is
    the command asked when something is wrong, so it must answer when ARIES is
    stopped, starting, wedged or fine — and anything it needed from a running
    ARIES would be exactly what is missing.
    """
    from aries.runtime import MEANING, describe, systemd

    base = os.environ.get("ARIES_API", "http://127.0.0.1:8000")

    if args.command in ("start", "stop", "restart"):
        action = {"start": systemd.start, "stop": systemd.stop,
                  "restart": systemd.restart}[args.command]
        ok, message = action()
        if not ok:
            print(_paint(f"could not {args.command} ARIES: {message}", COLOUR["critical"]))
            return 1
        print({"start": "started", "stop": "stopped",
               "restart": "restarted"}[args.command] + " ARIES")
        if args.command != "stop":
            import time
            for _ in range(20):
                time.sleep(0.5)
                if describe(base=base).state in ("RUNNING", "DEGRADED"):
                    break
        print()

    st = describe(base=base)
    colour = {"RUNNING": COLOUR["ok"], "DEGRADED": COLOUR["warning"],
              "STARTING": COLOUR["notice"], "STOPPED": ""}[st.state]
    print(f"  {_paint(st.state, colour)}  {DIM}{MEANING[st.state]}{RESET}")
    print(f"  {st.summary}")
    print()

    if not st.installed:
        print(f"  {DIM}install it so ARIES starts with your session:{RESET}")
        print("      ./scripts/aries-service install")
        print()
        return 0 if st.state == "RUNNING" else 1

    print(f"  {'enabled at login' if st.enabled else _paint('NOT enabled at login', COLOUR['warning'])}"
          f"{DIM} · api {'reachable' if st.api_reachable else 'not answering'} at {base}{RESET}")

    if st.components:
        print()
        for c in st.components:
            tick = (_paint("  ok  ", COLOUR["ok"]) if c.ok
                    else _paint(c.severity.upper().center(6), COLOUR.get(c.severity, "")))
            print(f"  {tick} {c.name:24} {DIM}{c.kind:11} {c.detail[:58]}{RESET}")

    if args.logs:
        print()
        print(f"{BOLD}Recent log{RESET}")
        for line in systemd.logs(args.logs).splitlines()[-args.logs:]:
            print(f"  {DIM}{line[:140]}{RESET}")
    print()
    return 0 if st.state in ("RUNNING", "STARTING") else 1


async def cmd_version(args) -> int:
    """Which revision is RUNNING — not which one is checked out.

    Entry 016 was verified three times against a shell holding code from hours
    earlier, and nothing in the system could have said so. This is the answer to
    "is the thing running the thing I just changed?", which is a different
    question from "what version is ARIES" and the one that was missing.
    """
    from aries.runtime.version import describe

    info = describe()
    src = info["source"]
    print(f"\n{BOLD}ARIES {info['aries']}{RESET}\n")
    print(f"  source            {src['described']}")
    print(f"  working tree      " + ("dirty" if src["dirty"] else "clean"))
    print(f"  shell build       {src['shell_build']}")
    print(f"  control centre    {src['control_centre_build']}")

    if info["installed"]:
        print(f"\n{BOLD}Installed{RESET}\n")
        for path, build in info["installed"].items():
            same = build == src["shell_build"]
            mark = _paint("same as source", COLOUR["ok"]) if same else \
                _paint("DIFFERENT from source", COLOUR["warning"])
            print(f"  {path}")
            print(f"      {build}  {mark}")
    else:
        print(f"\n  {DIM}the shell is not installed anywhere{RESET}")

    # The running shell, which is the one that actually matters.
    running = None
    try:
        out = subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.aries.Shell",
             "--object-path", "/org/aries/Shell", "--method", "org.aries.Shell.Ping"],
            capture_output=True, text=True, timeout=5).stdout
        if '"build":"' in out:
            running = out.split('"build":"')[1].split('"')[0]
    except (OSError, subprocess.SubprocessError):
        pass

    print(f"\n{BOLD}Running{RESET}\n")
    if running is None:
        print(f"  {DIM}the ARIES shell is not answering — not in the ARIES session,{RESET}")
        print(f"  {DIM}or it predates build stamping (log out and back in){RESET}")
    elif running == src["shell_build"]:
        print(f"  shell             {running}  "
              + _paint("is the source revision", COLOUR["ok"]))
    else:
        print(f"  shell             {running}  "
              + _paint("is NOT the source revision", COLOUR["warning"]))
        print(f"  {DIM}extensions do not reload — install, then log out and back in{RESET}")
    print()
    return 0


async def cmd_power(args) -> int:
    await _bootstrap()
    from agentic_core.database.base import async_session

    from aries.power import reconcile, snapshot
    from aries.settings import SettingsService

    async with async_session() as db:
        if args.action == "events":
            from aries.power.governor import recent_events
            rows = await recent_events(db, 25)
        if args.action in ("on", "off"):
            await SettingsService(db).set("power.background_mode", args.action == "on",
                                          set_by="user")
            await reconcile(db, reason="cli")
        snap = await snapshot(db)

    if args.action == "events":
        print(f"\n{BOLD}Resource policy decisions{RESET}\n")
        if not rows:
            print(f"  {DIM}nothing recorded — no heavy work has been refused or released{RESET}\n")
            return 0
        for row in rows:
            tint = COLOUR["ok"] if row["kind"] == "resumed" else COLOUR["warning"]
            when = (row["at"] or "")[:16].replace("T", " ")
            kind = f"{row['kind']:<11}"
            wl = f"{row['workload']:<15}"
            print(f"  {DIM}{when}{RESET}  {_paint(kind, tint)} {wl} {row['reason'][:90]}")
        print()
        return 0

    mode = snap["background_mode"]
    inh = snap["inhibitor"]
    disp = snap["display"]

    print(f"\n{BOLD}Power and Background{RESET}\n")
    print(f"  Background Mode    {_paint('on', COLOUR['ok']) if mode else 'off'}")
    print(f"  Suspend inhibitor  "
          + (_paint("active", COLOUR["ok"]) if inh["active"] else "inactive")
          + f"   {DIM}{inh['what']}/{inh['mode']}{RESET}")
    print(f"  Display            {disp['state']}  {DIM}{disp['detail']}{RESET}")
    off_after = disp["off_after_seconds"]
    print(f"  Display off after  "
          + ("never" if off_after == 0 else f"{off_after // 60} min" if off_after else "unknown"))
    session = snap["system"]["session"]
    print(f"  System             awake"
          + (f"  {DIM}session {session.get('id')} · {'idle' if session.get('idle') else 'active'}{RESET}"
             if session.get("available") else ""))
    print()
    print(f"  {DIM}{snap['effect']}{RESET}")

    if inh["held_by_aries"]:
        print()
        for row in inh["held_by_aries"]:
            print(f"  {DIM}held: {row['line'][:110]}{RESET}")
    if inh["other_sleep_blockers"]:
        print()
        print(f"  {DIM}other processes also blocking sleep:{RESET}")
        for row in inh["other_sleep_blockers"][:4]:
            print(f"  {DIM}  {row[:108]}{RESET}")
    if not inh["available"]:
        print()
        print(_paint(f"  {inh['unavailable_reason']}", COLOUR["warning"]))

    res = snap.get("resources") or {}
    m, lim = res.get("measurement") or {}, res.get("limits") or {}
    if m:
        print(f"\n{BOLD}Resource policy{RESET}\n")
        print(f"  CPU                {_reading(m['cpu_pct'], '%', m['cpu_unavailable'])}"
              f"   {DIM}limit {lim.get('cpu_pct')} %{RESET}")
        print(f"  GPU                {_reading(m['gpu_pct'], '%', m['gpu_unavailable'])}"
              f"   {DIM}limit {lim.get('gpu_pct')} %{RESET}")
        print(f"  Temperature        "
              f"{_reading(m['temperature_celsius'], ' °C', m['temperature_unavailable'])}"
              f"   {DIM}limit {lim.get('temperature_celsius')} °C"
              + (f" · {m['temperature_subject']}" if m.get("temperature_subject") else "")
              + RESET)
        print(f"  Heavy job budget   {lim.get('heavy_job_max_minutes')} min")
        print()
        for cls in res.get("classes") or []:
            tint = COLOUR["ok"] if cls["status"] == "allowed" else COLOUR["warning"]
            print(f"  {cls['title']:<24} {_paint(cls['status'], tint)}  {DIM}{cls['why']}{RESET}")
        for job in res.get("running_heavy") or []:
            print(f"\n  {DIM}running: {job['automation_id']} · "
                  f"{job['elapsed_seconds'] / 60:.0f} min{RESET}")
    print()
    return 0


def _reading(value, unit: str, unavailable: str | None) -> str:
    """A number, or why there is not one. Never a zero standing in for unknown."""
    if value is None:
        return _paint(f"unknown  {unavailable or ''}".rstrip(), COLOUR.get("notice", ""))
    return f"{value:g}{unit}"


async def cmd_settings(args) -> int:
    await _bootstrap()
    from agentic_core.database.base import async_session

    from aries.settings import SettingsService, all_defs
    async with async_session() as db:
        s = SettingsService(db)
        defs = [d for d in all_defs() if not args.prefix or d.key.startswith(args.prefix)]
        section = None
        for d in defs:
            if d.section != section:
                section = d.section
                print(f"\n{BOLD}{section.upper()}{RESET}")
            e = await s.explain(d.key)
            origin = "" if e["source"] == "default" else f"  {DIM}← {e['source_label']}{RESET}"
            print(f"  {d.key:44} {json.dumps(e['value'], default=str):<28}{origin}")
    print()
    return 0


async def cmd_settings_set(args) -> int:
    await _bootstrap()
    from agentic_core.database.base import async_session

    from aries.settings import SettingsService
    try:
        value = json.loads(args.value)
    except ValueError:
        value = args.value
    async with async_session() as db:
        out = await SettingsService(db).set(args.key, value, set_by="user")
    print(f"{args.key} = {json.dumps(out['effective'], default=str)}"
          + (f"  ({out['note']})" if out.get("note") else ""))
    return 0


def _bytes(n: int) -> str:
    return f"{n / 1_048_576:.2f} MB" if n >= 1_048_576 else f"{n / 1024:.0f} kB"


async def cmd_data(args) -> int:
    """What ARIES is holding, what it would remove, and removing it.

    `status` and `preview` never write. `clean` honours `data.dry_run_first`,
    so the first invocation rehearses even here — the CLI is not a way around
    the rehearsal, it is just another caller of the same service.
    """
    await _bootstrap()
    from agentic_core.database.base import async_session

    from aries.lifecycle import policy, service, working

    async with async_session() as db:
        if args.action == "sweep":
            out = await working.sweep(db)
            await db.commit()
            print(f"swept {out['swept']} orphaned working-set row(s)"
                  + (f" from {len(out['tasks'])} dead task(s)" if out["tasks"] else ""))
            return 0

        if args.action == "vacuum":
            out = await service.vacuum(db)
            print(f"{_bytes(out['before_bytes'])} → {_bytes(out['after_bytes'])}"
                  f"  {DIM}reclaimed {_bytes(out['reclaimed_bytes'])}{RESET}")
            return 0

        if args.action == "clean":
            out = await service.apply(db, force=args.force)
            held = await working.summary(db)
        else:
            out = await service.preview(db)
            held = await working.summary(db)

    if args.json:
        print(json.dumps({**out, "working_set": held}, indent=2, default=str))
        return 0

    verb = "removed" if args.action == "clean" else "would remove"
    print(f"\n{BOLD}Data{RESET}  {DIM}{_bytes(out['database_bytes'])} on disk{RESET}\n")

    by_kind: dict[str, list[dict]] = {}
    for line in out["tables"]:
        by_kind.setdefault(line["kind"], []).append(line)

    for kind in (policy.WORKING, policy.OPERATIONAL, policy.MEMORY,
                 policy.PROVENANCE, policy.AUDIT):
        lines = by_kind.get(kind)
        if not lines:
            continue
        print(f"  {BOLD}{kind.upper()}{RESET}")
        for line in sorted(lines, key=lambda r: -r["would_remove"]):
            n = line["would_remove"]
            tail = (_paint(f"{verb} {n}", COLOUR["warning"]) if n
                    else _paint("nothing to remove", COLOUR["ok"]))
            print(f"    {line['table']:<26} {line['present']:>7} rows   {tail}")
            print(f"      {DIM}{line['why']}{RESET}")
        print()

    print(f"  {BOLD}WORKING SET{RESET}")
    if held["held"]:
        print(f"    {held['held']} item(s), {_bytes(held['bytes'])}, "
              f"for {len(held['tasks'])} live task(s)"
              + (f"  {DIM}{held['sensitive']} marked sensitive{RESET}"
                 if held["sensitive"] else ""))
    else:
        print(f"    {DIM}nothing held — no task is currently reading anything{RESET}")

    print()
    if out.get("note"):
        print(f"  {_paint(out['note'], COLOUR['notice'])}")
    elif args.action == "clean":
        print(f"  {out['removed']} row(s) removed."
              + ("  Run `aries data vacuum` to give the space back." if out["removed"] else ""))
    else:
        print(f"  {out['would_remove']} row(s) are past their window.  "
              f"{DIM}`aries data clean` removes them.{RESET}")
    print()
    return 0


VERDICT_COLOUR = {"met": "ok", "unmet": "critical", "unverifiable": "notice"}
OUTCOME_COLOUR = {"done": "ok", "failed": "critical", "unconfirmed": "notice",
                  "proposed": "notice", "refused": "warning"}


async def cmd_do(args) -> int:
    """Ask ARIES to do something, and be told what it could actually confirm.

    Two facts are printed for every step and never merged: what the tool
    reported, and what ARIES saw afterwards. The second one is the answer.
    """
    await _bootstrap()
    from agentic_core.database.base import async_session

    from aries.operator import goals, service

    request = " ".join(args.request).strip()
    async with async_session() as db:
        run = await service.run(db, request, dry_run=args.dry_run, approve=args.yes)
    out = run.as_dict()

    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0 if out["outcome"] in ("done", "proposed") else 1

    print()
    plan = out["plan"]
    if plan["steps"]:
        origin = ("an exact match" if plan["source"] == "router"
                  else f"the local model ({plan['model']})" if plan["model"]
                  else plan["source"])
        print(f"  {DIM}understood by {origin}{RESET}")
        for i, step in enumerate(plan["steps"], 1):
            goal = goals.get(step["goal"])
            said = goal.describe(step["params"]) if goal else step["goal"]
            print(f"  {i}. {said}")
        print()

    for step in out["steps"]:
        v = step["verification"]
        tint = COLOUR[VERDICT_COLOUR.get(v["verdict"], "notice")]
        print(f"  {_paint(v['verdict'].upper(), tint)}  {DIM}{v['grade']}{RESET}")
        print(f"     {DIM}the tool said:{RESET} "
              + ("succeeded" if step["reported"] else "failed")
              + (f" {DIM}— {step['report_detail'][:70]}{RESET}" if step["report_detail"] else ""))
        print(f"     {DIM}ARIES checked:{RESET} {v['checked']}")
        print(f"     {DIM}and found    :{RESET} {v['found'][:140]}")
        print(f"     {DIM}{step['seconds']}s, {step['observations']} look(s){RESET}")
        print()

    tint = COLOUR[OUTCOME_COLOUR.get(out["outcome"], "notice")]
    print(f"  {_paint(out['outcome'].upper(), tint)}  {out['summary']}")

    if out["outcome"] == "proposed":
        print(f"  {DIM}run it with:  aries do --yes {request!r}{RESET}")
    if out["honesty_gap"]:
        # The measurement this milestone exists to make, said out loud rather
        # than left in a JSON field nobody reads.
        print(f"  {_paint('the tool claimed success and the desktop disagrees', COLOUR['critical'])}")
    for alt in plan.get("alternatives") or []:
        print(f"  {DIM}· {alt.get('title')}   {alt.get('example') or ''}{RESET}")
    print()
    return 0 if out["outcome"] in ("done", "proposed") else 1


async def cmd_connect(args) -> int:
    """The Integrations layer: what is connected, and reading from it.

    A credential is NEVER a command-line argument. `/proc/<pid>/cmdline` is
    world-readable, and shell history keeps it forever — so a password typed as
    an argument is a password on disk and visible to every process on the
    machine. It is read from a terminal prompt, or from stdin for a script.
    """
    await _bootstrap()
    from agentic_core.database.base import async_session

    from aries.connect import base, secrets, service
    from aries.sources import service as sources, types

    async with async_session() as db:
        if args.action == "add":
            secret = None
            if types.require(args.type).requires_credentials:
                secret = _read_secret(args.secret_stdin)
            try:
                out = await service.connect(db, type=args.type, name=args.name,
                                            location=args.location, secret=secret)
            except (service.NotConnected, secrets.NoKeyring, ValueError) as exc:
                print(_paint(f"  {exc}", COLOUR["critical"]))
                return 1
            health = out["health"]
            tint = COLOUR["ok"] if health["reachable"] else COLOUR["warning"]
            print(f"\n  connected {BOLD}{out['source']['source_id']}{RESET}")
            print(f"  {_paint(health['detail'], tint)}")
            cred = out["credential"]
            if cred.get("reference"):
                print(f"  {DIM}credential stored in {cred['where']} as {cred['reference']}{RESET}")
            print()
            return 0 if health["reachable"] else 1

        if args.action == "remove":
            out = await service.disconnect(db, args.source_id)
            print(f"  removed {out['removed']}"
                  + ("  (credential forgotten)" if out["credential_forgotten"] else ""))
            return 0

        if args.action == "check":
            health = await service.check(db, args.source_id)
            tint = COLOUR["ok"] if health["reachable"] else COLOUR["critical"]
            print(f"  {_paint('reachable' if health['reachable'] else 'not reachable', tint)}"
                  f"  {health['detail']}")
            return 0 if health["reachable"] else 1

        if args.action in ("read", "search"):
            task_id = f"cli-{int(time.time() * 1000)}"
            try:
                if args.action == "read":
                    out = await service.read(db, args.source_id, task_id=task_id)
                else:
                    out = await service.search(db, args.source_id, args.query or "",
                                               task_id=task_id)
            except service.NotConnected as exc:
                print(_paint(f"  {exc}", COLOUR["critical"]))
                return 1
            print(f"\n  {BOLD}{out['count']}{RESET} item(s) from {args.source_id}\n")
            for item in out["items"][:20]:
                print(f"  {item['title'][:70]:<72} {DIM}{item['bytes']:>7} bytes{RESET}")
            for flag in out.get("injection_attempts") or []:
                print(f"\n  {_paint('CONTENT AIMED AT THE ASSISTANT', COLOUR['critical'])}"
                      f"  {flag['title'][:60]}")
                for attempt in flag["attempts"]:
                    print(f"    {DIM}{attempt['why']}: {attempt['excerpt'][:70]}{RESET}")
            print(f"\n  {DIM}bodies are in the working set under {task_id} and are"
                  f" released when the task ends{RESET}\n")
            # The CLI is the task. Releasing here is what makes that true.
            from aries.lifecycle import working
            await working.release(db, task_id)
            await db.commit()
            return 0

        # status
        rows = await sources.list_sources(db)
        ok, detail = secrets.available()
        print(f"\n{BOLD}Connected sources{RESET}   "
              f"{DIM}keyring: {detail if ok else 'NONE — credentials cannot be stored'}{RESET}\n")
        by_type: dict[str, list] = {}
        for row in rows:
            by_type.setdefault(row.type, []).append(row)
        for type_name in sorted(by_type):
            readable = base.have(type_name)
            mark = _paint("readable", COLOUR["ok"]) if readable else _paint(
                "no connector", COLOUR["notice"])
            print(f"  {BOLD}{type_name}{RESET}  {mark}")
            for row in by_type[type_name]:
                state = "on" if row.enabled else "off"
                print(f"    {row.source_id:<24} {state:<4} {DIM}{row.location[:60]}{RESET}")
            print()
        if not rows:
            print(f"  {DIM}nothing connected yet — "
                  f"aries connect add directory Notes ~/Documents/notes{RESET}\n")
        return 0


def _read_secret(from_stdin: bool) -> str:
    """A credential, from a prompt or a pipe. Never from argv."""
    import getpass
    if from_stdin or not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\n")
    return getpass.getpass("  password (not echoed, goes straight to the keyring): ")


async def cmd_attention(args) -> int:
    """Read the connected sources and say what needs you."""
    await _bootstrap()
    from aries.automations.runner import run_automation

    out = await run_automation("aries.attention", trigger="manual", force=True)
    if not out.get("ran"):
        print(_paint(f"  {out.get('reason')}", COLOUR["warning"]))
        return 1

    from agentic_core.database.base import async_session
    from agentic_core.orchestrator.service import get_task
    async with async_session() as db:
        task = await get_task(db, out["task_id"]) if out.get("task_id") else None
    result = (task.output or {}).get("result") if task and task.output else {}
    result = result or {}

    print(f"\n{BOLD}Attention{RESET}  {DIM}{out.get('summary') or ''}{RESET}\n")
    for item in result.get("needs_you") or []:
        tint = COLOUR["critical"] if item.get("suspicious") else COLOUR["warning"]
        print(f"  {_paint('•', tint)} {BOLD}{item['title'][:70]}{RESET}")
        print(f"    {item.get('summary') or ''}"[:160])
        print(f"    {DIM}{item.get('category')} · {item.get('urgency')} · "
              f"{item.get('source_id')}{RESET}")
        for attempt in item.get("injection_attempts") or []:
            print(f"    {_paint('tried to instruct ARIES:', COLOUR['critical'])} "
                  f"{DIM}{attempt['why']}{RESET}")
        print()
    if result.get("can_wait"):
        print(f"  {DIM}{len(result['can_wait'])} more can wait{RESET}")
    for failure in result.get("failures") or []:
        print(f"  {_paint(failure['why'][:110], COLOUR['warning'])}")
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aries", description="ARIES command line")
    sub = p.add_subparsers(dest="command", required=True)

    for name, help_text in (("status", "is ARIES running?"),
                            ("start", "start ARIES"),
                            ("stop", "stop ARIES"),
                            ("restart", "restart ARIES")):
        rp = sub.add_parser(name, help=help_text)
        rp.add_argument("--logs", type=int, default=0, metavar="N",
                        help="also show the last N journal lines")
        rp.set_defaults(fn=cmd_runtime, command=name)

    sub.add_parser("version", help="which revision is running, and is it the source one")\
       .set_defaults(fn=cmd_version, command="version")

    pw = sub.add_parser("power", help="Background Mode, the suspend inhibitor and the "
                                      "resource policy")
    pw.add_argument("action", nargs="?", default="status",
                    choices=["status", "on", "off", "events"])
    pw.set_defaults(fn=cmd_power)

    cc = sub.add_parser("connect", help="folders and mailboxes ARIES may read (§21/§23)")
    cc.add_argument("action", nargs="?", default="status",
                    choices=["status", "add", "remove", "check", "read", "search"])
    cc.add_argument("type", nargs="?", default="", help="directory · documents · repository · email")
    cc.add_argument("name", nargs="?", default="")
    cc.add_argument("location", nargs="?", default="")
    cc.add_argument("--source-id", default="", help="for check/read/search/remove")
    cc.add_argument("--query", default="", help="for search")
    cc.add_argument("--secret-stdin", action="store_true",
                    help="read the credential from stdin instead of prompting")
    cc.set_defaults(fn=cmd_connect)

    at = sub.add_parser("attention", help="read the connected sources and say what needs you")
    at.set_defaults(fn=cmd_attention)

    do = sub.add_parser("do", help="ask ARIES to do something, and be told what it "
                                   "could actually confirm")
    do.add_argument("request", nargs="+", help="what you want, in words")
    do.add_argument("--yes", action="store_true",
                    help="carry out a plan the model made, without confirming first")
    do.add_argument("--dry-run", action="store_true",
                    help="plan and check the current state; change nothing")
    do.add_argument("--json", action="store_true")
    do.set_defaults(fn=cmd_do)

    dc = sub.add_parser("data", help="what ARIES keeps, for how long, and removing "
                                     "what is past its window")
    dc.add_argument("action", nargs="?", default="status",
                    choices=["status", "preview", "clean", "vacuum", "sweep"])
    dc.add_argument("--force", action="store_true",
                    help="skip the rehearsal and delete on this pass")
    dc.add_argument("--json", action="store_true")
    dc.set_defaults(fn=cmd_data)

    h = sub.add_parser("health", help="run one system health pass")
    h.add_argument("--json", action="store_true", help="print the raw result")
    h.set_defaults(fn=cmd_health)

    a = sub.add_parser("automations", help="what is registered, enabled and due")
    a.set_defaults(fn=cmd_automations)

    w = sub.add_parser("worker", help="the automations dispatcher: status, or run one tick")
    w.add_argument("--tick", action="store_true", help="run one dispatcher pass now")
    w.set_defaults(fn=cmd_worker)

    sc = sub.add_parser("sources", help="the Sources Registry (§24)")
    sc.add_argument("action", nargs="?", default="list",
                    choices=["list", "catalogue", "add-from", "types", "add", "rm", "resolve"])
    sc.add_argument("source_id", nargs="?", help="for: rm, add-from")
    sc.add_argument("--category", default="", help="catalogue: ai, tech, security, …")
    sc.add_argument("--language", default="", help="catalogue: en, mk, …")
    sc.add_argument("--search", default="", help="catalogue: match name, description or topic")
    sc.add_argument("--name", default="")
    sc.add_argument("--type", default=None)
    sc.add_argument("--location", default="")
    sc.add_argument("--topics", default="", help="comma separated")
    sc.add_argument("--priority", default="normal", choices=["low", "normal", "high"])
    sc.add_argument("--trust", default="normal",
                    choices=["blocked", "untrusted", "normal", "trusted"])
    sc.add_argument("--capability", default="read", choices=["read", "search", "listen"])
    sc.set_defaults(fn=cmd_sources)

    ic = sub.add_parser("interests", help="the Personal Interest Profile (§25)")
    ic.add_argument("action", nargs="?", default="list", choices=["list", "add", "rm", "score"])
    ic.add_argument("--topic", default="", help="the topic, or the text to score")
    ic.add_argument("--stance", default="want", choices=["want", "avoid"])
    ic.add_argument("--weight", type=float, default=None)
    ic.add_argument("--synonyms", default="", help="comma separated")
    ic.set_defaults(fn=cmd_interests)

    nc = sub.add_parser("news", help="the News Radar (§13/03)")
    nc.add_argument("action", nargs="?", default="briefing",
                    choices=["briefing", "all", "scan"])
    nc.add_argument("--limit", type=int, default=15)
    nc.add_argument("--force", action="store_true", help="scan even if disabled")
    nc.set_defaults(fn=cmd_news)

    lc = sub.add_parser("learning", help="the medium learning loop (§16)")
    lc.add_argument("action", nargs="?", default="evidence",
                    choices=["evidence", "propose", "run", "reversals", "history",
                             "feedback", "answer", "preferences", "explain"])
    lc.add_argument("--force", action="store_true")
    lc.add_argument("target", nargs="?", default="", help="explain: a setting key or topic")
    lc.add_argument("--text", default="", help="feedback: what you want to say")
    lc.add_argument("--project", default="", help="feedback: the project it is about")
    lc.add_argument("--id", type=int, default=0, help="answer: the feedback id")
    lc.add_argument("--scope", default="global",
                    choices=["current_result", "current_task", "current_workflow",
                             "project", "automation", "domain", "global"])
    lc.add_argument("--pending", action="store_true", help="feedback: only unanswered")
    lc.add_argument("--limit", type=int, default=20)
    lc.set_defaults(fn=cmd_learning)

    bc = sub.add_parser("brief", help="the Morning Brief (§13/01)")
    bc.add_argument("action", nargs="?", default="show", choices=["show", "generate"])
    bc.add_argument("--length", default="", choices=["", "headlines", "standard", "detailed"],
                    help="re-render the stored brief at a different length")
    bc.set_defaults(fn=cmd_brief)

    s = sub.add_parser("settings", help="resolved settings and where each came from")
    s.add_argument("prefix", nargs="?", default="", help="only keys under this dot-path prefix")
    s.set_defaults(fn=cmd_settings)

    ss = sub.add_parser("settings-set", help="set a setting as the user")
    ss.add_argument("key")
    ss.add_argument("value")
    ss.set_defaults(fn=cmd_settings_set)

    args = p.parse_args(argv)
    return asyncio.run(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
