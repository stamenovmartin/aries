# Reviewer guide

## Водич за преглед (македонски)

Ова складиште содржи **ARIES**: асистент за Ubuntu/GNOME што се управува со говор или текст и извршува вистински
дејства на компјутерот (фајлови, прозорци, системски сервиси, прелистувач). Тука се вклучени два проекти:

- **Дипломска работа**: агентот. Тоа е рутерот што одлучува дали да дејствува или да одбие, planner-от што ја
  избира алатката, верификаторите што проверуваат дали дејството навистина се случило, и completion contract-от
  и прашањата за појаснување.
- **Проект по ИИС**: информацискиот слој. Тоа се интересите и вестите, учењето од повратни информации и
  семантичката меморија.

Секоја бројка во резултатите е запишана во фајл и има наведен именител (на пр. 229/500). Секоја потврдна
хипотеза е **пререгистрирана**: хипотезата, податоците и критериумот се запишани и commit-нати пред мерењето.
Негативните резултати се пријавени исто како и позитивните.

**Каде да се почне:**

**Евалуација на јавни податочни множества.** Секоја компонента е мерена и на јавно множество, не само на
авторски фикстури:
- избор на алатка: NL2Bash и CLINC150 (R1, R1b), и со четири локални модели (M2);
- верификатори: 218 вметнати грешки (H8);
- меморија: LoCoMo;
- вести и учење: MIND-small.

