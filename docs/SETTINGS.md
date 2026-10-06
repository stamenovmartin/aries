# ARIES — Settings

Every setting, in one place, with where its value came from. No YAML.

```bash
./scripts/aries-ui            # Settings section
./scripts/aries settings      # the same values, in a terminal
```

## The screen is generated, not written

The Settings Service declares everything a control needs — type, title, description, control
kind, choices, bounds, unit, whether it is advanced, whether a machine may write it. So the
screen is **built from `GET /api/aries/settings`**: adding a setting to ARIES makes it appear,
correctly rendered, with no UI change at all.

| declaration | control |
|---|---|
| `bool` / `toggle` | switch row |
| `select` + `choices` | combo row |
| `slider` / `number` | spin row, honouring `minimum`, `maximum`, `unit` |
| `list` | entry row, comma separated, applied on commit |
| anything else | entry row |

## Two things a settings screen usually hides

ARIES's design depends on both being visible.

**Where the value came from.** Each changed setting is tagged *you set this* or *ARIES inferred
this* — never blurred. Untouched defaults carry no tag.

**What is overriding what.** A value you set which is currently outranked by a security policy
must not silently appear to be in force. The layer stack is shown in
`aries learning explain <key>` and in the Learning screen.

## Sections

General · Autonomy · **Power & Background** · Privacy · Notifications · Briefing · News ·
Interests · Learning · Automations · System health · Sources · AI

**Power & Background** is the one section with status panels above its controls, because its
settings are claims about the machine rather than about ARIES. Two panels, for the two promises:
the inhibitor, display, session and suspend policy are read from logind and GNOME at the moment
the screen is drawn, so the panel cannot report an inhibitor that is no longer held; and the
resource policy shows CPU, GPU and temperature against their limits, with what each workload
class would actually be allowed to do right now — computed by the same order of questions the
gate uses, because a panel that predicted something different would be believed. See
[POWER.md](POWER.md).

One setting there is written by ARIES and hidden from the form: `power.restore_idle_delay`, the
display timeout found before Background Mode changed it. It appears in the panel as *"will restore
to N s"* rather than as an editable field — editing it would destroy the value the machine has to
be returned to.

**Data** is generated rather than written. One window setting per operational retention policy is
defined from `aries/lifecycle/policy.py`, carrying that policy's own reason as its description and
its dependants' minimum as the schema's `minimum` — so a window too short to keep the circuit
breaker or the learning loop correct is refused at the door, with the reason, rather than clamped
silently. A policy with a setting name that has no setting would be a policy nobody can change;
generating both from one declaration is what stops the two disagreeing. See [DATA.md](DATA.md).

Advanced settings sit behind a disclosure per section. 70+ settings exist; most people will
touch a dozen.

## Precedence (§30)

```
SECURITY 80 → RESTRICTION 70 → USER 60 → INSTRUCTION 50 → PROJECT 40
           → LEARNED 30 → HISTORICAL 20 → DEFAULT 10
```

A write from the UI lands at **USER**, exactly as a write from the CLI does. Nothing the UI can
send reaches the learned layer — that is reserved for the learning loop, which in turn can never
reach a user layer. Settings marked `user_only` refuse machine writes entirely:
`autonomy.level`, `ai.daily_cost_limit`, `ai.send_file_contents`, `privacy.*`,
`sources.allow_private_addresses`, `automations.worker_enabled`, `learning.apply_changes`.

## Every change is audited

```
UI → PUT /api/aries/settings/{key} → permission check → Settings Service
   → validation → write → AuditEvent(actor, from, to, layer) → confirmation
```

The actor is derived from the authenticated principal, server-side — never from the request
body. There is no privileged GUI path; the Control Centre uses the same endpoint as `curl`.

Pinned by `tests/test_ui_contract.py::test_settings_written_through_the_ui_boundary_are_audited`.

## Refusals

A value outside its declared range is refused with ARIES's own words, and the UI shows that
message rather than a generic failure. Writes are never optimistic: the screen reflects what
ARIES says happened.
