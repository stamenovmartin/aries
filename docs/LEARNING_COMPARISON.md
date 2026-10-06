# Paired comparison of task-experience retrieval

Learning now offers **Compare learning versions**. The command `evaluate learning`
(or `proveri ucenje`, `провери учење`) queues the same comparison and opens its
own result window. Its complete case-level results remain in Monitor.

The comparison runs two retrieval implementations against the same frozen corpus
and 20 developer-labelled queries in `aries/workspace/fixtures/retrieval_v1.json`.
These are synthetic relevance cases. They do not execute desktop goals, invoke a
model, access personal accounts, or manufacture ratings in the user's review
history. The labels and code were developed together; this is a regression fixture,
not an independently held-out benchmark or evidence of general improvement.

- `overlap-v1` is the previous word-overlap behavior and remains the default.
- `focused-v2` ignores more generic command words, normalizes simple English
  plurals, requires sufficient query coverage, and abstains on ambiguous single
  topics. It is lexical matching, not translation or embeddings.

The recorded first comparison was 15/20 versus 19/20 exact expected selections,
with four improved cases and no regressions in this fixture. The remaining
`sports news summary` / `climate news summary` false positive is retained and
reported. It was not removed to manufacture a perfect score.

Each result includes the fixture version, SHA-256 of its exact bytes, a combined
retrieval/review implementation digest, each expected and selected review ID,
measured per-case time, precision/recall, and case-level improvements/regressions.
Expected empty selections are judged by exact equality, not counted as arbitrary
true positives in precision/recall. Timings are local retrieval time, not model
latency or full task completion time.

Running a comparison never changes the active version. The Learning selector
writes the existing typed, audited `workspace.review_retrieval` setting. Selecting
the previous version restores its behavior without rewriting review history.
Each piece of retrieved planner experience identifies the version that selected it.
No candidate auto-promotion or model-weight RL training is enabled.

Validation: `tests/test_learning_eval.py` checks identical inputs, the disclosed
failure, no hidden regressions, digests, durable queue execution, no desktop
writes, no implicit promotion, real retrieval switching and rollback. The broader
suite checks the existing review, planner, API and native UI contracts.
