#!/usr/bin/env python3
"""Frozen production next-action planning, without capability execution.

Default: validate/capture the 24 exact production prompts, making no model calls.
--execute requires the root agent's released measurement window ID. Every run
gets a new directory; raw outputs, failures and prior runs are never overwritten.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import sys
import time

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parent


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def verify_source(source, manifest):
    actual = {name: sha(source / name) for name in manifest["files"]}
    differences = [name for name, value in actual.items() if value != manifest["files"][name]]
    if differences:
        raise RuntimeError("Frozen source differs: " + repr(differences[:8]))
    return {"files": len(actual), "manifest_sha256": sha(PACKAGE / "source-manifest.json"),
            "verified_at": stamp(), "matched": True}


def configure(out, source, protocol):
    values = {
        "APP_ENV": "test", "DATABASE_URL": "sqlite+aiosqlite:///" + str(out / "planner.sqlite3"),
        "DATA_DIR": str(out / "runtime"), "RUNTIME_STORE": str(out / "runtime/state.json"),
        "CONTEXT_DIR": str(out / "runtime/context"), "API_KEY": "", "CREDENTIALS_KEY": "",
        "AI_PROVIDER": "ollama", "DRY_RUN": "true", "LIVE_TOOLS": "",
        "ARIES_FLAG_FILE": str(out / "flags.env"), "ARIES_PRIMARY_LANG": "en",
        "SCHEDULER_ENABLED": "false", "LEARNING_NIGHTLY_ENABLED": "false",
        **protocol["flags"],
    }
    os.environ.update(values)
    for key in ("ARIES_CLOUD_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        os.environ[key] = ""
    (out / "runtime").mkdir()
    (out / "flags.env").write_text("# Private planner evaluation; no shared overrides.\n")
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(source), str(source / "vendor"), str(source / "vendor/agentic-core")]
    os.chdir(source)
    return values


def planner_data(case):
    history = deepcopy(case["history"])
    return {
        "routing": {"execution_level": "local", "reason": "Prespecified offline planner evaluation",
                    "no_fallback": True},
        "steps": history,
        "evidence": ([{"evidence_id": "fixture-browser-open-evidence", "verified": True,
                       "synthetic": True}] if history else []),
        "agent": {
            "contract": {"supported": False, "requirements": [],
                         "reason": "Offline next-action evaluation; no completion-contract hints supplied."},
            "context": {},
            "environment": {"fixture_precondition": case["precondition"],
                            "source": "synthetic frozen evaluation fixture; not current OS observations"},
        },
    }


def normalized(decision):
    return {key: decision[key] for key in ("action", "capability", "arguments")}


def scores(decision, expected):
    same_capability = decision["action"] == expected["action"] and decision["capability"] == expected["capability"]
    return {"schema_valid": True, "capability_correct": same_capability,
            "capability_arguments_correct": same_capability and decision["arguments"] == expected["arguments"]}


def summarize(rows, fixture, protocol, complete):
    planned = len(fixture) * protocol["repetitions"]
    metrics = ("schema_valid", "capability_correct", "capability_arguments_correct")

    def group(items, denominator):
        return {"attempted": len(items), "denominator": denominator,
                **{key: {"correct": sum(bool(r["scores"][key]) for r in items),
                         "denominator": denominator} for key in metrics}}

    by_id = {case["id"]: [r for r in rows if r["case_id"] == case["id"]] for case in fixture}
    consistency = [{"case_id": case_id, "attempts": len(items),
                    "all_valid": len(items) == protocol["repetitions"] and all(r["scores"]["schema_valid"] for r in items),
                    "identical_valid_decisions": len(items) == protocol["repetitions"]
                    and all(r["scores"]["schema_valid"] for r in items)
                    and len({digest(normalized(r["decision"])) for r in items}) == 1}
                   for case_id, items in by_id.items()]
    return {
        "completed_at": stamp(), "complete": complete, "measurement": "offline next-action selection; no execution",
        "distinct_cases": len(fixture), "planned_attempts": planned,
        "overall": group(rows, planned),
        "per_repetition": {str(rep): group([r for r in rows if r["repetition"] == rep], len(fixture))
                           for rep in range(1, protocol["repetitions"] + 1)},
        "per_language": {lang: group([r for r in rows if r["language"] == lang],
                                    sum(c["language"] == lang for c in fixture) * protocol["repetitions"])
                         for lang in sorted({c["language"] for c in fixture})},
        "per_category": {cat: group([r for r in rows if r["category"] == cat],
                                   sum(c["category"] == cat for c in fixture) * protocol["repetitions"])
                         for cat in sorted({c["category"] for c in fixture})},
        "consistency": consistency,
        "all_three_identical_valid_cases": sum(c["identical_valid_decisions"] for c in consistency),
        "latency_seconds": [r["latency_seconds"] for r in rows],
        "errors": [{"case_id": r["case_id"], "repetition": r["repetition"], "error": r["error"]}
                   for r in rows if r.get("error")],
        "limitations": protocol["limitations"],
    }


class CapturedWithoutInference(Exception):
    pass


async def run(options, out, source, protocol, fixture, environment, manifest):
    # All imports occur after the process was pointed at the isolated database and
    # frozen checkout. Importing the app registers its SQL models, without starting
    # an API server, its lifespan, scheduler, queue or any capability executor.
    import httpx
    from agentic_core.database.base import Base, engine, async_session
    from aries.api.app import app  # noqa: F401
    import aries.intelligence as intelligence
    from aries.settings import SettingsService
    from aries.workspace import agent_planner, scopes
    from aries.workspace.registry import registry
    from aries import flags

    assert Path(agent_planner.__file__).is_relative_to(source)
    assert scopes.current() is None
    assert str(out) in str(engine.url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        settings = SettingsService(db)
        for key, value in protocol["settings"].items():
            await settings.set(key, value, set_by="user")
        await db.commit()
        resolved = {key: await settings.explain(key) for key in protocol["settings"]}

    all_caps = agent_planner.scoped_capabilities()
    checks = {"frozen_planner_import": Path(agent_planner.__file__).is_relative_to(source),
              "private_database": str(out) in str(engine.url),
              "full_registered_scope": len(all_caps) == len(registry._items),
              "expected_58_capabilities": len(all_caps) == 58,
              "state_snapshot_disabled": not flags.enabled("ARIES_STATE_SNAPSHOT"),
              "topk_disabled": not flags.enabled("ARIES_CAP_TOPK"),
              "all24_unique": len(fixture) == len({r["id"] for r in fixture}) == 24,
              "expected_decisions_registry_valid": all(
                  normalized(agent_planner.parse(json.dumps(case["expected"])).model_dump()) == case["expected"]
                  for case in fixture),
              "fixture_hash_matches_protocol": sha(HERE / "fixture.json") == protocol["fixture_sha256"]}
    if not all(checks.values()):
        save(out / "failed-preflight.json", checks)
        raise RuntimeError("Planner preflight failed: " + repr(checks))

    run_manifest = {
        "started_at": stamp(), "mode": "execute" if options.execute else "dry-run",
        "window_id": options.window_id, "source_root": str(source),
        "source": verify_source(source, manifest), "runner_sha256": sha(__file__),
        "protocol_sha256": sha(HERE / "protocol.json"), "fixture_sha256": sha(HERE / "fixture.json"),
        "environment": environment, "resolved_settings": resolved, "flags": flags.describe(),
        "registry": all_caps, "checks": checks,
        "database": str(engine.url), "model_metadata": None,
        "limitations": protocol["limitations"],
    }
    original_structured = intelligence.structured
    current = {}

    async def capture(db, messages, schema, **kwargs):
        serializable_kwargs = {key: asdict(value) if is_dataclass(value) else value
                               for key, value in kwargs.items()}
        payload = {"messages": messages, "schema": schema, "generation_kwargs": serializable_kwargs}
        current["prompt_sha256"] = digest(payload)
        name = current["case_id"] + ".json"
        path = out / "prompts" / name
        if path.exists():
            if digest(json.loads(path.read_text())) != digest(payload):
                raise RuntimeError("Prompt drift across repetitions: " + name)
        else:
            save(path, payload)
        if not options.execute:
            raise CapturedWithoutInference()
        return await original_structured(db, messages, schema, **kwargs)

    intelligence.structured = capture
    try:
        if not options.execute:
            for case in fixture:
                current.clear()
                current["case_id"] = case["id"]
                async with async_session() as db:
                    try:
                        await agent_planner.plan(db, case["goal"], planner_data(case), 8)
                    except CapturedWithoutInference:
                        pass
                    else:
                        raise RuntimeError("Dry run did not reach the production structured-call boundary")
            checks["all24_production_prompts_captured_without_inference"] = len(list((out / "prompts").glob("*.json"))) == 24
            run_manifest["source_after"] = verify_source(source, manifest)
            run_manifest["completed_at"] = stamp()
            save(out / "dry-run.json", run_manifest)
            print(json.dumps({"dry_run": str(out), "checks_passed": sum(checks.values()),
                              "checks_total": len(checks), "inference_calls": 0}, ensure_ascii=False))
            return

        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            response = await client.get(protocol["local_url"] + "/api/tags")
            response.raise_for_status()
            run_manifest["model_metadata"] = next(m for m in response.json()["models"] if m["name"] == protocol["model"])
        router_protocol = json.loads((PACKAGE / "protocol.json").read_text())
        run_manifest["router_protocol_sha256"] = sha(PACKAGE / "protocol.json")
        run_manifest["expected_model_digest"] = router_protocol["model"]["digest"]
        run_manifest["model_before_matches_router"] = (
            run_manifest["model_metadata"]["digest"] == run_manifest["expected_model_digest"])
        save(out / "run-manifest.json", run_manifest)
        if not run_manifest["model_before_matches_router"]:
            raise RuntimeError("Local model digest differs from the frozen router protocol; no planner calls made")
        rows, orders = [], []
        for seed in protocol["order"]["seeds"]:
            order = list(range(len(fixture)))
            random.Random(seed).shuffle(order)
            orders.append(order)
        save(out / "order.json", [[fixture[i]["id"] for i in order] for order in orders])
        with (out / "attempts.jsonl").open("x") as log:
            try:
                for repetition, order in enumerate(orders, 1):
                    for index in order:
                        case = fixture[index]
                        current.clear()
                        current["case_id"] = case["id"]
                        row = {"repetition": repetition, "case_id": case["id"], "goal": case["goal"],
                               "category": case["category"], "language": case["language"],
                               "expected": case["expected"], "started_at": stamp(), "raw_output": None,
                               "decision": None, "error": None, "scores": {"schema_valid": False,
                               "capability_correct": False, "capability_arguments_correct": False}}
                        started = time.monotonic()
                        async with async_session() as db:
                            try:
                                raw, usage = await agent_planner.plan(db, case["goal"], planner_data(case), 8)
                                row.update(raw_output=raw, usage=usage)
                                decision = agent_planner.parse(raw).model_dump()
                                row.update(decision=decision, scores=scores(decision, case["expected"]))
                            except Exception as exc:
                                row["error"] = {"type": type(exc).__name__, "message": str(exc)[:3000]}
                        row["latency_seconds"] = round(time.monotonic() - started, 6)
                        row["prompt_sha256"] = current.get("prompt_sha256")
                        rows.append(row)
                        log.write(json.dumps(row, ensure_ascii=False) + "\n")
                        log.flush()
                        os.fsync(log.fileno())
                        save(out / "summary.json", summarize(rows, fixture, protocol, False))
                        print(json.dumps({"attempt": len(rows), "planned": 72, "case": case["id"],
                                          "repetition": repetition, "scores": row["scores"],
                                          "error": (row["error"] or {}).get("type")}), flush=True)
            finally:
                rows_complete = len(rows) == len(fixture) * protocol["repetitions"]
                try:
                    run_manifest["source_after"] = verify_source(source, manifest)
                except Exception as exc:
                    run_manifest["source_after"] = {"matched": False, "error": str(exc)[:2000]}
                try:
                    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                        response = await client.get(protocol["local_url"] + "/api/tags")
                        response.raise_for_status()
                        run_manifest["model_after"] = next(m for m in response.json()["models"]
                                                           if m["name"] == protocol["model"])
                    run_manifest["model_stable"] = (
                        run_manifest["model_after"]["digest"] == run_manifest["model_metadata"]["digest"]
                        == run_manifest["expected_model_digest"])
                except Exception as exc:
                    run_manifest["model_after"] = {"error": str(exc)[:2000]}
                    run_manifest["model_stable"] = False
                complete = (rows_complete and run_manifest["source_after"]["matched"]
                            and run_manifest["model_stable"])
                summary = summarize(rows, fixture, protocol, complete)
                summary["integrity"] = {"rows_complete": rows_complete,
                                        "source_stable": run_manifest["source_after"]["matched"],
                                        "model_stable": run_manifest["model_stable"],
                                        "model_before_matches_router": run_manifest["model_before_matches_router"],
                                        "expected_model_digest": run_manifest["expected_model_digest"]}
                save(out / "summary.json", summary)
                run_manifest["completed_at"] = stamp()
                run_manifest["complete"] = complete
                run_manifest["attempts_sha256"] = sha(out / "attempts.jsonl")
                run_manifest["summary_sha256"] = sha(out / "summary.json")
                save(out / "run-manifest.json", run_manifest)
                if not complete:
                    raise RuntimeError("Planner run incomplete or source/model identity changed; preserved all attempts")
    finally:
        intelligence.structured = original_structured
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=PACKAGE / "frozen")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--window-id", default="")
    options = parser.parse_args()
    if options.execute and not options.window_id:
        parser.error("--execute requires the root-coordinated --window-id")
    source = options.source_root.resolve()
    protocol = json.loads((HERE / "protocol.json").read_text())
    fixture = json.loads((HERE / "fixture.json").read_text())["cases"]
    manifest = json.loads((PACKAGE / "source-manifest.json").read_text())
    verify_source(source, manifest)
    out = HERE / "runs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out.mkdir(parents=True, exist_ok=False)
    (out / "prompts").mkdir()
    for name in ("protocol.json", "fixture.json", "run_planner.py"):
        shutil.copy2(HERE / name, out / name)
    environment = configure(out, source, protocol)
    print("Planner artifact directory: " + str(out), flush=True)
    try:
        asyncio.run(run(options, out, source, protocol, fixture, environment, manifest))
    except BaseException as exc:
        save(out / "harness-error.json", {"time": stamp(), "type": type(exc).__name__,
                                         "message": str(exc)[:5000], "model_execution_requested": options.execute})
        raise


if __name__ == "__main__":
    main()
