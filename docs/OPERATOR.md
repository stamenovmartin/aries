# ARIES — Operator

**"Open YouTube" is not done when a command exits 0. It is done when a browser is on YouTube.**

```bash
aries do "run a system health check"     # exact match → acts, and checks
aries do "open youtube"                  # the local model → proposes a plan
aries do --yes "open youtube"            # …and carries it out
aries do --dry-run "open the news screen"
```

The same thing is in the Control Centre under **Operator**, and both go through the same gated,
audited service.

---

## The claim this has to earn

Not *"ARIES can open YouTube"*. That is a subprocess call, and every assistant on the internet
can make one. The claim is **"ARIES knows whether it opened YouTube"** — and says so when it does
not.

So every step carries two facts that are never merged:

| | |
|---|---|
| **reported** | the tool came back saying it worked |
| **verified** | ARIES looked at the desktop afterwards and confirmed it |

The difference between them is the **honesty gap**, and it is the measurement this milestone
exists to make. A system that records only the first cannot tell working from appearing to work —
which is exactly what M13 shipped with 1,511 green assertions.

---

## The evidence ladder

Not all verification is equally strong, and a system that pretends otherwise is lying about the
part that matters. Every result says which grade it earned.

| grade | what it means | example |
|---|---|---|
| **proof** | read from a system of record, or from the application itself | an automation run row; the Control Centre stating its own section over D-Bus |
| **strong** | two independent observations agree | a process named `firefox` **and** a mapped window belonging to it |
| **circumstantial** | consistent with the goal, and explainable otherwise | a browser window titled *"… — YouTube"* |
| **none** | the observation needed was not available | no window list outside the ARIES session |

`none` produces **unverifiable**, a third verdict beside met and unmet. It is not a failure and it
is certainly not a success: it is ARIES saying *"I did it and I cannot confirm it"*, which is the
truth. The engine has the same shape — `uncertain` is a first-class outcome there for the same
reason.

**A web goal can never be better than circumstantial.** There is no way to read a browser's active
tab URL from outside the browser without an extension inside it. The title comes from the page, so
it is good evidence, and it is still a title. Saying so is better than inventing a stronger claim.

---

## Seeing the desktop

**Processes** come from `/proc`, which is always there.

**Windows** come from the ARIES shell over D-Bus, because Wayland gives no client a way to
enumerate another's windows — a deliberate security property, not a gap to work around. `wmctrl`
and `xdotool` see nothing here; anything claiming otherwise is reading XWayland and missing most
of the desktop. Mutter knows, so the extension inside Mutter is asked:

```
org.aries.Shell.Windows()  →  [{id, title, wm_class, app_id, pid, focused, workspace, minimised}]
```

**Read only, and that is load-bearing.** The method observes and returns; it does not focus, raise,
move or close. Mixing the two would mean the call ARIES makes to check its work could also change
it, after which no verification means anything. A test asserts the method body contains no such
call.

The consequence is honest and inconvenient: **in an Ubuntu session there is no window list**, so
ARIES can act and cannot confirm most of it. It says `unconfirmed`, names the reason, and does not
downgrade to a weaker claim.

---

## How a request is understood — three ways, in order of honesty

**1. The deterministic router.** `aries/shell/intents.py` already resolves *"run a health check"*
and *"open news"* exactly, offline, with no model and no variance. If it matches, that is the plan.

Only an **exact** pattern match counts. `resolve()` also returns near matches ranked by keyword,
and those are suggestions for a person to pick from — taking the top one turned *"send an email to
my boss"* into *"open the Connections screen"*, which is precisely the plausible substitution this
whole milestone exists to stop, arriving from the component that was supposed to be the exact one.

**2. The local model**, for anything the router does not know — asked to choose from a **fixed
vocabulary of goals**, never to write a command.

**3. Refusal.** ARIES says what it cannot do and names what it can. It never substitutes something
plausible.

### Why the model picks goals rather than commands

A model that emits shell produces something that cannot be checked before it runs, cannot be
checked after it runs, and cannot be refused by a permission system that does not know what the
command will do.

A model that emits `{"goal": "open_url", "url": "…"}` produces something with a schema, a
permission, an audit line, and a verifier that decides whether it worked independently of anything
the model claims. **That constraint is the design.** It costs the Operator the ability to do
arbitrary things and buys the ability to be honest about what it does.

### A guess is proposed; an exact match is performed

