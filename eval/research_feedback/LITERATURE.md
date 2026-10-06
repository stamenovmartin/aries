# Literature checked against primary sources, 2026-10-03

These are methodological precedents, not evidence that ARIES improves anything.
The full HTML methods were inspected for the first four; abstracts for CRITIC/Reflexion.

| Source | What to use | Limit on the claim |
|---|---|---|
| [From Confident Closing to Silent Failure](https://arxiv.org/html/2606.09863v1) | Separate completion claims from environment ground truth; retain ambiguous claims. Its AppWorld analysis uses a structured status signal. | The negative LLM-judge findings apply to the tested configurations/domains, not every possible judge. Its within-failure prevalence denominator is not our all-trial denominator. |
| [ReliabilityBench](https://arxiv.org/html/2601.06112v1) | Cross fault conditions with repeated trials and architecture; retain task/state identity. | Its main experiment uses two trials per configuration. Twenty repetitions is our proposed design choice, not a requirement or power guarantee derived from this paper. |
| [Reason Less, Verify More](https://arxiv.org/html/2607.07405v1) | Read-only pre-execution policy gates, negative controls, task-level paired bootstrap, disjoint-seed replication. | The 29.6% to 42.0% result is 74/250 to105/250 on50tasks×5trials, a12.4percentage-point difference. It is not an ARIES target or transferable effect size. |
| [Verification as an Architectural Layer: V-Model](https://arxiv.org/html/2609.31937v1) | Separate generation, verification and binding control; distinguish gate contributions from planner contributions. | The pilot is47executions on multi-hop QA and omits the integration-level verifier pair. It explicitly limits its empirical claim to termination behavior, not large-scale accuracy. |
| [CRITIC](https://arxiv.org/abs/2305.11738) | External tool feedback can inform revision without changing model weights. | Post-action state feedback is a narrower experimental setting, not proof that the general feedback loop is novel. |
| [Reflexion](https://arxiv.org/abs/2303.11366) | Feedback and episodic memory can affect subsequent attempts without weight updates. | Freeze memory between experimental arms; otherwise history adaptation changes a second independent variable. Do not call ordinary contextual feedback trained reinforcement learning. |

## Positioning after this review

Proposed empirical contribution: measure how planner-visible, independently re-read
post-action state changes subsequent LLM decisions under tool/state discrepancies, with
the execution policy, completion controller, model and resources held fixed.

Pre-execution permission enforcement and post-action verification address different points
in the lifecycle. That distinction helps delimit the study; by itself it establishes no
global novelty. The V-model and feedback literature already cover substantial neighboring
ground. Report a bounded empirical contribution, not a first-ever verification architecture.

The current ARIES pilot demonstrates a distinction worth preserving: a model can repeatedly
propose unsupported finish while an external controller prevents user-visible false success.
Runtime bounding of that repetition is not evidence of better reasoning. Keep both outcomes.
