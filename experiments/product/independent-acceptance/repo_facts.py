#!/usr/bin/env python3
"""Repository facts counted from the LIVE OBJECT, not from a text pattern.

WHY THIS EXISTS
---------------
The documents in old-docs/ say "15 registered capabilities". Somebody counted with

    grep -o "Capability('" aries/workspace/registry.py | wc -l

and got 15, because registry.py literally contains 15 `Capability(` constructor
calls. The live `registry` object holds 58: the other 43 are registered at import
time by aries/workspace/{file,browser,desktop,input,keyboard,network,screen,
shell,system}_capabilities.py. The grep looked authoritative and was wrong by
3.9x.

So every number in this file is obtained by the method named in the comment above
it, and that method is always "ask the thing itself":
  - capabilities      -> import the registry, len() its items
  - API routes        -> import the FastAPI app, len(app.routes)
  - database tables   -> query sqlite_master, READ-ONLY (a live service writes here)
  - flags             -> import aries.flags and enumerate FLAGS
  - brief collectors  -> import aries.brief.sections and enumerate _COLLECTORS
  - file/line counts  -> walk the tree, read the files
  - systemd / scripts -> list the directories
Anything that cannot be obtained is recorded as UNOBTAINABLE with the reason,
never guessed.

Run:
    PYTHONPATH=vendor/agentic-core:vendor:. .venv/bin/python \
        experiments/product/independent-acceptance/repo_facts.py
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import traceback

ROOT = pathlib.Path("/home/stamenovmartin/aries")
OUT = ROOT / "experiments/product/independent-acceptance/raw/repo_facts.json"
DB = ROOT / "var/aries.db"


def unobtainable(reason: str) -> dict:
    return {"UNOBTAINABLE": reason}


def guarded(label: str, fn):
    """Run one fact-gatherer; never let one failure hide the other facts."""
    try:
        return fn()
    except BaseException:                                       # noqa: BLE001
        return unobtainable(f"{label} raised: {traceback.format_exc(limit=3).strip()}")


# ── capabilities: import the registry object and len() its items ─────────────
def capabilities() -> dict:
    # METHOD: import aries.workspace (whose __init__ imports every *_capabilities
    # module, which is what actually registers them) and read the live dict.
    from aries.workspace import registry as registry_module

    reg = registry_module.registry
    items = reg._items                      # the live dict the system itself serves from
    caps = list(items.values())

    by_effect: dict[str, int] = {}
    by_risk: dict[str, int] = {}
    for c in caps:
        by_effect[c.effect] = by_effect.get(c.effect, 0) + 1
        by_risk[c.risk_level] = by_risk.get(c.risk_level, 0) + 1

    needs_approval = [c.name for c in caps if c.requires_approval]
    no_approval = [c.name for c in caps if not c.requires_approval]

    # For contrast: the number the grep produced, computed the grep's way, so the
    # discrepancy is visible inside the artefact itself rather than only in prose.
    reg_src = (ROOT / "aries/workspace/registry.py").read_text(encoding="utf-8")
    grep_style = reg_src.count("Capability(")

    # Which module registered what, so "43 elsewhere" is auditable.
    per_module: dict[str, int] = {}
    for c in caps:
        mod = getattr(c.executor, "__module__", "?")
        per_module[mod] = per_module.get(mod, 0) + 1

    return {
        "method": "import aries.workspace.registry; len(registry._items)",
        "total": len(items),
        "grep_style_count_in_registry_py": grep_style,
        "grep_undercount_factor": round(len(items) / grep_style, 2) if grep_style else None,
        "by_effect": dict(sorted(by_effect.items())),
        "by_risk_level": dict(sorted(by_risk.items())),
        "requires_approval_true": len(needs_approval),
        "requires_approval_false": len(no_approval),
        "requires_approval_names": sorted(needs_approval),
        "registering_module_counts": dict(sorted(per_module.items())),
        "names": sorted(items),
    }


# ── spoken catalogue: a SECOND, smaller set that is easy to confuse ────────
def spoken_catalogue() -> dict:
    # METHOD: import aries.workspace.capabilities and len() its module-level
    # tuples. This matters because the repository has TWO capability sets of
    # different size — the typed registry the planner uses (58) and the spoken
    # catalogue a person can say out loud (54) — plus two subsets of the spoken
    # one (SENSITIVE, WRITES). A document citing "capabilities" may mean any of
    # them, so all four are reported rather than collapsed into one number.
    from aries.workspace import capabilities as C

    return {
        "method": "import aries.workspace.capabilities; len(CATALOGUE/SENSITIVE/WRITES/ARGUMENTS)",
        "spoken_catalogue_entries": len(C.CATALOGUE),
        "spoken_sensitive_needing_approval": len(C.SENSITIVE),
        "spoken_that_write": len(C.WRITES),
        "argument_schemas": len(C.ARGUMENTS),
        "spoken_names": sorted(k for k, _, _ in C.CATALOGUE),
        "sensitive_names": sorted(C.SENSITIVE),
        "writing_names": sorted(C.WRITES),
    }


# ── API routes: import the ASGI app and count app.routes (NOT grep) ─────────
def api_routes() -> dict:
    # METHOD: import aries.api.app and walk app.routes. Importing does not run the
    # lifespan, so no worker, scheduler or model is started.
    from aries.api.app import app

    rows = []
    for r in app.routes:
        path = getattr(r, "path", None) or getattr(r, "path_format", None) or repr(r)
        methods = sorted(getattr(r, "methods", None) or [])
        rows.append({"path": path, "methods": methods, "type": type(r).__name__})

    http_methods: dict[str, int] = {}
    for row in rows:
        for m in row["methods"]:
            http_methods[m] = http_methods.get(m, 0) + 1

    aries_prefixed = [r for r in rows if str(r["path"]).startswith("/api/aries")]
    # A route object can serve several verbs; the path/verb pair count is the number
    # a document calling something an "endpoint" most likely means.
    path_method_pairs = sum(len(r["methods"]) or 1 for r in rows)

    return {
        "method": "import aries.api.app; len(app.routes)",
        "route_objects_total": len(app.routes),
        "path_method_pairs_total": path_method_pairs,
        "aries_prefixed_route_objects": len(aries_prefixed),
        "unique_paths": len({r["path"] for r in rows}),
        "unique_aries_paths": len({r["path"] for r in aries_prefixed}),
        "by_http_method": dict(sorted(http_methods.items())),
        "aries_paths": sorted({str(r["path"]) for r in aries_prefixed}),
        "all_paths": sorted({str(r["path"]) for r in rows}),
    }


# ── database: sqlite_master on var/aries.db, READ-ONLY (mode=ro URI) ────────
def database() -> dict:
    # METHOD: sqlite3 over a mode=ro URI. A live service holds this file open for
    # writing; a normal connect() could take a lock, so read-only is mandatory.
    import sqlite3

    if not DB.exists():
        return unobtainable(f"{DB} does not exist")

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        tables = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        views = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")]
        indexes = [r[0] for r in cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name")]
        user_tables = [t for t in tables if not t.startswith("sqlite_")]
        aries_tables = [t for t in user_tables if t.startswith("aries")]

        rows: dict[str, object] = {}
        for t in user_tables:
            try:
                rows[t] = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.Error as exc:
                rows[t] = f"UNOBTAINABLE: {exc}"
    finally:
        con.close()

    return {
        "method": 'sqlite3.connect("file:var/aries.db?mode=ro", uri=True); SELECT FROM sqlite_master',
        "path": str(DB),
        "size_bytes": DB.stat().st_size,
        "tables_total": len(user_tables),
        "tables_including_sqlite_internal": len(tables),
        "aries_prefixed_tables": len(aries_tables),
        "views": len(views),
        "indexes": len(indexes),
        "table_names": user_tables,
        "row_counts": rows,
        "total_rows_all_tables": sum(v for v in rows.values() if isinstance(v, int)),
    }


# ── source size: walk the tree and read the files ───────────────────────────
def _walk_python(base: pathlib.Path) -> dict:
    files, lines, blank, comment, bytes_ = 0, 0, 0, 0, 0
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in p.parts or ".venv" in p.parts:
            continue
        files += 1
        bytes_ += p.stat().st_size
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            lines += 1
            s = line.strip()
            if not s:
                blank += 1
            elif s.startswith("#"):
                comment += 1
    return {"files": files, "lines": lines, "blank_lines": blank,
            "comment_lines": comment, "code_or_docstring_lines": lines - blank - comment,
            "bytes": bytes_}


def source_size() -> dict:
    # METHOD: rglob("*.py") excluding __pycache__, then count physical lines.
    out = {"method": 'pathlib rglob("*.py"), __pycache__ excluded; physical line count'}
    for name, rel in (("aries", "aries"), ("aries_ui", "aries_ui"),
                      ("tests", "tests"), ("scripts", "scripts"),
                      ("eval", "eval"), ("experiments", "experiments")):
        base = ROOT / rel
        out[name] = _walk_python(base) if base.is_dir() else unobtainable(f"{base} missing")
    prod = [out[k] for k in ("aries", "aries_ui") if isinstance(out[k], dict) and "files" in out[k]]
    out["aries_plus_aries_ui"] = {
        "files": sum(d["files"] for d in prod),
        "lines": sum(d["lines"] for d in prod),
    }

    # Repo-wide Python file count, the number a document means by "N Python files":
    # everything the project itself wrote. .venv and vendor/ are third-party and are
    # excluded; __pycache__ is not source.
    skip = {".venv", "vendor", "__pycache__", ".git", "node_modules"}
    repo_files = [p for p in ROOT.rglob("*.py") if not (skip & set(p.relative_to(ROOT).parts))]
    out["repo_wide_python_excluding_venv_and_vendor"] = {
        "files": len(repo_files),
        "lines": sum(len(p.read_text(encoding="utf-8", errors="replace").splitlines())
                     for p in repo_files),
        "excluded": sorted(skip),
    }
    vendor_files = [p for p in (ROOT / "vendor").rglob("*.py")
                    if "__pycache__" not in p.parts] if (ROOT / "vendor").is_dir() else []
    out["vendor_python_files"] = len(vendor_files)

    # Non-Python source a document may cite: the GNOME shell extension, the session
    # and share trees.
    for name, rel, exts in (("shell", "shell", (".js", ".css", ".json", ".xml")),
                            ("session", "session", (".sh", ".desktop", ".conf", ".py")),
                            ("share", "share", (".desktop", ".svg", ".png", ".xml", ".json"))):
        base = ROOT / rel
        if not base.is_dir():
            out[name] = unobtainable(f"{base} missing")
            continue
        files = [p for p in base.rglob("*") if p.is_file() and p.suffix in exts]
        out[name] = {
            "extensions_counted": list(exts),
            "files": len(files),
            "lines": sum(len(p.read_text(encoding="utf-8", errors="replace").splitlines())
                         for p in files),
        }
    return out


# ── execution budgets and typed errors: read the live module constants ─────
def execution_budgets() -> dict:
    # METHOD: import aries.workspace.orchestration and read the constants and the
    # route table, plus the agent step limit from the settings schema default.
    # Documents quote these as the system's hard bounds, so they are read, not
    # transcribed.
    from aries.settings import schema
    from aries.workspace import orchestration as O

    try:
        max_steps = schema.require("workspace.agent_max_steps").default
    except Exception as exc:                                     # noqa: BLE001
        max_steps = unobtainable(f"workspace.agent_max_steps: {exc!r}")

    verdicts: dict[str, int] = {}
    for _code, pair in O.ROUTE.items():
        verdicts[pair[0]] = verdicts.get(pair[0], 0) + 1

    alts = O.ALTERNATIVES
    return {
        "method": "import aries.workspace.orchestration; read constants, ROUTE and ALTERNATIVES",
        "attempt_cap_capability_invocations_per_subgoal": O.ATTEMPT_CAP,
        "retry_cap_repeats_of_one_strategy": O.RETRY_CAP,
        "alternative_cap_distinct_alternatives": O.ALTERNATIVE_CAP,
        "max_subgoals_fan_out_width": O.MAX_SUBGOALS,
        "ceiling": O.CEILING,
        "aging_deferrals": O.AGING_DEFERRALS,
        "retry_backoff_seconds": list(O.RETRY_BACKOFF_S),
        "agent_max_steps_setting_default": max_steps,
        "typed_error_codes_in_route_table": len(O.ROUTE),
        "route_verdict_counts": dict(sorted(verdicts.items())),
        "typed_error_code_names": sorted(O.ROUTE),
        "primaries_with_declared_alternatives": len(alts),
        "declared_alternatives_total": sum(len(v) for v in alts.values()),
        "declared_alternatives": {k: [getattr(a, "capability", "?") for a in v]
                                  for k, v in sorted(alts.items())},
    }


# ── settings: import the schema registry and enumerate ─────────────────────
def settings_schema() -> dict:
    # METHOD: import aries.settings and call all_defs()/sections(). The definitions
    # live in a module-level registry populated at import; a grep over defaults.py
    # would miss whatever registers elsewhere, which is the same mistake as the
    # capability undercount.
    from aries.settings import schema

    defs = schema.all_defs()
    secs = schema.sections()
    per_section = {s: len(schema.in_section(s)) for s in secs}
    return {
        "method": "import aries.settings.schema; all_defs() / sections()",
        "settings_total": len(defs),
        "sections_total": len(secs),
        "section_names": secs,
        "per_section": per_section,
    }


# ── automations: import the genome registry and enumerate ───────────────────
def automations() -> dict:
    # METHOD: import aries.automations and call all_automations(). `import aries`
    # is what registers them, so it is imported first.
    import aries  # noqa: F401  registering side effect
    from aries.automations import all_automations

    specs = all_automations()
    rows = []
    for s in specs:
        rows.append({
            "name": getattr(s, "name", "?"),
            "enabled_setting": getattr(s, "enabled_setting", None),
            "interval_setting": getattr(s, "interval_setting", None),
            "time_setting": getattr(s, "time_setting", None),
            "agents": list(getattr(s, "agents", []) or []),
        })
    return {
        "method": "import aries; aries.automations.all_automations()",
        "total": len(specs),
        "uses_no_model": sum(1 for r in rows if not r["agents"]),
        "uses_a_model": sum(1 for r in rows if r["agents"]),
        "names": sorted(r["name"] for r in rows),
        "specs": rows,
    }


# ── systemd units: list systemd/ and split by suffix ───────────────────────
def systemd_units() -> dict:
    # METHOD: list the repository's systemd/ directory. These are the units the
    # repo ships; what is *installed* on this host is a different question and is
    # answered separately below without starting or querying any service.
    base = ROOT / "systemd"
    if not base.is_dir():
        return unobtainable(f"{base} missing")
    names = sorted(p.name for p in base.iterdir() if p.is_file())
    by_kind: dict[str, list[str]] = {}
    for n in names:
        by_kind.setdefault(pathlib.Path(n).suffix.lstrip(".") or "no_suffix", []).append(n)

    installed: object
    user_dir = pathlib.Path.home() / ".config/systemd/user"
    if user_dir.is_dir():
        installed = sorted(p.name for p in user_dir.iterdir()
                           if p.is_file() or p.is_symlink())
    else:
        installed = unobtainable(f"{user_dir} missing")

    return {
        "method": "list repo systemd/ directory, split on filename suffix",
        "total": len(names),
        "service": len(by_kind.get("service", [])),
        "timer": len(by_kind.get("timer", [])),
        "target": len(by_kind.get("target", [])),
        "by_kind": {k: sorted(v) for k, v in sorted(by_kind.items())},
        "names": names,
        "installed_in_user_systemd_dir": installed,
    }


# ── scripts/: list the directory, split executable vs not ──────────────────
def scripts() -> dict:
    # METHOD: list scripts/, excluding __pycache__. "Entry point" = a file a user
    # can invoke, so the executable bit is reported separately from the file count.
    base = ROOT / "scripts"
    if not base.is_dir():
        return unobtainable(f"{base} missing")
    files = sorted(p for p in base.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts)
    rel = [str(p.relative_to(base)) for p in files]
    executable = [str(p.relative_to(base)) for p in files if os.access(p, os.X_OK)]
    aries_prefixed = [n for n in rel if n.startswith("aries")]
    by_ext: dict[str, int] = {}
    for p in files:
        by_ext[p.suffix or "no_extension"] = by_ext.get(p.suffix or "no_extension", 0) + 1
    return {
        "method": "list scripts/ recursively, __pycache__ excluded; os.access(X_OK)",
        "files_total": len(rel),
        "executable": len(executable),
        "aries_prefixed": len(aries_prefixed),
        "by_extension": dict(sorted(by_ext.items())),
        "names": rel,
        "executable_names": executable,
    }


# ── feature flags: import aries.flags and enumerate ─────────────────────────
def flags() -> dict:
    # METHOD: import aries.flags and read FLAGS / describe(). describe() is what
    # the eval harnesses themselves write into result files, so this is the same
    # number the measurements are taken against.
    from aries import flags as F

    described = F.describe()
    on = [n for n, v in described["flags"].items() if v["on"]]
    off = [n for n, v in described["flags"].items() if not v["on"]]
    default_true = [n for n, (d, _) in F.FLAGS.items() if d]
    default_false = [n for n, (d, _) in F.FLAGS.items() if not d]
    return {
        "method": "import aries.flags; enumerate FLAGS and describe()",
        "total": len(F.FLAGS),
        "currently_on": len(on),
        "currently_off": len(off),
        "default_on": len(default_true),
        "default_off": len(default_false),
        "names": sorted(F.FLAGS),
        "off_now": sorted(off),
        "primary_language": described["primary_language"],
        "listen_languages": described["listen_languages"],
        "supported_languages": list(F.SUPPORTED),
        "whisper_models_declared": sorted(F.WHISPER_MODELS),
        "whisper_models_present_on_disk": sorted(
            rel for rel in F.WHISPER_MODELS.values() if (ROOT / rel).is_dir()),
    }


# ── brief collectors: import and enumerate, live vs declared-unavailable ───
def brief_collectors() -> dict:
    # METHOD: import aries.brief.sections, read the live _COLLECTORS dict. A
    # declared-unavailable section is one produced by the `_pending` factory — it
    # returns a Section with `unavailable` set and never touches the database. It
    # is identified by the closure's qualname, not by a name allowlist, so adding
    # a real collector later cannot silently keep it on the unavailable list.
    from aries.brief import sections as S

    collectors = dict(S._COLLECTORS)
    declared, live = [], []
    for name, fn in collectors.items():
        qual = getattr(fn, "__qualname__", "")
        (declared if "_pending" in qual else live).append(name)

    reasons = {}
    for name in declared:
        cell = getattr(collectors[name], "__closure__", None) or ()
        vals = [c.cell_contents for c in cell if isinstance(c.cell_contents, str)]
        reasons[name] = max(vals, key=len) if vals else "UNOBTAINABLE: reason not in closure"

    return {
        "method": "import aries.brief.sections; enumerate _COLLECTORS; split on _pending closure",
        "total": len(collectors),
        "live": len(live),
        "declared_unavailable": len(declared),
        "live_names": sorted(live),
        "declared_unavailable_names": sorted(declared),
        "declared_unavailable_reasons": reasons,
        "names_via_public_api": S.names(),
    }


# ── tests: parse the AST, because this suite has no pytest ─────────────────
def tests() -> dict:
    # METHOD: this project does NOT use pytest (it is not installed in .venv).
    # Each test file is a standalone script ending in
    #     sys.exit(run_module(sys.modules[__name__]))
    # and `run_module` discovers module-level callables named test_*. There is
    # therefore no collector to ask without EXECUTING every test, which would
    # touch the database and is out of scope here. The next-best authority is the
    # parsed syntax tree: ast.parse gives the real set of `def test_*` definitions,
    # which a grep cannot (it counts commented-out and string-embedded matches and
    # misses nothing-but-decorated forms). Each file's own `check(...)` calls are
    # counted the same way, since that is this suite's unit of assertion.
    import ast

    test_dir = ROOT / "tests"
    if not test_dir.is_dir():
        return unobtainable(f"{test_dir} missing")
    files = sorted(p for p in test_dir.rglob("test_*.py") if "__pycache__" not in p.parts)

    funcs = 0
    checks = 0
    unparsed = []
    per_file = {}
    for p in files:
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=str(p))
        except SyntaxError as exc:
            unparsed.append(f"{p}: {exc}")
            continue
        f_here = 0
        c_here = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name.startswith("test_"):
                f_here += 1
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "check":
                c_here += 1
        funcs += f_here
        checks += c_here
        per_file[str(p.relative_to(test_dir))] = {"test_functions": f_here, "check_calls": c_here}

    grep_defs = sum(
        sum(1 for line in p.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.lstrip().startswith(("def test_", "async def test_")))
        for p in files)

    pytest_available = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "-c", "import pytest"],
        capture_output=True, text=True, timeout=120).returncode == 0

    return {
        "method": "ast.parse each tests/**/test_*.py; count def test_* and check() calls",
        "pytest_installed_in_venv": pytest_available,
        "collected_tests": unobtainable(
            "this suite has no pytest and no non-executing collector; each file "
            "self-runs via run_module(). AST test-function count is reported instead."),
        "test_files": len(files),
        # The project's own runner (vendor/agentic-core/tests/run_tests.py) globs
        # tests/test_*.py at the TOP level only, so that count is reported too — a
        # document saying "N test files" may mean either.
        "test_files_top_level_only": len(list(test_dir.glob("test_*.py"))),
        "test_functions_ast": funcs,
        "check_assertions_ast": checks,
        "grep_style_def_test_count": grep_defs,
        "files_that_would_not_parse": unparsed,
        "per_file": per_file,
    }


# ── generated docs: counts whose authority is a generator, read as generated ─
def generated_doc_counts() -> dict:
    # METHOD: two files under docs/ are machine-generated and kept in sync by
    # their own generators (`scripts/aries-capability-docs`,
    # `scripts/aries-verification-table --check`). For the verification coverage
    # split there is no other authority short of re-running the generator, so the
    # generated file is read and its own numbers are reported as such. The row
    # count of the generated capability table IS independently checkable, and is
    # compared against the live registry here.
    import re

    out: dict[str, object] = {
        "method": "read the generated docs/ artefacts; cross-check the table row count "
                  "against the live registry",
    }

    cap_doc = ROOT / "docs/CAPABILITIES.md"
    if cap_doc.is_file():
        text = cap_doc.read_text(encoding="utf-8", errors="replace")
        rows = [l for l in text.splitlines() if re.match(r"^\|\s*`[a-z_]+\.[a-z_]+`", l)]
        out["capabilities_md_table_rows"] = len(rows)
    else:
        out["capabilities_md_table_rows"] = unobtainable(f"{cap_doc} missing")

    vt = ROOT / "docs/verification_table.md"
    if vt.is_file():
        text = vt.read_text(encoding="utf-8", errors="replace")
        wanted = {
            "capabilities_in_the_registry_AS_THE_GENERATOR_COUNTS_IT":
                r"capabilities in the registry: \*\*(\d+)\*\*",
            "with_dedicated_branch_in_verify": r"dedicated branch in `verify\(\)`: \*\*(\d+)\*\*",
            "re_reading_state_inside_execute": r"inside `execute\(\)` instead: \*\*(\d+)\*\*",
            "proved_in_a_delegate_module": r"delegate module: \*\*(\d+)\*\*",
            "proof_via_operator_run": r"operator\.run\(\)`: \*\*(\d+)\*\*",
            "read_only_answer_is_the_observation": r"itself the observation: \*\*(\d+)\*\*",
            "changing_state_without_proving_it": r"without proving it: (\d+)\*\*",
            "recorded_as_verified_in_the_live_ledger": r"recorded as verified: \*\*(\d+)\*\*",
        }
        found: dict[str, object] = {}
        for key, pat in wanted.items():
            m = re.search(pat, text)
            found[key] = int(m.group(1)) if m else unobtainable(f"pattern not found: {pat}")
        out["verification_table"] = found
        out["verification_table_note"] = (
            "The generator's own line 'capabilities in the registry' reports the SPOKEN "
            "catalogue size, not the typed registry size. Both exist in this repo and "
            "differ; a document citing this line is citing the spoken set.")
    else:
        out["verification_table"] = unobtainable(f"{vt} missing")
    return out


# ── documentation and experiments: list the trees ──────────────────────────
def docs_and_experiments() -> dict:
    # METHOD: list the directories. Counted because documents cite their own size.
    def md(base: pathlib.Path) -> object:
        if not base.is_dir():
            return unobtainable(f"{base} missing")
        files = sorted(p for p in base.rglob("*.md"))
        lines = sum(len(p.read_text(encoding="utf-8", errors="replace").splitlines())
                    for p in files)
        words = sum(len(p.read_text(encoding="utf-8", errors="replace").split())
                    for p in files)
        return {"md_files": len(files), "md_lines": lines, "md_words": words,
                "names": [str(p.relative_to(base)) for p in files]}

    out = {"method": "list the trees"}
    out["old_docs"] = md(ROOT / "old-docs")
    out["docs"] = md(ROOT / "docs")
    exp = ROOT / "experiments"
    out["experiments"] = ({
        "top_level_dirs": len([p for p in exp.iterdir() if p.is_dir()]),
        "dir_names": sorted(p.name for p in exp.iterdir() if p.is_dir()),
        "json_files": len(list(exp.rglob("*.json"))),
    } if exp.is_dir() else unobtainable(f"{exp} missing"))
    ev = ROOT / "eval"
    out["eval"] = ({
        "top_level_dirs": len([p for p in ev.iterdir() if p.is_dir()]),
        "dir_names": sorted(p.name for p in ev.iterdir() if p.is_dir()),
        "json_files": len(list(ev.rglob("*.json"))),
    } if ev.is_dir() else unobtainable(f"{ev} missing"))
    return out


# ── old-docs inventory: the documents' claims about themselves ─────────────
def document_inventory() -> dict:
    # METHOD: count the files, and read each PDF's page count out of the PDF's own
    # page-tree /Count (the largest value, which is the root node). The documents
    # cite their own sizes, so those are repository counts too. Nothing here opens
    # or modifies a document.
    import re

    base = ROOT / "old-docs"
    if not base.is_dir():
        return unobtainable(f"{base} missing")

    per_folder = {}
    for sub in sorted(p for p in base.iterdir() if p.is_dir()):
        per_folder[sub.name] = {
            "md_top_level": len(list(sub.glob("*.md"))),
            "md_recursive": len(list(sub.rglob("*.md"))),
            "pdf": len(list(sub.rglob("*.pdf"))),
        }

    pages = {}
    for pdf in sorted(base.rglob("*.pdf")):
        try:
            blob = pdf.read_bytes()
            counts = [int(m.group(1)) for m in re.finditer(rb"/Count\s+(\d+)", blob)]
            pages[str(pdf.relative_to(base))] = max(counts) if counts else unobtainable(
                "no /Count in the PDF page tree")
        except OSError as exc:
            pages[str(pdf.relative_to(base))] = unobtainable(str(exc))

    extras: dict[str, object] = {}
    prov = base / "research_package/processed_results/provenance.json"
    if prov.is_file():
        try:
            data = json.loads(prov.read_text(encoding="utf-8"))
            extras["provenance_records"] = len(data.get("records", []))
            extras["provenance_commit"] = data.get("commit")
        except (OSError, ValueError) as exc:
            extras["provenance_records"] = unobtainable(str(exc))
    runs = base / "research_package/processed_results/suite_runs.json"
    if runs.is_file():
        try:
            extras["indexed_suite_runs"] = len(json.loads(runs.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            extras["indexed_suite_runs"] = unobtainable(str(exc))

    thesis = base / "thesis"
    extras["thesis_numbered_chapter_files"] = (
        len([p for p in thesis.glob("*.md") if re.match(r"^\d\d_", p.name)])
        if thesis.is_dir() else unobtainable("old-docs/thesis missing"))

    return {
        "method": "count files; read each PDF's own /Count page-tree value",
        "per_folder": per_folder,
        "pdf_page_counts": pages,
        **extras,
    }


# ── package layout: subpackages of aries/ ──────────────────────────────────
def package_layout() -> dict:
    # METHOD: list aries/ for directories holding an __init__.py.
    base = ROOT / "aries"
    if not base.is_dir():
        return unobtainable(f"{base} missing")
    subs = sorted(p.name for p in base.iterdir()
                  if p.is_dir() and p.name != "__pycache__" and (p / "__init__.py").exists())
    dirs = sorted(p.name for p in base.iterdir() if p.is_dir() and p.name != "__pycache__")
    ui = ROOT / "aries_ui"
    return {
        "method": "list aries/ directories containing __init__.py",
        "aries_subpackages": len(subs),
        "aries_subpackage_names": subs,
        "aries_subdirectories": len(dirs),
        "aries_ui_pages": (len([p for p in (ui / "pages").glob("*.py")
                                if p.name != "__init__.py"])
                           if (ui / "pages").is_dir() else unobtainable("aries_ui/pages missing")),
        "aries_ui_page_names": (sorted(p.stem for p in (ui / "pages").glob("*.py")
                                       if p.name != "__init__.py")
                                if (ui / "pages").is_dir() else []),
    }


# ── git: ask git, not the filesystem ───────────────────────────────────────
def git_facts() -> dict:
    # METHOD: run git. Documents sometimes cite a commit count or a date.
    def g(*args: str) -> str:
        return subprocess.run(["git", "-C", str(ROOT), *args],
                              capture_output=True, text=True, timeout=120).stdout.strip()

    if not (ROOT / ".git").exists():
        return unobtainable("no .git directory")
    return {
        "method": "git rev-list / git log",
        "commits": int(g("rev-list", "--count", "HEAD") or 0) or unobtainable("empty rev-list"),
        "head": g("rev-parse", "HEAD"),
        "branch": g("rev-parse", "--abbrev-ref", "HEAD"),
        "first_commit_date": g("log", "--reverse", "--format=%cI", "--max-count=1"),
        "last_commit_date": g("log", "-1", "--format=%cI"),
        "tracked_files": len(g("ls-files").splitlines()) or unobtainable("git ls-files empty"),
    }


def main() -> int:
    facts = {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "repo_root": str(ROOT),
        "python": sys.version.split()[0],
        "note": ("Every count here is taken from the live object or the authoritative "
                 "source named in each section's 'method' field. No count is taken "
                 "from a grep over source text, except where a grep-style number is "
                 "reported explicitly for contrast."),
        "capabilities": guarded("capabilities", capabilities),
        "spoken_catalogue": guarded("spoken_catalogue", spoken_catalogue),
        "api_routes": guarded("api_routes", api_routes),
        "database": guarded("database", database),
        "source_size": guarded("source_size", source_size),
        "systemd_units": guarded("systemd_units", systemd_units),
        "scripts": guarded("scripts", scripts),
        "flags": guarded("flags", flags),
        "brief_collectors": guarded("brief_collectors", brief_collectors),
        "execution_budgets": guarded("execution_budgets", execution_budgets),
        "settings_schema": guarded("settings_schema", settings_schema),
        "automations": guarded("automations", automations),
        "tests": guarded("tests", tests),
        "generated_doc_counts": guarded("generated_doc_counts", generated_doc_counts),
        "docs_and_experiments": guarded("docs_and_experiments", docs_and_experiments),
        "document_inventory": guarded("document_inventory", document_inventory),
        "package_layout": guarded("package_layout", package_layout),
        "git": guarded("git", git_facts),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    json.dump(facts, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
