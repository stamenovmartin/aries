"""Scheduled dashboards call exactly the same queue as a submitted goal."""
from agentic_core.database.base import async_session
from aries.automations.genome import AutomationSpec, register
from aries.settings import SettingsService
from sqlalchemy import select
from aries.workspace.models import WorkspaceGoal

async def refresh_topics(ctx):
    from aries.workspace.service import submit
    ids, reused = [], []
    async with async_session() as db:
        topics = await SettingsService(db).get("workspace.topics")
        for topic in topics[:6]:
            if not isinstance(topic, str) or not topic.strip():
                continue
            request = 'Research news with source links: ' + topic.strip()
            pending = (await db.execute(select(WorkspaceGoal).where(
                WorkspaceGoal.request == request,
                WorkspaceGoal.state.in_({'queued', 'running'})).limit(1))).scalar_one_or_none()
            if pending:
                reused.append(pending.id)
                continue
            from sqlalchemy import func
            count = await db.scalar(select(func.count()).select_from(WorkspaceGoal).where(
                WorkspaceGoal.state.in_({'queued', 'running'})))
            if count >= 17:  # leave capacity for interactive user requests
                break
            result = await submit(db, "", capability="research", args={"query": topic},origin='automation:aries.dashboards')
            ids.append(result["id"])
        result = {"summary": f"Queued {len(ids)} topic dashboards; reused {len(reused)} pending", "goal_ids": ids,
                  "reused_goal_ids": reused}
        # Direct automations own their bookkeeping. Without a run row the
        # dispatcher sees 'never ran' and queues the same topics every minute.
        from aries.automations.genome import get, record_run
        await record_run(db, get('aries.dashboards'), status='ok', summary=result['summary'],
                         detail=result, trigger=ctx.get('trigger', 'schedule'))
        await db.commit()
    return result

register(AutomationSpec(
    automation_id="aries.dashboards", name="Topic Dashboards", version="1.0.0",
    purpose="Keep dashboards for your research topics fresh, with source links and visible gaps",
    run=refresh_topics, enabled_setting="workspace.dashboard_enabled",
    schedule_setting="workspace.interval_minutes", default_interval_minutes=60,
    input_sources=["enabled news sources", "public news search when enabled"],
    evaluation_metrics=["sources found", "collection failures", "time to dashboard"],
))
