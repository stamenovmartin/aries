# ARIES — Personal Interest Profile

What the user cares about, what they never want to see, and how ARIES decides whether an item
is worth their attention. Specification §25.

Deterministic — no model. It runs on every item from every source, must work with the network
down, and above all must **explain itself**: §25 requires the user be able to inspect and
override what ARIES concluded, and "the model thought so" is not inspectable.

## Matching

Terms match on **word boundaries**, never as substrings. `if "ai" in text` would match
*s**ai**d*, *em**ai**l*, *camp**ai**gn*, *Ukr**ai**ne*, *ag**ai**nst* — a profile built that
way calls almost everything relevant, and the failure looks like bad ranking rather than a
broken matcher.

* multi-word terms match as phrases, with flexible whitespace (`llm agents` matches `llm\nagents`)
* accents are folded, so `cafe` matches `café`
* terms with leading or trailing punctuation (`c++`, `.net`) drop the boundary on that side
* **no stemming** — `agent` does not match `agents`. Deliberate: stemming badly widens a topic
  invisibly. Add the plural as a synonym, which is explicit.

## Scoring

```
score = 1 − ∏ (1 − weightᵢ)      over every matching topic
```

Noisy-OR rather than a sum: a sum needs an arbitrary cap, and then the cap decides the answer
more than the weights do. This saturates naturally, stays in [0, 1], is monotonic, and lets
each topic's contribution be shown separately. One matching topic scores **exactly** its
weight.

An **avoided** topic disqualifies outright — score 0, naming the topic and the term. §25 lists
"topics I do not care about" as its own category: the user means *not this*, not *this, but
less*, so no accumulation of positive matches can outvote it.

## Weights, and who decides

```
effective weight  =  the user's weight        if they set one
                     else the learned weight  if ARIES inferred one
                     else interests.default_weight
```

`weight` is written only by the user; `learned_weight` only by the learning loop, which
**cannot reach the user's column**. So §25's "explicit user configuration has higher priority
than inferred preferences" is structural, not a rule someone must remember.

A shadowed inference is kept and reported, never dropped — the user can see what ARIES would
have said, and clearing their own weight falls back to it rather than to the default.

**Learning may weigh topics; it may not invent them.** `learn()` on an unknown topic is
refused. What the user follows is theirs; how much is negotiable.

## Synonyms bridge to sources

The Sources Registry matches topics as exact strings, so a source tagged `artificial
intelligence` was invisible to a user who wrote `ai`. `topics_for()` returns the canonical
topic *and* every synonym, which is what closes that gap — a synonym is a fact about what the
user means, so it lives here rather than on every source.

## Using it

```bash
./scripts/aries interests add --topic "LLM agents" --synonyms "agentic,ai agents" --weight 0.9
./scripts/aries interests add --topic cryptocurrency --stance avoid --synonyms "crypto,bitcoin"
./scripts/aries interests                       # weights, origins, and what ARIES would have said
./scripts/aries interests score --topic "Agentic AI agents arrive in 5G telecom networks"
```

```
0.960  Agentic AI agents arrive in 5G telecom networks
matches 2 topic(s): llm agents (0.90), telecom (0.60)
  · llm agents weight 0.90 (user) via agentic, ai agents
  · telecom weight 0.60 (default) via telecom, 5g
```

Over HTTP: `GET/POST /api/aries/interests`, `PATCH/DELETE /api/aries/interests/{topic}`,
`POST /api/aries/interests/score`. Reading needs `view_data`; editing needs `edit_task` — a
topic shapes what reaches the user but names nowhere ARIES will go.

Clearing a weight uses `{"clear_weight": true}`, not `{"weight": null}`: JSON cannot
distinguish "set this to nothing" from "I did not mention it".
