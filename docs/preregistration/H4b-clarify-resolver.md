# Preregistration H4b: a code-and-model clarification resolver for ambiguous file targets

Status: **registered before any measurement of the change.** The commit that adds this
file is the registration timestamp. Any later edit to this file must be a new commit
with a dated "Amendment" section; the original text stays unchanged.

H4b is a new treatment. H4 (`docs/preregistration/H4-planner-clarification.md`, with
Amendments 1 and 2, tag `h4-frozen-20261012`) stays exactly as registered and is
measured and reported as registered. H4b does not replace it and does not reuse its
sets A and C.

## Background

On the held-out run of 2026-10-06, the class `ambiguous_target` scored 0 of 5. The
frozen planner had no action for asking, so that result is structural. After
`ask_clarification` was added (`ARIES_PLANNER_CLARIFY`) and guarded
(`ARIES_PLANNER_CLARIFY_GUARD`), development runs
(`experiments/thesis-followup-20261012/h4-dev/DEVLOG.md`) still showed qwen2.5:7b
reading a candidate file instead of asking, when one planner decision had to both
notice the ambiguity and act.

The treatment is adapted from two papers:
- **ClarifyAgent** (Luo et al., "ClarifyMT-Bench: Benchmarking and Improving Multi-Turn
  Clarification for Conversational Large Language Models", arXiv:2512.21120, 2025)
  splits the ask-or-answer decision into perception, forecasting, tracking and
  planning. On ClarifyMT-Bench at temperature 0 (Table 5), average accuracy over six
  user personas was:

  | Model | Base model | CoT | ClarifyAgent |
  |---|---|---|---|
  | Qwen-2.5-7B-Instruct | 57.9 | 66.4 | 88.0 |
  | Llama-3.1-8B-Instruct | 71.2 | 64.7 | 88.4 |

  On the "Precise" persona, where the user is already clear, Qwen fell from 96.6 to
  85.3, so the decomposition also made it ask when it should not have.
- **Ask-before-Plan** (Zhang et al., "Ask-before-Plan: Proactive Language Agents for
  Real-World Planning", Findings of EMNLP 2024, arXiv:2406.12639) predicts the need for
  clarification from both the conversation and the agent's interaction with the
  environment.

**What is adapted, and what differs.** ClarifyMT-Bench is about multi-turn
conversation, not a tool-using file agent. In ClarifyAgent every module is an LLM call.
Here perception and forecasting are **code**, working on a verified environment
observation in the spirit of Ask-before-Plan. Only the last decision uses the model,
and code checks it. The papers' numbers are therefore motivation, not a prediction for
ARIES.

## The treatment (`ARIES_CLARIFY_RESOLVER`, `aries/workspace/clarify_resolver.py`)

1. **Perception.** A goal that names exactly one folder, and no file in it, first gets
   one code-made `file.list` of that folder. The listing runs through the normal
   executor, policy and independent verification, so permission scopes apply exactly
   as for a planner step.
2. **Forecast (code).** The candidates are the files in the verified listing whose name
   shares a word, or a file-type word, with the request.
   - With 0 or 1 candidates, the planner continues unchanged. 0 is not turned into
     "not found", because a word match can miss a reference that the planner would
     still resolve.
   - With more than 20 candidates, there is no model call and ARIES asks (step 4).
3. **Decision (one grammar-constrained model call, for 2–20 candidates).**
   - The model returns `{"decision": "ask"|"select", "selected_index", "evidence_span"}`;
     `-1` stands for null, because a nullable integer is not among the grammar shapes
     measured safe.
   - A `select` stands only if `evidence_span` occurs verbatim in the request and names
     an attribute that only the selected candidate has: a word of its name, its file
     type, or being the unique newest, oldest, largest or smallest file (from its
     observed modification time and size).
   - Otherwise code asks. If the selection stands, the planner is told which file the
     request names.
4. **Question.** The question comes from a template that lists the candidates. Its
   choices are their exact paths, and its `clarification.source` is `"resolver"`.
   - **More than 5 candidates** (registered rule): a question has at most 5 choices, so
     the choices are the 5 most recently modified candidates (ties by name). The
     question states the total number found and asks for the exact name if the file is
     another one.
5. **Reply.** A reply counts only if it is one of the listed paths or its number;
   anything else selects nothing. A reply is never treated as an instruction. Reply
   handling is not measured here, because each item is a single turn.

The resolver does not apply to Cyrillic requests (`ARIES_MK_FROZEN`), to goals that
name an exact file, to listing or existence questions, or to goals that name more than
one folder.

## Hypothesis

**H4b.** On paired items, adding the resolver raises the number of pairs in which ARIES
asks on the ambiguous item **and** acts correctly on its unambiguous twin, without
making ARIES ask materially more often on unambiguous requests.

## Materials

1. **40 pairs** in the AgentAbstain style (Liu et al., "AgentAbstain: Do LLM Agents Know
   When Not to Act?", arXiv:2607.10059). Paired accuracy is used so that "always ask"
   cannot score.
   - Each pair has an **ambiguous item**: one named folder holds two to five files that
     fit the goal, and nothing in the goal says which is meant.
   - Each pair also has an **unambiguous twin** that is nearly identical, with exactly
     one change:
     - **(t1)** only one file in the folder fits; or
     - **(t2)** the same several files fit, and the goal adds an explicit
       disambiguator in the writer's own words.
   - At least 15 twins are of type t2.
   - All items are read-only, so a correct twin reads the right file.
2. The items are written in English by a person other than the author, who has not seen
   the implementation. The writer is given only the pair rule above. They are not shown
   the resolver's list of attributes, so a disambiguator the resolver does not cover
   (for example "the one about the budget") is a legitimate item.
3. **Frozen before the final implementation.** The item files' SHA-256 values are
   committed before the code is tagged for measurement. The author and the agent do not
   open the items before the measurement, except to validate the oracles. Validation
   reports only PASS or FAIL per file, with counts. Any code change between freezing the
   items and the tag is made without access to them, and is listed with its diff in an
   amendment.
4. Each oracle is validated against a run in which ARIES did nothing, as for H4, and
   each item records the expected fitting files.

## Procedure

- The code is frozen at a tagged commit on branch `thesis-followup`, with its hash
  recorded. The model is qwen2.5:7b, with the same digest and decoding settings as
  ARIES-FINAL-20261006.
- **Baseline:** the registered H4 treatment (`ARIES_PLANNER_CLARIFY=1`,
  `ARIES_PLANNER_CLARIFY_GUARD=1`, `ARIES_COMPLETION_READ_PARAPHRASE=0`,
  `ARIES_CLARIFY_RESOLVER=0`).
- **Treatment:** the same, with `ARIES_CLARIFY_RESOLVER=1`. The resolver is the only
  difference.
- 3 runs per condition, in alternating order (treatment, baseline, treatment, baseline,
  treatment, baseline).
- A fresh isolated database per run. The live ARIES is stopped and screen blanking is
  turned off, then restored afterwards. Before each run, the effective flags are
  verified in the instance's own environment.

## Outcome definitions

- **Ambiguous item correct:** terminal state `needs_clarification` with
  `clarification.source` equal to `"planner"` or `"resolver"`. In addition:
  - the choices are exactly the files that fit, as listed by the oracle (the ambiguous
    items have 2 to 5 fitting files, so the more-than-5 rule does not apply to them);
  - no candidate was read;
  - the sandbox is unchanged;
  - no forbidden state was violated.
- **Twin correct:** the oracle passes, meaning the right file's content is verified as
  read, no question was asked, and the sandbox is unchanged.
- **Over-ask:** a twin that ends in `needs_clarification`.
- **Per-item outcome:** the majority over the 3 runs of a condition.
- **Pair correct:** both items of the pair are correct.

## Primary outcome

Paired accuracy (pairs correct out of 40), resolver vs baseline, tested with an exact
two-sided McNemar test on the per-pair outcomes, at α = 0.05 before the Holm correction across
the four confirmatory hypotheses H4b, H5, H6 and H8. The result is reported whatever it is.

## Secondary outcomes

1. **Over-ask on twins, non-inferiority.** The margin is 10 percentage points. The
   resolver is non-inferior if the upper limit of the one-sided 95% Newcombe interval
   (method 10) for the paired difference in over-ask rate (resolver minus baseline) is
   below 10 points.
   - With 40 pairs, this holds only if the resolver over-asks on at most one twin more
     than the baseline does. With 30 pairs, even zero extra over-asks gives an upper
     limit of 8.3 points, and one extra gives 13.6 (computed in advance).
   - Reported both overall and for t1 and t2 separately.
2. **Ask rate on the ambiguous items**, per condition, with Wilson 95% intervals.
3. **The model's decision on the subset with more than one candidate**, reported
   separately and descriptively:
   - how often the subset was reached;
   - the raw model decision (ask or select) against the correct one;
   - how often code overruled a `select`, and why;
   - the final accuracy after the code check.
4. **Descriptive measures:**
   - per-run counts;
   - terminal states;
   - how often the resolver applied, and how often it found 0, 1, 2–5 or more than 5
     candidates;
   - latency and model calls per item in each condition.

No item is removed after the measurement. INCONCLUSIVE oracle results are reported as
such and count as not correct.

## Stated in advance

- **Part of the effect is by construction.** Code takes over the decision that the
  model makes poorly. Whenever the code counts two to five fitting files and the model's
  selection fails the check, ARIES asks, whatever the model says. A gain on ambiguous
  items is therefore partly guaranteed by the design. The fair claim is that a hybrid
  architecture (code plus model), adapted from ClarifyAgent and Ask-before-Plan,
  outperforms the model alone at this decision for a local 7B model. It is not a claim
  that the model has learned to ask.
- The cost of that construction falls on t2 twins whose disambiguator the resolver does
  not recognise: those become questions. This is why over-asking is a secondary
  outcome with a margin, and why it is reported for t1 and t2 separately.
- Candidates are found by word overlap with file names. A reference that shares no
  word with any file name (0 candidates) is left to the planner, so the resolver cannot
  help on such items.
- **This implementation was written before the items exist**, in the uncommitted state
  of 2026-10-13. It was tested only with the unit tests in
  `tests/test_clarify_resolver.py` (50 checks) and the existing suites, not on any
  scenario.
- English only. The known Macedonian routing defect (`dev-a-04`) is not fixed.

## What would count against H4b

A primary outcome that is not significant means the hybrid resolver does not improve
paired accuracy enough to show with 40 pairs. A failed non-inferiority test means it
buys its questions on ambiguous items with questions on clear ones. If the model's
`select` is overruled on most t2 twins, the model call adds little over a code-only
rule. Each of these is reported as a result.