Табела со множествата, примероците, ознаките и резултатите има во главниот
[`README.md`](../README.md#evaluation-on-public-datasets), во делот „Evaluation on public datasets“.

1. Оваа страница, табелата „Research questions" подолу: секое прашање, неговиот резултат и каде се доказите.
2. [`experiments/thesis-followup-20261012/RESULTS.md`](../experiments/thesis-followup-20261012/RESULTS.md): сите
   резултати од дипломската на едно место, секој со ознака (потврден, истражувачки, описен).
3. [`experiments/iis/real-data/README.md`](../experiments/iis/real-data/README.md): резултатите од ИИС на
   јавни податоци (MIND, LoCoMo).
4. [`experiments/analysis/README.md`](../experiments/analysis/README.md): сите споредби како графици.
5. [`docs/preregistration/`](preregistration/): пререгистрациите.

---

## What is where

```
aries/                 the assistant (Python): router, planner, executor, verifiers, memory, interests, learning
aries_ui/              the Control Centre (GTK)
shell/                 the GNOME Shell extension (top bar, dock, command bar)
tests/                 the test suite (make test)
eval/                  fixtures for end-to-end runs (agent_suite, smoke)
experiments/           every measurement: inputs, scripts, raw outputs, summaries
  thesis/INDEX.md      map of the thesis experiments
  iis/INDEX.md         map of the IIS experiments
  archive/INDEX.md     superseded and early experiments
docs/                  documentation; docs/INDEX.md lists every document
  preregistration/     the registered hypotheses, with dated amendments
  AUDIT.md             the 2026-10-22 code audit and what was fixed
verification/          the frozen verifier ledger and its reproduction script
vendor/                the vendored agentic-core engine
scripts/               install, test, evaluation and helper scripts
```

## Research questions

**Label meanings.** *Confirmatory* means the hypothesis was preregistered and measured as registered.
*Exploratory* means the analysis was not registered as a test. *Descriptive* means counts with no test.

### Thesis: the agent

| # | Question | Result | Label | Evidence |
|---|---|---|---|---|
| H6 | Does an explicit abstention instruction (A1) make the router decline better than no instruction (A0), on 300 new requests? | Yes: 186/300 vs 152/300, McNemar p = 1.0 × 10⁻⁶, Holm 3.1 × 10⁻⁶ | confirmatory | [RESULTS §9](../experiments/thesis-followup-20261012/RESULTS.md), [`h6-run/`](../experiments/thesis-followup-20261012/h6-run/) |
| H8 | Do the hardened verifiers detect more injected faults than the frozen ones? | Yes: 188/218 vs 155/218 mutants killed, p = 1.2 × 10⁻¹⁰, Holm 4.7 × 10⁻¹⁰ | confirmatory | [RESULTS §8](../experiments/thesis-followup-20261012/RESULTS.md), [`h8/`](../experiments/thesis-followup-20261012/h8/) |
| H5 | Does a typed completion contract let more goals finish correctly? | No: 2/15 vs 0/15, p = 0.25; false "done" rose from 3/75 to 12/75 | confirmatory | [RESULTS §10](../experiments/thesis-followup-20261012/RESULTS.md), [`h5-runs/`](../experiments/thesis-followup-20261012/h5-runs/) |
| H4b | Can a resolver tell an ambiguous request (ask) from an unambiguous twin (act)? | No: it asked on every item; pairs correct 0/40 with and without it | confirmatory | [RESULTS §11](../experiments/thesis-followup-20261012/RESULTS.md), [`h4b-runs/`](../experiments/thesis-followup-20261012/h4b-runs/) |
| R1 | On public data (NL2Bash, CLINC150), how well does ARIES choose a tool and detect out-of-scope requests, against simple baselines? | Worse than the baselines: NL2Bash 229/500 vs zero-shot 321/500; CLINC150 277/600 vs zero-shot 336/600 | confirmatory (own family) | [RESULTS §13](../experiments/thesis-followup-20261012/RESULTS.md), [`thesis-r1-real-data/`](../experiments/thesis-r1-real-data/) |
| R1b | Do the remedies for R1's two causes help on new public samples? | Yes against frozen ARIES on both datasets and against zero-shot on NL2Bash (348/500 vs 233/500 and 320/500); not against zero-shot on CLINC150 (342/600 vs 334/600, Holm p = 0.48); the gain is in abstention, in-scope accuracy is lower | confirmatory (own family) | [`thesis-r1b/`](../experiments/thesis-r1b/), [prereg](preregistration/R1b-improved-router-planner.md) |
| M2 | Does the R1b result depend on the model? | No for the comparison with frozen ARIES: T beats F for llama3.1:8b, qwen2.5:1.5b and qwen2.5:14b on both datasets (Holm, 6/6). Against zero-shot it is mixed (CLINC150 llama 327 vs 329), and qwen2.5:1.5b wins on NL2Bash only by refusing every request | confirmatory (own family) | [`thesis-m2-models/`](../experiments/thesis-m2-models/), [prereg](preregistration/M2-local-models.md) |
| X1 | Do the remedies fix H5 and H4b on their own items? | H4b: code selects, 32/40 pairs; H5: more correct done (12/45) but more false done (15/75) | exploratory | [`thesis-improvements-20261022/`](../experiments/thesis-improvements-20261022/), [prereg](preregistration/X1-remedy-reruns.md) |
| HAL1 | What does the model invent, and what reaches the user? | The model never cited a non-existent evidence id; false successes come from completion contracts that accept real evidence for the wrong goal | descriptive | [prereg](preregistration/HAL1-hallucination-measures.md) |
| — | Router arms A0–A3 on 225 out-of-distribution utterances (the original thesis experiment) | predeclared criterion not met | confirmatory | [`thesis-final-20261006/`](../experiments/thesis-final-20261006/) |
| — | End to end on 49 held-out goals | 29/49 pass the independent check; 0 reached `done` (diagnosed) | descriptive | [`product/independent-acceptance/`](../experiments/product/independent-acceptance/), [diagnosis](analysis/terminal-state-diagnosis.md) |
| H4 | Does the planner ask on new ambiguous goals? | not run: the external item sets were not received | registered | [prereg](preregistration/H4-planner-clarification.md) |

The four hypotheses H4b, H5, H6 and H8 form one Holm family
([`holm_family.csv`](../experiments/thesis-followup-20261012/thesis-tables/holm_family.csv)). One row per agent
component is in [`components.csv`](../experiments/thesis-followup-20261012/thesis-tables/components.csv).

### IIS: the information layer

| Question | Result | Label | Evidence |
|---|---|---|---|
| Does the ARIES interest profile rank news better than standard baselines on MIND-small (73,152 impressions)? | Yes: AUC 0.613 vs 0.600 for the strongest baseline (embedding), 0.578 for popularity; the online learning adds +0.0001 | exploratory (not preregistered) | [`iis/real-data/mind/`](../experiments/iis/real-data/mind/) |
| Does ARIES semantic memory retrieve the annotated evidence on LoCoMo (1,982 questions)? | Worse than BM25: hit@5 0.377 (e5) and 0.349 (bge-m3) vs 0.500; the write cascade changes nothing | exploratory | [`iis/real-data/locomo/`](../experiments/iis/real-data/locomo/) |
| Extract-then-store vs store-everything (author corpus) | supported on clean@3, not on hit@3 | preregistered | [`memory/analysis.md`](../experiments/memory/analysis.md) |

## The code, by component

| Component | Main file | Tests |
|---|---|---|
| Router (act or abstain, intent) | [`aries/intelligence/router.py`](../aries/intelligence/router.py) | `tests/test_intelligence.py`, `tests/test_abstention_vocabulary.py` |
| Planner (next action, capability choice) | [`aries/workspace/agent_planner.py`](../aries/workspace/agent_planner.py) | `tests/test_planner_*.py` |
| Agent loop (plan, execute, verify, finish) | [`aries/workspace/agent.py`](../aries/workspace/agent.py) | `tests/test_agent*.py` |
| Capability registry | [`aries/workspace/registry.py`](../aries/workspace/registry.py) | `tests/test_workspace.py` |
| Verifiers | [`aries/workspace/hardened_verifiers.py`](../aries/workspace/hardened_verifiers.py), [`scope_verifiers.py`](../aries/workspace/scope_verifiers.py), [`verification/`](../verification/) | `tests/test_verify_*.py` |
| Completion contract | [`aries/workspace/contracts.py`](../aries/workspace/contracts.py), [`typed_contract.py`](../aries/workspace/typed_contract.py) | `tests/test_typed_contract.py` |
| Clarification | [`aries/workspace/clarification.py`](../aries/workspace/clarification.py), [`clarify_resolver.py`](../aries/workspace/clarify_resolver.py) | `tests/test_clarif*.py` |
| Context for the planner | [`aries/workspace/context_engine.py`](../aries/workspace/context_engine.py) | `tests/test_context_engine.py` |
| Semantic memory | [`aries/workspace/memory/`](../aries/workspace/memory/) | `tests/test_memory*.py` |
| Interests and news | [`aries/interests/`](../aries/interests/), [`aries/news/`](../aries/news/) | `tests/test_interests*.py` |
| Learning from feedback | [`aries/learning/`](../aries/learning/) | `tests/test_learning*.py` |
| Feature flags (every behaviour change is behind one) | [`aries/flags.py`](../aries/flags.py), generated list in [`CONFIG_REFERENCE.md`](CONFIG_REFERENCE.md) | each flag's own test, e.g. `tests/test_loop_guard.py` |

## How to check the results

```
make setup     # virtual environment from requirements.lock
make test      # the test suite
make check     # recomputes every thesis table (17) and figure (9) from its sources; fails on any difference
```

`make check` runs `experiments/thesis-followup-20261012/thesis-tables/check.py`. It needs no model, no service and
no network. Each table names its source files with their SHA-256 and commit on its first line.

Measurements that need the local models (Ollama, GPU) are listed with their commands in
[`experiments/thesis/INDEX.md`](../experiments/thesis/INDEX.md) and
[`experiments/iis/INDEX.md`](../experiments/iis/INDEX.md).

## Rules the evidence follows

- **Frozen results are never edited.** A new run writes a new file. Frozen folders stay at their paths, because
  preregistrations and checksums name them.
- **Preregistration first.** Changes are dated amendments, committed before the measurement they affect.
- **Public datasets are not committed.** Only download scripts with SHA-256 are committed, and only aggregate
  results or per-item outcomes without text.
- **Labels from language models are disclosed.** Where gold labels or items were written by a model, the
  result says so, with its agreement statistic.

## Known limitations

- Gold labels for R1 come from two LLM labelers with adjudication (κ 0.65 and 0.83), not from people.
- The held-out goals and the H4b/H5/H6 items were written by a language model in a separate session, not by
  people.
- Most measurements use one local model (qwen2.5:7b); llama3.1:8b is a secondary check.
- Voice input in Macedonian is implemented but not measured live (no working microphone during the evaluation).
