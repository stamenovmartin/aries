# Offline policy artifact registry

`aries.workspace.policy_artifacts.Registry(path)` requires an explicit SQLite
path. It never reads or changes live runtime settings. Only bounded context size
and item count policies are supported. A selected policy is an offline review
decision, **not deployment authorization**.

Workflow: store baseline/candidate policies and fixture contents; register a plan
with assigned case/seed pairs, source/environment/scorer digests, objective,
required telemetry, outcome floor and resource guards; store both arms' trials
and raw evidence; evaluate; explicitly initialize/promote/rollback a named
selection with actor, reason and expected revision. Rollback is another history
event and never deletes failed experiments. Default outcome floor requires every
assigned candidate outcome to be verified; fixtures with expected failures must
declare a suitable floor before recording observations.

Artifacts use strict canonical finite JSON and SHA-256. Evaluation rechecks
policy/fixture integrity and both evaluator source hashes. Promotion recomputes
the gate rather than trusting the saved eligibility bit. One SQLite transaction
couples an append-only-by-API decision chain and its selected pointer. Revision
checks prevent stale reviews, including baseline→candidate→baseline cycles.
Read snapshots validate history continuity and pointer consistency.

Validation from the repository root:
`.venv/bin/python -B -m unittest tests.test_policy_artifacts -v`.
The saved runner executes the registry acceptance tests and existing numerical
gate tests in separate processes. All data is synthetic and databases temporary.
Controlled failure cases include cheaper unsafe/unverified results, omitted
outcomes, tool-call regression, missing telemetry, environment/gate drift,
database corruption, four concurrent reviewers and an injected transaction abort.

Limits: producer-supplied raw evidence and provenance are not authenticated.
Hashes bind bytes, not factual truth, external preregistration time or provenance.
A privileged database writer can replace an entire valid history; no external
signed anchor or backup recovery exists. Tests establish local behavior, not
statistical policy quality. No actual model-policy baseline/ablation, latency,
token or billed-cost gain has been measured by this batch. These and held-out
acceptance remain prerequisites before connecting selections to runtime.
There is no candidate generation, automatic evolution or live deployment here.
Rollback covers this registry's selected configuration, not external actions or
live service state.
