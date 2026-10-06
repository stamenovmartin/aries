# ARIES — Learning

Three loops (§16). One exists.

| loop | speed | status |
|---|---|---|
| **fast** | **seconds — something you say changes what ARIES does** | **built (Entry 010)** |
| **medium** | **days — outcomes adjust preferences** | **built (Entry 008), reversible (Entry 010)** |
| slow | weeks — aggregated evidence proposes improvements, sandboxed (§18) | not built |

## What the medium loop does

Reads what happened to the items ARIES put in front of the user, and adjusts two things: how much
each topic is worth, and how high the relevance bar should be.

```bash
./scripts/aries learning evidence    # what it has observed, with confidence intervals
./scripts/aries learning propose     # what it would change — writes nothing
./scripts/aries learning run         # a pass
```

## Four rules it cannot break

1. **It writes the learned layer only.** `interests.learn()` and `SettingsService.learn()`
   physically cannot write a user value. If you have set a weight, the inference is stored,
   reported as shadowed, and does nothing until you clear yours.
2. **It may weigh topics; it may not invent them.** Learning about a topic you never chose is
   refused. What you follow is yours; how much is negotiable.
3. **It acts on intervals, not rates.** One click in three is not 33% engagement, it is no
   evidence.
4. **It moves slowly and can be watched.** Every change is capped per pass, carries a written
   rationale, and `learning.apply_changes = false` makes it propose without acting.

## Why intervals

```
 1/3  → [0.06, 0.79]   too wide to mean anything → do nothing
 2/40 → [0.01, 0.17]   low even optimistically   → lower it
33/33 → [0.90, 1.00]   high even pessimistically → raise it
```

The Wilson score interval behaves sensibly at small `n` and near 0 or 1, which is the regime a
personal system lives in. A raw rate would lurch after every handful of clicks — and a system
whose opinions change for no visible reason is worse than one that never learns.

## The circular-evidence trap

Evidence comes only from items the user could act on: `delivered` and `held`. Items **below the
threshold are excluded**, and that exclusion is the important one — counting them as "not engaged"
would teach the system that everything it withheld was uninteresting. A topic scored low, so it
was never shown, so it looked uninteresting, so it scored lower. That is how a recommender
collapses onto its own first guess.

For the same reason **the relevance bar only ever rises**. Evidence for "you would have wanted
more" could only come from items you never saw. If the bar is too high, you lower it; the system
only offers to be quieter.

## Settings

`learning.enabled` (off by default) · `apply_changes` (user-only) · `interval_hours` ·
`window_days` · `min_observations` (10) · `engaged_threshold` (0.4) · `ignored_threshold` (0.1) ·
`noisy_threshold` (0.3) · `max_step` (0.15).

## Reversal: taking a learned preference back

An established learned preference may be reversed by contradicting evidence — but reversing
must be **harder than forming**, or every settled preference is one quiet fortnight from being
undone.

### Hysteresis is a confidence level, not a moved threshold

The first attempt tightened the threshold itself (0.10 → 0.06). That is the wrong currency: a
Wilson bound sits well above the point estimate at realistic sample sizes, so it demanded
literally zero engagement across sixty observations. The rule was not strict, it was
**unreachable** — and an unreachable rule is the same as an absent one.

"Be more certain" is what hysteresis means, and certainty belongs in the confidence level.
Reversing evaluates the **same** threshold with a **wider** interval:

```
       ordinary (95%)   reversing (≈99%)   threshold 0.10
0/60       0.060             0.094           reverses
1/60       0.089             0.122           does NOT reverse   ← the asymmetry
```

`1/60` would establish a low weight on a fresh topic and is not enough to overturn a settled
one.

### Five things that look alike

A falling engagement rate has at least five causes, and only one is a reversal. The diagnoses
are asked **first** — neither contextual collapse nor fatigue looks contradictory in aggregate,
so both were unreachable while they sat after the strength test.

| | what it is | what ARIES does |
|---|---|---|
| `noise` | not decisive even at face value | nothing |
| `temporary` | decisive recently, not over the window | wait |
| `contextual` | collapsed for one source, healthy for another | **the source is the finding** — the topic is left alone |
| `fatigue` | declining steadily but still positive | decay gently, do not invert |
| `sustained` | decisive recently **and** over the window | open a pending reversal |

### Confirmation, and withdrawal

A reversal is not applied when first suspected. It is recorded as **pending**, confirmed on
later passes, and **abandoned** the moment the contradiction stops holding — so alternating
evidence opens and withdraws a reversal repeatedly and changes nothing. Withdrawal is recorded,
because ARIES declining to act is information.

### Oscillation

Each time the loop turns around on a target, its allowed step halves. After
`learning.max_reversals` turnarounds the target is **frozen** and handed back:

> *I kept changing my mind about 'programming' — you decide.*

A system that cannot decide should hand the decision back rather than keep performing
indecision. Setting the weight explicitly releases the freeze.

```bash
./scripts/aries learning reversals    # contested preferences, pending and applied
./scripts/aries learning history      # every change, with policy version
```

## The fast loop: something you say

```
you say something → classify → infer scope → confidence → apply or ASK → audit
```

Deterministic patterns, no model: it works offline, it can explain itself, and unmatched input
becomes `not_feedback` rather than a confident misreading.

### It does not treat every sentence as feedback

"what about the other one?", "the deploy finished at 5pm" — classified `not_feedback`, recorded
so the reading is auditable, acted on by nothing.

### It asks rather than overgeneralising

§15's example is the whole problem: *"this catalogue is too dark"* must become **prefer brighter
backgrounds for the Insomnia autumn catalogue**, not *the user dislikes dark interfaces*.

```
$ aries learning feedback --text "shorter"
  heard: correction   scope current_result · confidence 50%
  ? Should I make briefs shorter just this once, or from now on?

$ aries learning feedback --text "always keep briefs shorter"
  heard: persistent_rule   scope global · confidence 90%
  applied briefing.length = "standard"  at the user layer
```

### Scope becomes a layer

| what you said | scope | layer |
|---|---|---|
| "just this once, shorter" | current result | `INSTRUCTION` |
| "shorter for this project" | project | `PROJECT` |
| "always keep briefs shorter" | global | `USER` |
| "shorter" | *asks* | nothing written |

An explicit statement carries **user** authority because the user made it. The medium loop can
never reach these layers; a person speaking can.

### Inspecting it

```bash
./scripts/aries learning feedback              # what was said and what came of it
./scripts/aries learning preferences           # everything decided, and by whom
./scripts/aries learning explain briefing.length
```

`explain` answers six questions for a setting or a topic: what is believed now, why, from what
evidence, at what scope, how confident, and whether it is explicit or learned.

## Not built yet

The **slow loop** (§18): aggregated evidence generating improvement hypotheses, sandboxed and
benchmarked before promotion. Nothing here changes ARIES's own code or topology.

Source trust and clickbait down-ranking (§13/03) are unimplemented; source *ordering* already
self-adjusts on observed usefulness, which covers part of it.

Feedback that maps to no known setting (`"I prefer the short version"`) is classified and
recorded but cannot act — the phrase-to-setting table is deliberately small, since inventing a
setting change from free text is the overgeneralisation this design exists to avoid.

No retention policy for the append-only learning tables.
