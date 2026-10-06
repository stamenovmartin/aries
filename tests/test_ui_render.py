"""Every Control Centre screen draws real ARIES data without throwing.

The contract suite proves the endpoints return the keys the UI reads. This
proves the UI can actually build a widget tree out of them — which is a
different failure, and the one that reaches the user as an error page.

It captures live responses here (in the ARIES virtual environment), then runs
the renderer on the system interpreter, which is the only one that has `gi`.
Two processes, because that is genuinely how the product is built.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests._bootstrap import bootstrap, check, reset_db, run_module

bootstrap("aries-ui-render")

import httpx  # noqa: E402

from agentic_core.database.base import async_session  # noqa: E402

from aries.interests import service as interests  # noqa: E402
from aries.settings import SettingsService  # noqa: E402
from aries.sources import service as sources  # noqa: E402
from aries_ui.contract import READS  # noqa: E402

from aries.api.app import app  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def _populate():
    """Rows in every table a screen reads, so no page renders an empty list.

    An empty screen renders trivially. The interesting crashes — a None where a
    string was assumed, a missing key on one item in a list — need real rows.
    """
    await reset_db()
    async with async_session() as db:
        s = SettingsService(db)
        await s.set("news.enabled", True, set_by="user")
        await s.set("health.enabled", True, set_by="user")
        await interests.add(db, topic="ai", weight=0.9, synonyms=["artificial intelligence"])
        await interests.learn(db, "ai", 0.55, confidence=0.8, rationale="you ignored 20 of 30")
        await sources.add(db, name="Example", type="rss", location="https://example.com/f.xml",
                          topics=["ai"])
        from aries.lifecycle import working
        await working.put(db, "render-task", label="An email from the bank",
                          source="gmail", content="x" * 900, sensitive=True)
        from aries.workspace.models import WorkspaceGoal
        from aries.workspace.reviews import submit as review_task
        db.add(WorkspaceGoal(id="render-reviewed-task", request="Summarize Python documentation", state="partial",
                            result_json=json.dumps({"steps":[], "cards":[], "gaps":["Missing requested source image"]})))
        await db.commit()
        await review_task(db, "render-reviewed-task", "needs_work", "Include the requested source image and link")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        await c.post("/api/aries/learning/feedback", json={"text": "shorter"})
        await c.post("/api/aries/automations/aries.health/run", json={"force": True})


def _has_gtk() -> bool:
    return subprocess.run(["/usr/bin/python3", "-c", "import gi"],
                          capture_output=True).returncode == 0


async def test_every_screen_renders_real_data():
    if not _has_gtk():
        check("skipped — PyGObject is not on the system interpreter", True)
        return
    await _populate()

    captured = 0
    with tempfile.TemporaryDirectory() as tmp:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as c:
            for i, endpoint in enumerate(READS):
                r = await c.get(endpoint)
                if r.status_code != 200:
                    check(f"{endpoint} answers, to be captured "
                          f"(got {r.status_code})", False)
                    continue
                with open(os.path.join(tmp, f"{i:03d}.json"), "w") as fh:
                    json.dump({"path": endpoint, "body": r.json()}, fh)
                captured += 1
        check(f"captured {captured} live payload(s)", captured == len(READS))

        # The system interpreter, not this one: `gi` is not in the venv, and the
        # UI's real runtime is /usr/bin/python3. Testing it anywhere else would
        # be testing something the user never runs.
        proc = subprocess.run(
            ["/usr/bin/python3", os.path.join(ROOT, "tests", "ui_render.py"), tmp],
            capture_output=True, text=True, timeout=180,
            env={**os.environ, "GSETTINGS_BACKEND": "memory"})

    for line in (proc.stdout or "").splitlines():
        if line.startswith(("PASS", "FAIL")):
            print(f"  {line}")
    if proc.returncode != 0:
        print((proc.stderr or "").strip()[-1500:])
    check("every screen renders without throwing", proc.returncode == 0)


if __name__ == "__main__":
    run_module(sys.modules[__name__])
