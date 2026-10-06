# ARIES — Memory

§14 asks for distinct memory layers rather than a chat log. This is what exists, which layer
each thing is, and — for each — who may write it.

**The rule that shapes all of it:** what the user said and what ARIES concluded are stored
**separately**, and meet only at the moment of resolution. Three subsystems implement the same
separation, and the fourth (the learning loop) is the one it was built for.

## What exists

| § layer | where it lives | written by |
|---|---|---|
| Preference | `aries_settings` (layered) · `aries_interests` | the user, and — at the learned layer only — the loop |
| Episodic | `aries_news_items` · `aries_briefs` · `aries_health_samples` | automations |
| Agent / workflow | `aries_automation_runs` · engine `task_runs`, `agent_steps` | the runner |
| Organisational | `aries_sources` · the interest profile | the user |
| Audit | engine `audit_events` (append-only) · `aries_learning_changes` · `aries_reversals` · `aries_feedback` | everything |
| Working | request-scoped context dicts | in-process only |
| Semantic | `aries_workspace_memories` (utterances) · `aries_workspace_conclusions` + `…_conclusion_sources` (inferences) | the user, and — at the learned layer only — the extraction cascade |

## Layered preference memory

A single key holds values from several sources at once. Resolution walks from strongest to
weakest and returns the first found; **losing values are kept, not overwritten**.

```
SECURITY 80   absolute
RESTRICTION 70  an explicit prohibition
USER 60         set in the UI, or said as a standing rule
INSTRUCTION 50  "for this task" — where the fast loop writes a narrow correction
PROJECT 40      scoped to one project
LEARNED 30      inferred; carries a confidence and a rationale
HISTORICAL 20   a weak prior
DEFAULT 10      what ships
```

Keeping the losers is what lets ARIES say *"you set 0.5; I would have said 0.72, because you
ignored 12 of 15 low scorers"* — and what makes clearing your own value fall back to the
inference rather than all the way to the default.

**Machine authors may write only `DEFAULT`, `HISTORICAL`, `LEARNED`.** Enforced on the write
path, not merely by read order. Settings marked `user_only` refuse machine writes entirely.

## Provenance

Everything ARIES concluded records how it got there.

| record | carries |
|---|---|
| `aries_settings` | value, layer, scope, confidence, rationale, who set it, when |
| `aries_interests` | user weight and learned weight **in separate columns**, learned rationale, confidence, engagement counters |
| `aries_learning_changes` | previous → new, direction, confidence, rationale, scope, **policy version**, window, the interval it decided from, classification, whether it reversed the previous change |
| `aries_reversals` | what was believed, what contradicted it, the classification, the interval, observations, status (pending/applied/abandoned), confirmations, policy version |
| `aries_feedback` | what was said, what ARIES made of it, scope, confidence, the question it asked, whether it was applied and at which layer |
| `aries_workspace_conclusions` | the statement, its confidence, its rationale, which of `APPEND`/`SUPERSEDE`/`COEXIST` it was, which cascade stage decided, what it relates to, and four timestamps |
| `aries_workspace_conclusion_sources` | a **foreign key** to every utterance a conclusion was drawn from. A conclusion with no row here is refused at the write path, because it could not be explained |

`aries learning explain <subject>` is the union of these, for a setting or a topic: what is
believed, why, from which evidence, at what scope, how confident, and whether it is explicit or
learned.

## What is deliberately not remembered

* **Secrets.** Never in settings, never in source URLs (refused at validation), never in
  general memory. Credentials belong in the engine's encrypted store.
* **Paths under `privacy.excluded_paths`** — enforced by the Sources Registry, resolved through
  symlinks before judging.
* **Items the user never saw.** The learning loop draws evidence only from `delivered` and
  `held`. Counting withheld items as "not engaged" would let ARIES confirm its own guesses —
  a topic scores low, so it is never shown, so it looks uninteresting, so it scores lower.
* **Topics under `privacy.excluded_memory_topics`** — enforced since semantic memory, at stage 1
  of the extraction cascade, which is *before* anything is embedded, and therefore on the machine
  write path as well as the user's. `tests/test_memory.py` asserts it.
* **Anything that looks like a credential** — passwords, API keys, private keys, card numbers and
  IBANs are refused by the same gate, by pattern, whoever offered them.
* **Commands.** "отвори YouTube", "play some music" and their four hundred repetitions are
  instructions, not facts. A habit belongs to the learning loop's interest weights.

## Retention

| table | kept |
|---|---|
| `aries_health_samples` | 90 days (`baseline.prune`); the baseline window is 14 |
| `aries_news_items` | indefinitely — including what was *not* shown, so "why didn't you tell me?" has an answer |
| `aries_learning_changes`, `aries_reversals`, `aries_feedback` | indefinitely; append-only |
| `aries_workspace_memories`, `aries_workspace_conclusions` | indefinitely — **expired, never deleted** |
| `audit_events` | indefinitely; immutability enforced by the engine |

No pruning exists yet for the append-only learning tables. At one learning pass a day they grow
slowly; a retention policy is owed before that stops being true.

## Semantic memory

§14's vector memory. ARIES decides for itself what was worth keeping out of what the user said,
writes it down unasked, and uses it later. The same rule shapes it as everything above, and here
it is structural rather than procedural:

