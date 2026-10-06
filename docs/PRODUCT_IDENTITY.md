# ARIES — Product Identity

**ARIES is the product. Linux is the foundation.**

This is a standing constraint, adopted at the Shell milestone, and it outranks convenience.
It is not branding; it changes what gets built and in what order.

```
┌─────────────────────────────────────┐
│             ARIES Shell             │
│ Desktop · Dock · Search · Settings  │
│ Notifications · Control Centre      │
├─────────────────────────────────────┤
│          ARIES Intelligence         │
│ Orchestrator · Agents · Context     │
│ Memory · Learning · Evolution       │
├─────────────────────────────────────┤
│          ARIES Automation           │
│ Workflows · Scheduler · Proactive   │
│ Background Intelligence             │
├─────────────────────────────────────┤
│          ARIES Capabilities         │
│ Files · Web · Mail · Calendar       │
│ Git · Docker · SSH · Apps           │
├─────────────────────────────────────┤
│             ARIES Core              │
│ Security · Audit · Settings · IPC   │
│ Power · Services · Permissions      │
├─────────────────────────────────────┤
│        Linux / Ubuntu base          │
│ Kernel · Drivers · systemd · Wayland│
└─────────────────────────────────────┘
```

## The rule

Never design a feature as **"Linux feature + ARIES add-on."**
Always design it as **"ARIES capability implemented using Linux."**

The difference is not cosmetic. "Linux feature + add-on" produces a system where the user
must know that Wi-Fi is GNOME's, power is systemd's, briefings are ARIES's, and the
boundaries between them leak into everything they do. "ARIES capability implemented using
Linux" produces one environment whose implementation happens to be excellent, mature,
unmodified Linux.

## Five surfaces

Every major capability is unfinished until all five exist. A capability with only the first
is a library; a capability with only the fourth is a mock.

| # | surface | the question it answers |
|---|---|---|
| 1 | **ARIES Core capability** | can ARIES actually do the thing? |
| 2 | **Orchestrator / agent access** | can a goal reach it without the user naming it? |
| 3 | **Automation access** | can it run unattended, on a schedule or a trigger? |
| 4 | **ARIES UI / Settings surface** | is there an ARIES-native place to see and configure it? |
| 5 | **Audit / security / learning** | is it recorded, permissioned, and able to improve? |

This replaces the previous habit of "build the capability, add a UI later". The Shell is not
a final decorative phase — from this milestone on, a capability ships with its surface.

## Ambient, not a chatbot

The most important design decision in the whole system: **AI must not look like a chat box
glued to an operating system.**

Wrong:

```
ARIES Desktop  +  [ Ask AI ]
```

Right — `Super+Space`, "prepare me for tomorrow":

```
Calendar ──────┐
Mail ──────────┤
Projects ──────┤
News ──────────┼──→ Orchestrator ──→ result / actions
Memory ────────┤
Deadlines ─────┤
Agents ────────┘
```

The user never learns that seven agents ran. Intelligence is a property of the environment,
not an application inside it.

## The named surfaces

What ARIES owns, in the user's language — regardless of which Linux component implements it:

| surface | replaces, from the user's point of view | status |
|---|---|---|
| **ARIES Search** | app launcher + file search + AI prompt, as one thing | Shell v0.1 |
| **ARIES Notifications** | system notifications + agent and automation results, in one place | Shell v0.1 |
| **ARIES Settings** | GNOME Settings, for what ARIES controls | partial — Control Centre |
| **ARIES Power** | power management + background intelligence | done — M12 |
| **ARIES Automations** | cron, timers, scripts | done — M3–M12 |
| **ARIES Memory** | — | next |
| **ARIES Connections** | mail, calendar, GitHub, sources | next |
| **ARIES Agents** | — | next |
| **ARIES Activity** | what the system did, why, and which agent | next |
| **ARIES Files intelligence** | understanding projects, not a new file manager | later |

## What this does *not* license

The principle is about the **surface**, not about reimplementing the foundation. ARIES owns
how Wi-Fi is presented and configured; NetworkManager still does the work. ARIES owns the
power surface; logind still arbitrates sleep. Rewriting a driver, a network stack or a
compositor because "ARIES should own it" would produce a worse system and contradicts the
standing rule that no dependency is adopted or rejected for identity reasons (§3).

The test is the user's experience: *do they have to know?* If the answer is no, the
implementation may be anything that works.

## The session goal, and the fallback

Long term:

```
POWER → ARIES → ARIES Login → ARIES Desktop
```

with Ubuntu beneath it providing kernel, drivers, packages and systemd. Linux applications
stay Linux applications — Firefox, PyCharm, a terminal — and the *environment* around them
is ARIES: window management, shortcuts, notifications, permissions, workspace behaviour.

And permanently, until ARIES is mature:

```
Sessions:
  ● ARIES
  ○ Ubuntu (fallback)
```

The fallback is not a transitional embarrassment to be removed as soon as possible. It is
the recovery environment, and losing it would make every later change riskier than it needs
to be. No milestone may remove it.
