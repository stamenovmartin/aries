# ARIES — Control Centre

The first graphical interface to ARIES: a GTK4 application through which the system can be
understood, configured and controlled without a terminal.

```bash
cd ~/aries && ./scripts/start.sh        # ARIES itself
cd ~/aries && ./scripts/aries-ui        # the Control Centre
```

## The architecture, and why it is two processes

```
aries_ui  (system Python 3.14 · GTK4 · libadwaita · stdlib only)
    │  HTTP, loopback
    ▼
ARIES API (venv Python 3.12 · FastAPI)  →  permissions → audit → services → database
```

GTK's Python bindings belong to the system interpreter; ARIES runs in a `uv`-managed 3.12
virtual environment. Rather than fight that, the split **is** the architecture — and it is the
one the requirement asks for:

> UI → typed service boundary → ARIES core. Never UI → database.

The Control Centre does not import `aries`, and **cannot**: the package is not on its
interpreter's path. A UI action is therefore structurally incapable of bypassing permissions or
the audit log, because the only thing it can reach is the API. See `decisions/ADR-0004`.

## Screens

| screen | shows | writes through |
|---|---|---|
| **Home** | status, decisions waiting, brief, health, notifications, next automation, recent learning | `/home` |
| **Brief** | the morning brief, section by section | `/brief` |
| **News** | sources + catalogue + health · articles with feedback · tuning | `/sources`, `/news`, `/settings` |
| **Interests** | **explicit and learned side by side**, evidence, pending reversals | `/interests` |
| **Learning** | tell ARIES something · its questions · contested beliefs · evidence · history | `/learning/*` |
| **Automations** | §27's Control Centre; advanced (genome, metrics, history) behind a disclosure | `/automations` |
| **System** | health findings; healthy readings collapsed | `/health/latest` |
| **Connections** | what needs you from what ARIES read · connected sources and where their secrets live · connected / available / **not built yet** | `/connections`, `/connect`, `/attention` |
| **Operator** | ask for something in words; what the tool reported, what ARIES checked, and what it found | `/operator`, `/operator/history` |
| **Data** | what ARIES is reading right now, what it keeps and for how long, and what it is about to forget | `/data`, `/data/working-set` |
| **Settings** | every setting, generated from the schema, plus the live Power & Background and Resource policy panels | `/settings`, `/power` |

**Operator** is not a chat window. The interesting thing about it is not that it answers, but that
it distinguishes *what it did* from *what it could check* — so every result shows the tool's report,
the check, and the finding as three separate lines, and the headline says whether ARIES can verify
anything at all right now. See [OPERATOR.md](OPERATOR.md).

**Data** leads with the working set rather than with retention, deliberately. The windows are the
boring half; the interesting half is *"what is ARIES reading right now, and where did it come
from?"* — the question a person actually has once ARIES can open their mail. Labels and sources
are shown, never contents. See [DATA.md](DATA.md).

## Responsiveness

Every request runs on a worker thread and its result is marshalled back with `GLib.idle_add`,
which is the one supported way to touch GTK from another thread. The window never blocks on a
fetch, a probe, a database query or an automation run.

**Stale replies are dropped.** Home → News → Home starts three requests that may land in any
order; a late reply from the first would repaint the screen with older data. Every request
carries a generation number, and a reply whose generation has been superseded never reaches a
widget.

**Writes are never optimistic.** The UI shows what ARIES says happened, not what it hoped — a
value refused by validation or by the permission model must not appear to have been applied.

## Three states, not two

`Loading` · `Empty` · **`Absent`**. "No failed services" and "the health automation has never
run" are different facts, and rendering both as blankness is lying by omission — the same rule
that makes ARIES report `null` with a reason rather than `0`.

## The command interface

`Ctrl+Space` opens a command bar over the capabilities ARIES actually has. It is **not a chat**:
it matches what it recognises, runs it through the real API, and says plainly when it cannot.

```
show pending decisions · run system health · scan for news
why do you think AI matters to me?  ·  make my morning brief shorter
only notify me if it is important  ·  disable security news
```

Unrecognised input produces *"ARIES cannot do that yet"* and three things it can do — never a
plausible-sounding nothing. Intent order is significant: **actions are matched before
navigation**, or "scan for news" silently becomes "show news".

`Super+Space` belongs to the desktop shell rather than to an application. To bind it:
*Settings → Keyboard → Custom Shortcuts*, command `~/aries/scripts/aries-ui`.

## The contract between the two processes

Nothing but `aries_ui/contract.py` connects what the UI expects to what ARIES provides — so it
is declared as data, and `tests/test_ui_contract.py` asserts that every endpoint exists and
returns the keys the UI reads.

This exists because the gap bit: when reversal detection sliced the evidence endpoint by time
and source, the Learning screen kept reading the old flat keys and rendered an error page.
Nothing failed until a human looked.

## What is real, and what is not

**Real** — every value on every screen comes from ARIES:  the suspend inhibitor as *logind*
reports it, sources and their health, articles with
the reason each was shown or held, explicit and learned weights, reversals with their evidence,
automation runs, health findings, settings with provenance.

**Not implemented, and labelled so** — email, calendar, GitHub, Docker and SSH appear on
Connections as *not built yet*, with the reason. Status is **derived** from whether a connector
exists, so a screen cannot claim a capability the system lacks.

**Deliberately absent** — Edit, Duplicate and Rollback for automations. They operate on a
versioned genome, which is §18's controlled evolution; a button that mutated a spec in place
would look like that feature while providing none of its safety.

## Accessibility

Inherited from GTK rather than reimplemented: full keyboard navigation, AT-SPI exposure, the
user's own theme, contrast and text scale. Colour is never the only signal — severity carries an
icon, and provenance differs in **form** (solid vs dotted) as well as hue, so the distinction
survives greyscale and colour-blindness. The layout adapts to a narrow window through
`NavigationSplitView`.

## Known limits

* The UI needs ARIES running; it says so and gives the command rather than showing an empty window.
* No light-theme polish pass yet — the tokens are theme-relative and follow the system, but only
  dark has been reviewed in detail.
* The command bar has 16 intents. Adding one is a row in `command.py`, and it is only addable if
  the capability already exists.
* Article feedback is not batched: one click, one request.
