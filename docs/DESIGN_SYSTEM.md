# ARIES — Design System

> **Two toolkits, one language.** Since the Shell milestone the tokens live in
> `aries/shell/tokens.py` and **both** stylesheets are generated from them: the
> Control Centre's GTK CSS (theme-relative — `@accent_color`, so it follows the
> user's own accent and light/dark) and the shell's St CSS (fully resolved
> literals, because GNOME Shell's CSS has no variables, no `alpha()` and no
> `calc()`). A test asserts the generated file matches the tokens, so a colour
> changed in one place cannot drift in the other. See [SHELL.md](SHELL.md).
>
> What the language is made of: one type family and five sizes · every gap a
> multiple of 4 · three radii chosen so a control inside a surface inside a panel
> nests correctly · four elevations expressed as background and border rather
> than piled shadows · three motion durations, none longer than 240 ms · one
> 2 px focus ring that is never suppressed.


Small on purpose. libadwaita already embodies most of what the brief asks for — calm, native,
progressive — so this is a layer on top of it, not a replacement. Reimplementing Adwaita's
typography, rows and dialogs would look foreign on the user's desktop and lose accessibility
that comes free.

## What is inherited

Typography scale (`.title-1`, `.title-2`, `.heading`, `.caption`), `boxed-list` rows,
`PreferencesGroup`, `StatusPage`, `Toast`, `NavigationSplitView`, `ExpanderRow`, dialogs, and
light/dark switching driven by the user's own theme and accent colour.

## What ARIES adds

Four things Adwaita has no opinion about and ARIES needs everywhere.

### 1. Severity — one vocabulary, system-wide

| level | meaning | colour |
|---|---|---|
| `ok` | verified good | success |
| `info` | **neutral** — not an assertion of health | 40% foreground |
| `notice` | worth knowing | accent |
| `warning` | real, not urgent | warning |
| `critical` | act now | error |

Used identically by health findings, source health, notification levels, automation status and
reversal states. `info` and `ok` were briefly the same colour, which made *"Not built yet"*
render with a green tick — the interface asserting that an unimplemented integration was fine.
Verified-good and simply-neutral must not share a colour, or the colour stops meaning anything.

Every level also carries an **icon**, so severity is never colour alone.

### 2. Provenance — the distinction that must never blur

```
Explicit  ▌ solid left border, accent      "you set this"
Learned   ⁞ dotted left border, warning    "ARIES inferred this"
Default     no border                      "default"
```

The requirement is most insistent about this, and it is right to be: a user must never mistake
what they configured for what a machine concluded. The difference is in **form** as well as
colour, so it survives a glance, greyscale, and colour-blindness.

On Interests the two numbers sit side by side and are never merged:

```
ai        Explicit 0.90   Learned 0.94
agents    Explicit 0.85   Learned 0.89
security  Explicit 0.75
```

### 3. Density — one scale

`4 · 8 · 12 · 18 · 24 · 36`. Everything is a multiple of four. Radii: `6 · 12 · 18`.

### 4. Quiet — for the thing a calm interface needs most

A section that is present, healthy and has nothing to say gets one muted line, not a card full
of green ticks. Nothing needing attention must not look like nothing happening.

## States

| state | when | looks like |
|---|---|---|
| Loading | work in flight | spinner + what is loading; window stays interactive |
| Empty | nothing here, and that is fine | status page, often with the action that would fill it |
| **Absent** | nothing here *because* something is missing | status page naming the reason |
| Error | ARIES refused or is unreachable | plain words, ARIES's own message, the command that fixes it |

`Empty` and `Absent` are different on purpose. "No failed services" and "the health automation
has never run" are not the same fact.

## Motion

Only where it communicates state: a spinner while work is in flight, a toast confirming a write,
Adwaita's own navigation transitions. No decorative animation, no parallax, no reveal effects.

## Deliberately avoided

Gradients · glassmorphism and blur · drop shadows beyond Adwaita's own · borders where whitespace
separates adequately · giant cards · dashboard widgets · sparklines and gauges · animated
counters · custom fonts · a bespoke colour palette that ignores the user's accent.

## Progressive disclosure

Every screen leads with what a non-technical user needs and puts the technical truth one level
down:

* Automations: name, state, last result → **Advanced** (version, permissions, genome, history) →
  raw JSON.
* Settings: plain controls → **Advanced** per section.
* System: findings that matter → healthy readings collapsed → per-probe detail.
* Interests: two numbers → expand for evidence, intervals, history, reversals.

## Adding a component

Put it in `aries_ui/widgets.py` only if two screens need it. Use Adwaita's own widget wherever
one exists. A new colour must map to the severity vocabulary or it does not go in.
