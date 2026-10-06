# Task reviews and reusable experience

A completed task dashboard now offers **Useful** and **Needs correction**.
Needs correction requires an explanation. A review belongs to that goal, rather
than becoming a global preference or changing the recorded execution outcome.
Typing a correction pins the result window and pauses its automatic redraw.

Learning shows the latest review, the original task, and controls to reopen the
task or retire its review. Changing a judgment creates a new historical record;
only the latest review per goal contributes to counts or future retrieval.
Retiring that latest review does not revive an older judgment. Repeating an
unchanged submission reuses its existing record.

The server captures the task request, terminal state, up to eight bounded step
summaries and verifier results, limitations, and a digest of the source result.
It excludes executable arguments and full source bodies. Later changes to the
original goal do not rewrite this snapshot. The existing feedback history and
retention policy govern these records.

Before model-based planning, ARIES retrieves up to three reviewed tasks whose
request shares meaningful words with the new goal. This is bounded lexical
retrieval over up to 200 recent latest reviews, not semantic similarity training.
The planner sees the human correction and historical step names/states, never a
replayable old session handle. The allowed capability set and execution gates
remain determined by the current request.

Evaluation reports human usefulness judgments separately from verified tool
outcomes. A useful failed attempt stays technically failed; a successful task
can still receive a correction. No model-generated or developer test rating is
inserted into the user's live review history. No scalar reward or model-weight
RL training is inferred from these records.

API:

- `POST /api/aries/learning/task-reviews/{goal_id}` with `rating` (`useful` or
  `needs_work`) and an optional `comment` (required for `needs_work`, max 2000
  characters). Active tasks and approval-paused tasks cannot be reviewed.
- `GET /api/aries/learning/task-reviews` returns latest active reviews and counts.
- Existing feedback scope controls retire a review by moving it out of
  `current_task`; history remains.

Validation: `tests/test_task_reviews.py` covers immutable snapshots, technical vs
human outcomes, deduplication, replacement/retirement, relevance, planner context,
API rejection paths, and the execution-time median. `tests/test_ui_render.py`
now renders a populated review through real API payloads in an isolated test DB.
