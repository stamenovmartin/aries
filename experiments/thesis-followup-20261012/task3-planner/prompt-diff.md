# Planner prompts: follow-up vs ARIES-FINAL-20261006 (dry run, no model calls)

Compared: the 24 production prompts captured by the follow-up dry run (`runs/20261012T170558.287607Z/prompts/`)
with those of the frozen run (`experiments/thesis-final-20261006/planner/runs/20261006T173518.677345Z/prompts/`).

- **21 of 24 are byte-identical.**
- **3 differ (`p20`, `p21`, `p22`).** These are the cases whose synthetic data already contains a verified
  observation, so `ARIES_PLANNER_CLARIFY` offers the clarification option. The differences in these three:
  - one added instruction message about `ask_clarification`;
  - `ask_clarification` added to the action enum;
  - the `question` and `choices` properties added to the schema;
  - the derived `generation_kwargs.provenance.payload_sha256`, which is a hash of the messages and schema.
- With those removed, all three are identical to the frozen prompts: messages, schema and generation settings.
