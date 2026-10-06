# Two agents, one repository

On 2026-09-29 and 30 this repository was built by several agents at once: a the reviewing agent
session with seven subagents, and a Codex session. They had no message channel, so
they made one — `COORDINATION.md` at the repository root, append-only, one heading
per message. This is what that produced, and what it cost.

`COORDINATION.md` is the live channel and the transcript. This file is the lesson.

## What the channel was for

Not politeness. Two agents writing the same file is a lost hour, and two agents
solving the same problem is a wasted one. The protocol is three lines:

* **One new file per agent.** Shared files are edited by one coordinator, serially.
* **Claim a shared file by name before editing it**, and say when you release it.
* **Append, never edit someone else's message.** Reply with a new one.

Seven subagents each built a capability module in its own new file and returned the
`registry.py` and `capabilities.py` snippets as text; the coordinator applied them
one at a time and ran the affected suites after each. **Zero conflicts.** Both
collisions that did happen were in shared files edited concurrently, which is the
argument for the rule rather than against it.

## What cross-agent review caught that neither side would have

This is the part worth keeping. Both findings are in the other agent's code, and
neither author was looking in the right place.

### Codex found an honesty bug inside the module written to fix dishonesty

`aries/speech/replies.py` exists because ARIES said **"Task queued"** out loud
while its result already held `disk.used_pct 8.5%, free_gib 396.28`. The module
mines the measurement and refuses to speak process language.

Codex, reading it to wire it into the voice daemon, found that it mined readings
**before** checking the goal's state. An earlier step's measurements survive in the
record, so a `failed` goal would say *"Дискот е на 8.5%"* and never mention
failing. Confidently speaking stale evidence is the exact thing the project
refuses to do — sitting in the module written to remove it.

The author had tested the happy paths and the process-word blocklist. The reader
tested the state machine. `tests/test_replies.py` now carries that case verbatim.

### the reviewing agent found why the voice loop had never once worked

Every component passed its tests. The journal showed **not one addressed utterance
all day** — every line `not addressed` or `dropped`, full of `'Thank you for
watching.'` and `'Captions by GetTranscribed.com'`.

Measured, not reasoned: synthesized Macedonian through the real
`pick_language → transcribe → wake_match` chain was addressed 4 times out of 4, so
the chain worked. What did not work was that **`pick_language()` returned
`max(ranked)` with no floor.** Clean synthesized Macedonian scores p=0.11–0.24, and
the user's real speech scored `[en 0.45]`, `[en 0.01]`, `[en 0.00]`. A short
utterance carries no language evidence, so the pick was near-random, and once it
picked `en` the English prompt dragged the decode into English captions that could
never contain "Ари".

That diagnosis went into the channel with the numbers. Codex owned the file, fixed
it — low-confidence language decodes without a forced prompt, caption echoes
filtered, the task id polled so the *answer* is spoken instead of the receipt —
restarted the service, and reported a live goal producing *"Дискот е на 8.5%.
Слободни ти се 396 гигабајти од 433."*

Neither half was reachable from one seat. The diagnosis needed a full end-to-end
measurement; the fix needed ownership of the file.

### And a claim corrected in the other direction

the reviewing agent told Codex to make the settings UI schema-driven. Codex replied that
`aries_ui/pages/settings.py` **already** derives every group and control from
`/settings`. The instruction had been inferred from the schema's docstring rather
than read from the UI. Recorded here because an agent confidently briefing another
agent on a file it has not opened is a failure mode the channel exposes and a
single agent never notices.

## The shape that keeps recurring

**Engineering green is not product green.** Every finding above is one instance:

| component | its own tests | the installed system |
|---|---|---|
| voice loop | all passing | never addressed once, all day |
| `replies.py` | happy paths passing | spoke stale readings for failed goals |
| orchestration reroute | 99 checks passing | `_register()` never imported in production, so the path is dead code |
| `docs/CAPABILITIES.md` | — | described 20 of 58 capabilities |

Codex found the third one. It is the same sentence every time: the piece works and
nothing connects it to the person. `docs/ERROR_LOG.md` entries 018–027 record the
mechanical half of this — **exit zero is not evidence** — and this is the
organisational half.

## What it cost

Seven the reviewing agent subagents: **405 tool calls, ~1.04M tokens, 129.7 minutes of agent
time compressed into about 31 minutes of wall clock** by running four in parallel.
Plus the Codex session's own work. The animated timeline in the published inventory
artifact shows the parallelism.

The overhead of the channel was four messages and one file. Against one avoided
collision, that pays for itself.

## If you are the next agent here

1. Read `COORDINATION.md` before you edit anything, and add your row.
2. Read the measured-facts section in it. No compiler, no root, no `pactl`, no pip
   in the venv, `AccessDenied` on GNOME's own screenshot API, Cyrillic silently
   dropped by Mutter keysyms. Every one of those cost someone an hour already.
3. When you finish a component, **check it from the user's seat, not the test's.**
   Ask what the person sees or hears, and whether anything carries the result to
   them. That question found every bug in this document.
