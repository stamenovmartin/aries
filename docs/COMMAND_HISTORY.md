# ARIES — Command Interface

`Ctrl+Space` in the Control Centre. A command bar over the capabilities ARIES actually has —
**not a chat**.

## The rule

It matches what it recognises, runs it through the real API, and says plainly when it cannot.
A bar that answers everything with something plausible is worse than one that answers half of
things honestly: the first cannot be trusted and the second can.

Unrecognised input:

> **Not supported.** ARIES cannot do "order me a pizza" yet. This is a command bar over the
> capabilities that exist, not a chat — so it says so rather than guessing.
> Try: "show pending decisions", "run system health", "scan for news".

## Supported intents (v0.1)

Order is significant — **actions are matched before navigation**, because patterns overlap and
a verb is more specific than a noun.

### Actions

| say | does | reaches |
|---|---|---|
| run system health · check this machine | runs the health automation | `POST /automations/aries.health/run` |
| scan for news · fetch news | runs the News Radar | `POST /automations/aries.news/run` |
| run a learning pass | re-reads the evidence | `POST /automations/aries.learning/run` |
| why do you think **AI** matters to me? | opens the explanation for that subject | `GET /learning/explain/{subject}` |
| make my morning brief shorter | submits feedback — ARIES asks how far it reaches | `POST /learning/feedback` |
| only notify me if it is important | submits feedback | `POST /learning/feedback` |
| disable **security** news | adds the topic to what ARIES ignores | `POST /interests` |

### Navigation

`show pending decisions` · `show my brief` · `show today's important news` · `show my interests`
· `show automations` · `open settings` · `where does my news come from` · `show connections` ·
`show system health`

## Why these and not more

An intent is addable only if the capability already exists. That keeps the command bar from
outrunning the system — it cannot offer something ARIES cannot do, because there would be
nothing to call.

## Bugs this has already had

**"scan for news" showed the News screen instead of scanning.** Navigation intents were declared
before actions, and `scan for news` contains "news". Same for "make my morning brief shorter",
which matched *show brief*. Both did the more generic, less useful thing, silently. Fixed by
ordering actions first; pinned by `tests/test_ui_client.py::test_intents_route_to_real_capabilities`.

## Super+Space

Belongs to the desktop shell, not to an application, so ARIES does not take it. To bind it:
*Settings → Keyboard → View and Customise Shortcuts → Custom Shortcuts*, command
`~/aries/scripts/aries-ui`.

The eventual ARIES shell (§5) owns this properly; until then, taking a global shortcut an
application has no business holding would be the wrong kind of ambition.

## Not implemented

Free-form natural language, multi-step requests ("find AI news and email it to me"), and
anything requiring a model. v0.1 is a deterministic router; a model-backed intent layer belongs
with the Orchestrator (§6), where it can be evaluated rather than guessed at.


## Where a command actually goes (Entry 017)

A resolved intent is not a completed action. For the whole of M13 the router
returned `navigate → news` correctly, and nothing opened, because the launcher it
handed off to exec'd itself.

So the chain is now checked end to end rather than at its first link:

```
"show news"
  → POST /api/aries/command            the router resolves it
  → {"kind": "navigate", "section": "news"}
  → scripts/aries-ui --section news    the launcher runs the Control Centre
  → app.activate_action("section", …)  a stateful GAction, not a startup race
  → the window navigates
  → org.gtk.Actions.Describe           read back: where did it ACTUALLY land?
```

The last line is the point. `./scripts/aries-e2e` asks the window where it is
rather than trusting the caller, for every one of the nine sections, in both the
cold-start and already-running cases.

**A command bar that resolves an intent it cannot carry out is worse than one
that refuses**, because refusal is visible and a no-op is not.
