# M14 implementation and evaluation addendum

**Measured live run:** `20260917T204354Z-fb8722` · 17 September 2026  
**Result:** 4/4 required scenarios passed; three tasks `done`, negative-control task `failed`.

## Implementation

M14 користи централен registry со 15 capabilities, strict decisions (`execute`, `finish`, `fail`, `ask_approval`) и existing `WorkspaceGoal` queue. Backward-compatible `schema_version=2` JSON зачувува step transitions, model decisions, executor observations, verification, errors и evidence references. Default action budget е осум, configurable до 32.

Capabilities: `file.read`, `file.write`, `file.list`, `file.search`, `file.exists`; `browser.open`, `browser.read`, `browser.search`; `desktop.launch`, `desktop.focus`; `system.status`, `system.storage`, `system.processes`; `task.inspect`; `notification.send`.

Registry-derived finite grammar ја ограничува local model генерацијата, а runtime повторно го валидира JSON. `finish` не е понуден пред supported goal conditions да имаат provisional evidence; за supported goals без извршен чекор `fail` не е понуден пред првиот реален обид. Ова го спречува model-от да го замени missing-file probe со претпоставка. Runtime сепак независно го проверува секој terminal claim.

Safety review доведе до exact desktop launch без втор text planner, binding на write path/content кон познатиот user goal, почитување на `operator.confirm_model_plans`, conditional approval update и descriptor-relative no-follow file access. Овие се implementation safeguards, не доказ за целосна отпорност на сите напади.

## Measured scenarios

| Scenario | Task status | Steps | Planner calls | Native input tokens | Native output tokens | Native total tokens | Harness elapsed s |
|---|---|---:|---:|---:|---:|---:|---:|
| File workflow | done | 2 | 3 | 11,220 | 236 | 11,456 | 10.734 |
| System inspection | done | 1 | 2 | 5,857 | 70 | 5,927 | 4.166 |
| Negative control | failed — expected | 1 | 2 | 5,618 | 87 | 5,705 | 4.154 |
| Browser | done | 2 | 3 | 12,799 | 152 | 12,951 | 10.853 |
| Total | 4/4 test verdicts pass | 6 | 10 | 35,494 | 545 | 36,039 | 29.907 |

Token counts се runtime-native `prompt_eval_count` / `eval_count` за `qwen2.5:7b`, не character estimates. Во сите четири tasks `token_measurement_complete=true`. Estimated fields остануваат одделно во raw JSON и не се користат во табелата. Total elapsed е сума на четирите harness case durations, не end-to-end run wall time со readiness polling.

Final run има 0 planner retries, 0 invalid decisions, 0 verification failures и 1 capability failure — намерниот missing-file обид. Овие нули важат само за овој завршен acceptance run; претходните обиди содржат грешки.

File action создаде exact bytes `ARIES M14 verified execution` и потоа ги прочита. Двата step evidence records се rechecked пред final completion. System probe измери `/` со 5.4% и `/boot/efi` со 0.6%; резултатот `/` е пресметан од набљудуваните вредности, не hard-coded. Browser независно го набљудува `https://www.python.org/` со title `Welcome to Python.org`. Browser transport ја прикажува прочитаната DOM содржина во controlled session; ова не е unrestricted interactive browser capability. Negative control изврши `file.read` и зачува реален `FileNotFoundError`, со `retryable=false` и без final verified evidence refs.

## Approval and timing protocol

Demo ја зачувува вистинската approval setting. Само неговиот exact new-file proposal и public Python.org navigation се одобруваат од harness-от. Ова е authorized test protocol, не целосно unattended policy bypass. Approval proposals и arguments се зачувани во result.json.

Во овој artifact, task `metrics.wall_seconds` кај approval-resumed tasks ја потценува целата траекторија: file има 4.125 s, а browser 6.930 s. Затоа табелата користи externally measured harness `seconds`, кој го вклучува целото scenario polling/execution interval. Planner и execution timing остануваат достапни одделно. Подоцнежна metric поправка не ги препишува овие историски вредности.

## Development iteration, not held-out research

Сите претходни attempts се зачувани:

| Run | Passed | Context |
|---|---:|---|
| `20260917T203400Z-51901a` | 0/4 | Local grammar compiler incompatibility |
| `20260917T203531Z-505cc8` | 0/4 | Service readiness failure |
| `20260917T203544Z-497bea` | 2/4 | Development iteration |
| `20260917T203732Z-b2ba9e` | 3/4 | Development iteration |
| `20260917T204217Z-2a255c` | 3/4 | Development iteration |
| `20260917T204354Z-fb8722` | 4/4 | Final recorded live acceptance |

Grammar, prompt и protocol се прилагодувани според истите сценарија. Последниот green run е engineering acceptance, не independent test set, unbiased success-rate estimate или доказ за scientific superiority. Не се собираат повторувањата во поголем „независен“ sample.

Historical Operator 372 trials, controls 52/52, old full demo 11/11 и core demo 7/7 остануваат одделни experiments.

## Subsequent replication

Run [`20260917T204843Z-1ae7a7`](../../experiments/agent/20260917T204843Z-1ae7a7/result.json) повторно помина **4/4** по поправки на active wall-time accumulation и planner call-budget edge handling. Task states повторно се `done`, `done`, `failed` (expected negative control), `done`. Harness durations се 14.785 s, 4.673 s, 4.130 s и 11.350 s за file, system, negative и browser.

Новото `metrics.wall_seconds` ја вклучува активната обработка пред и по approval resume, но го исклучува approval/queue waiting interval; harness `seconds` останува end-to-end scenario metric. Првата acceptance табела погоре и нејзините historical timing limitations се задржани непроменети. Replication е врз истите development fixtures и не претставува независен held-out benchmark. Source digest: `0459dac21da3e7ffc57fa9ea850e74f20ab2b91bfe63b11f88f79127c108cb3a`.

## Scope and remaining limitations

Completion oracle користи конзервативни услови извлечени од **корисничкиот goal text**. General capability selection не значи general semantic goal verification. Unsupported goal може да има verified useful steps и сепак да заврши `partial`.

Full regression validation е одделна од овој live run; конечните regression counts не се измислуваат или изведуваат од 4/4. GNOME active shell и repository shell може да имаат различни build identities; свежа login session е потребна за session-loaded modules кога smoke пријавува mismatch. Backend success не е доказ за loaded desktop integration.

## Reproduction and artifacts

```bash
cd ~/aries
./scripts/aries-agent-demo
```

[Run result](../../experiments/agent/20260917T204354Z-fb8722/result.json) · [Report](../../experiments/agent/20260917T204354Z-fb8722/report.md) · [Task snapshots](../../experiments/agent/20260917T204354Z-fb8722/tasks/) · [Evidence snapshots](../../experiments/agent/20260917T204354Z-fb8722/evidence/)

Run source SHA-256: `0ec0e1ca9df86982738a53d4835163b466a1509783ec6400ad6b4af93aae14ae`. Git marker `c1adb8041e2a1bd3acd1efd5f300a09a2b968967`, dirty tree. Artifact digests are included in the publication manifest.