The interesting failure is not a model refusing. It is a model answering plausibly — *"reformat my
hard drive"* was answered, by a competent 7B model, with *"open the System screen"*. Nothing about
that is dangerous on its own. What is dangerous is a system that would carry it out and report
success.

So `operator.confirm_model_plans` is on by default: a model-derived plan is shown and waits.

---

## Where it thinks

`intelligence.location` defaults to **local** — a model on this machine, which has a GPU. When it
is local, ARIES does **not** fall back to a remote provider if the local one is unreachable: it
says the local model is unreachable. A privacy default that degrades under failure is not a
default.

`qwen2.5:7b` on an RTX 3060 plans in ~0.3–3 s at about 70 tokens/second.

---

## The gates

The Operator's hands are four engine `ToolSpec`s and it has no other way to touch the machine, so
everything it does is already audited, refusable and replay-safe before any of its own logic runs:

| tool | what it does |
|---|---|
| `desktop.open_url` | open an `http(s)` address in the default browser |
| `desktop.open_app` | launch an installed application |
| `aries.open_section` | open the Control Centre on a section |
| `aries.run_automation` | run one ARIES automation now |

Every call passes permission → schema → dry-run → live-tool allowlist → policy → approval →
at-most-once → journal. ARIES drives the engine's switches from **its own settings**, at the point
of use rather than at startup: a gate armed at boot is wrong the moment the user changes their
mind, and the failure of a stale arming is that ARIES acts after being switched off.

**A refusal is not a failure.** A step stopped by the action budget, an approval, the policy or an
automation's own circuit breaker did not fail to plan and did not fail to act. The outcome is
`held`, with the gate named. Folding those into `failed` made a rate limiter look like a planner
collapsing.

### What is deliberately absent

Closing windows, killing processes, deleting anything, typing into another application. v0.1 opens
things — every tool here is something a person can undo by closing a window, which is the property
that makes *"let it try and check afterwards"* a reasonable design at all. An Operator that can
destroy has to argue past a much higher bar, and it has not earned that yet.

---

## Settling

An application takes time to map a window. Verifying the instant after `gtk-launch` returns would
report `unmet` for something that succeeds 800 ms later — wrong in the *flattering* direction for a
naive baseline and the *unflattering* direction for this one.

So verification polls until the goal is met or `operator.settle_seconds` (8 s) elapses, and the
elapsed time is recorded. The window is a declared constant, identical for every variant in the
experiment, and "how long it took to become true" is a result rather than a detail hidden inside a
sleep.

---

## The working set

Everything the Operator pulls in to answer one request goes to `aries_working_set` under the
task's id, and is released when the task ends — success, failure or refusal. Today that is the
observations it took; when the Operator starts reading mail it will be mail. The seam is here now
so that it is not retrofitted later, which is when it would be forgotten. See [DATA.md](DATA.md).

---

## Surfaces

| surface | where |
|---|---|
| capability | `aries/operator/` — `desktop`, `goals`, `tools`, `plan`, `service` |
| orchestrator | the engine's `call_tool` gates every action; the working set is released on every terminal outcome |
| CLI | `aries do "…"` · `--yes` · `--dry-run` · `--json` |
| API | `POST /api/aries/operator` · `GET /api/aries/operator` · `GET /api/aries/operator/history` |
| UI | Control Centre → **Operator** |
| shell | `org.aries.Shell.Windows()` — read-only observation |
| settings | `operator.*` (off by default) and `intelligence.*` (local by default) |
| audit | `operator.ran`, carrying `reported_success`, `verified_success` and `honesty_gap` |
| evaluation | [`experiments/operator/`](../experiments/operator/) and [EXPERIMENTS.md](EXPERIMENTS.md) |

---

## Known limits, stated rather than discovered

* **Window-grade verification needs the ARIES session with a shell new enough to have
  `Windows()`** — which means a logout and login after installing this build. Until then every
  `open_url` and `open_app` result is `unconfirmed`, correctly.
* **A browser tab's URL is not readable.** Circumstantial is the ceiling, and a page whose title
  does not mention the site will verify as unmet even when it is right.
* **Applications and tabs cannot be un-opened**, so experiment trials for those classes are marked
  `contaminable`: a variant that does nothing can inherit the previous trial's success. Section and
  automation trials are reset properly.
* **One request, one plan.** There is no replanning after a failed verification. Re-opening a
  browser that is already open does not help, and the cases where replanning *would* help — the
  application is not installed, so try another — are not built.
