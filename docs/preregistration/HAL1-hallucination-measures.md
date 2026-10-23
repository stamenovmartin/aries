# HAL1: how often the model hallucinates, and how often ARIES lets it through (registered, descriptive)

**Registered:** 2026-10-22, before any of the measures below has been computed on any run. The runs it reads
already exist (H5, H4b, R1) or are registered (X1, R1b); the definitions and the script
(`experiments/thesis-improvements-20261022/hallucination_eval.py`) are committed first.

**Label: descriptive.** No hypothesis is tested and nothing enters a Holm family. The point is to separate two
things the thesis has so far reported together: what the **model** invents, and what the **system** accepts.
ARIES is designed so that a model claim does not become a result without verified evidence; HAL1 counts both
sides of that boundary.

## Definitions

Unit: one planner decision, one router decision, or one goal run, as stated. Every count has its denominator.

**Model level (what the language model produced):**

- **M1 invented action:** a planner decision that fails validation against the registry: a capability that
  does not exist, a missing required argument, an argument the capability does not have, or a malformed
  value. Denominator: planner decisions. Broken down by error kind (from the validation message).
- **M2 invented evidence:** a `finish` decision whose `evidence_refs` contain an id that is not among the
  goal's evidence ids at any time. Denominator: `finish` decisions.
- **M3 premature success claim:** a `finish` decision proposed while the goal has no verified evidence at all.
  Denominator: `finish` decisions.
- **M4 ungrounded path in a claim:** a `finish` or `fail` decision whose `summary` or `reason` names a path
  (the contract's path pattern) that occurs neither in the request nor in any observation or argument of the
  goal's steps. Denominator: those decisions that name at least one path.
- **M5 confident wrong action (router):** on items whose gold label is OUT_OF_SCOPE, the router acts with
  confidence ≥ 0.9. Denominator: gold OUT_OF_SCOPE items (R1 and R1b NL2Bash and CLINC150 raw outputs).

**System level (what ARIES let through):**

- **S1 false success:** a goal run that ends `done` while the independent oracle fails, or a control goal (N)
  that ends `done`. Denominator: goal runs (H5 sets G and N, X1, held-out goals).
- **S2 claims blocked:** `finish` proposals that the completion check rejected, over all `finish` proposals:
  how much of M2–M4 the verifier caught. Reported with S1.
- **S3 final text source:** for every goal run, whether the final card text was assembled by code from
  verified evidence (`done`/`answered`) or is a system status, and whether any final text carries model prose
  presented as fact. Counted, not judged.

## Data read (local run folders; only aggregates are written)

H5 runs (`thesis-followup-20261012/h5-runs/2026*`), H4b runs, X1 runs
(`thesis-improvements-20261022/*-reruns/2026*`), R1 and R1b router and planner raw files. The script never
writes item or request text; the output `hallucination-summary.json` holds counts and rates with
Clopper-Pearson 95% intervals, per condition.

## Limitations stated in advance

- M1–M4 are mechanical; a paraphrased hallucination without a path or an evidence id is not caught.
- M5 uses LLM gold labels (R1/R1b).
- The items were written by a model, not people; one machine; qwen2.5:7b.

## Amendment 1 (2026-10-22, before the final computation)

A dry computation on the existing H5 and H4b runs (nothing written) showed two defects in the script, fixed
before `hallucination-summary.json` is written: (1) S1 false `done` was divided by every outcome, held-out
goals included; it is now over G and N item-runs, as in H5, and the held-out false `done` has its own
denominator; (2) M1's kinds now separate a value the model made up in the wrong format (most often an
`expected_sha256` that is not a 64-character hex string) and the router's malformed output. The definitions
are unchanged.