| | `aries_workspace_memories` | `aries_workspace_conclusions` |
|---|---|---|
| holds | what the user **said**, verbatim | what ARIES **concluded** |
| language | the one it was spoken in — never translated, never summarised | a copy of the utterance; **no model writes these words** |
| layer | USER (60), always | LEARNED (30), always |
| written by | `user`, `voice`, `chat`, `shell`, `ui` — human channels only | `aries:memory` |
| carries | no confidence, no rationale — there is nothing to justify | a confidence, a rationale, a decision, a stage, and its sources |

`store.record` refuses a source that is not a human channel. `store.conclude` refuses any layer
outside `MACHINE_WRITABLE`, and refuses a conclusion with no source utterance. Both refusals
happen before the row exists.

**Not generating the memory text is the guarantee.** mem0 v2 dropped its same-language promise
and stores Macedonian speech translated into English. That cannot happen here, because no model
is ever asked to produce the words — it contributes one label out of four and a probability, and
the rationale is composed deterministically from the numbers.

### Four timestamps, and no delete

Zep's separation of world time from system time (arXiv:2501.13956):

```
valid_at    when it became true in the world
invalid_at  when it stopped being true in the world
created_at  when the row was written
expired_at  when ARIES stopped believing it
```

`forget` sets `expired_at` and withdraws every conclusion drawn from that utterance — keeping the
inference while deleting its evidence would leave something that can no longer be explained. A
contradiction sets the loser's `invalid_at` and `superseded_by`.

**Contradictions are arbitrated by the clock, not by the model.** The model says *whether* two
statements conflict; the later `valid_at` wins, always, without being asked. And a machine
supersession withdraws only the LEARNED conclusion — it never expires the utterance, because
expiring is a write and what the user said is at layer USER. The user said X on Tuesday and
not-X on Friday; both stay on the record, and only the belief "X is currently the case" is
withdrawn.

### Deciding what to keep — three stages, cheapest first

| | cost | decides |
|---|---|---|
| 1 · gate | ~0 ms | excluded topics, credentials, commands, length, the privacy switch |
| 2 · novelty | ~8 ms | embed once; cosine against the cached matrix. Clearly redundant → bump the neighbour's recency and stop. Clearly novel → keep |
| 3 · the model | ~0.1 s | one bare enum — `APPEND` / `SUPERSEDE` / `COEXIST` / `ABORT` — with a calibrated probability |

Only the uncertain middle band reaches stage 3, and **none of it is on the voice path**:
`observe_later` queues the utterance and returns in microseconds, and the cascade runs seconds
after the request was already acted on.

`COEXIST` is the label that earns its place. A preference that varies by circumstance — coffee in
the morning, tea at night — is not a contradiction, and resolving it by picking a winner destroys
the knowledge that made it useful (TANGLE, arXiv:2608.13921).

### Retrieval

**1 October 2026 privacy correction:** changing `privacy.excluded_memory_topics`
now applies to existing utterances and conclusions before ranking, limiting or
recency updates. A conclusion is also excluded when its source utterance matches,
even if its own text differs. Excluded neighbours are removed before the automatic
memory cascade sees their text, and a model relation cannot update an excluded row.
These exclusions hide context without deleting history; clearing the setting makes
the rows eligible again.

Privacy-policy read failures return no optional retrieval context, reject explicit
memory writes and stop automatic writes at the gate. Privacy is checked again after
pending inference, before saving or updating recency. Common information questions
in Macedonian, Latin transliteration and English are refused by the automatic gate;
explicit `remember()` remains a separate user-directed path. This is a bounded
question-prefix recognizer, not general understanding of whether every sentence is
worth remembering. Regression evidence is in `tests/test_memory_privacy.py`.

`aries/workspace/retrieval.py`, version `semantic-v3`, inside the same versioned scheme as
`overlap-v1` and `focused-v2` so the same A/B, the same setting and the same rollback apply.
Scored per Park et al. (arXiv:2304.03442):

```
w_sim·similarity + w_recency·decay + w_importance·importance + w_layer·layer
```

with the decay half-life chosen **per memory kind** (an identity claim outlives a plan by three
orders of magnitude) and recency refreshed **on retrieval** — being useful is the one piece of
evidence that a memory is still current which costs nothing to collect. `layer` is where the two
tables meet, and the only place they do: at equal similarity a USER utterance outranks a LEARNED
conclusion, by arithmetic.

### Does any of it beat just keeping everything?

Not on retrieval — and something else matters more than either.
[`experiments/memory/analysis.md`](../experiments/memory/analysis.md) measures
it against store-everything-verbatim with the same embedder — the honest baseline, which is not
"no memory" — and the extraction retrieved **one fewer** answer (17/23 against 18/23,
p = 1.000) while being the only variant that never returned a contradicted fact or a refused topic
(25/25 against 23/25, p = 0.500), on 24 rows instead of 33. Neither difference is significant at
this fixture size. **On retrieval alone it is a cost optimisation, not a capability**, and one of
its three supersessions was wrong.

**The embedder is worth more than the method.** Swapping `e5-base-int8` for `bge-m3` and changing
nothing else takes the baseline from 18/23 to 23/23 and MRR from 0.659 to 0.927 — five answers,
against the cascade's minus one. The default stays e5 on availability rather than quality: it
runs in-process from a 279 MB file with no service and no VRAM, at 9 ms against bge-m3's 38 ms.
`workspace.memory_embedder` switches it, and the evidence for switching is in the analysis.
