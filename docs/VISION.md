# ARIES — Vision

**ARIES** is the *Artificial Responsive Intelligent Execution System*: a personal,
AI-native, adaptive, agentic computing environment built on top of Linux.

## What ARIES is not

Not a chatbot, not a the reviewing agent wrapper, not a collection of prompts, not a Linux theme, not a
macOS clone, not a pile of shell scripts, not a static multi-agent demo.

## What ARIES is

Linux provides a stable operating system. ARIES provides an intelligent environment above
it, where the user states an intention and the system decides how to accomplish it — which
agents, which workflow, which tools, sequential or parallel, and whether to ask first.

The user should not have to choose a model, an agent, a workflow or a tool. Power users
keep access to all of it.

## The properties that define it

**Responsive.** The interface never freezes because an agent is working. Long work is
asynchronous, cancellable, streamed and observable while it runs.

**Adaptive.** The system learns from outcomes and corrections at three speeds (§16): a fast
loop measured in seconds, a medium loop in days, a slow loop in weeks that only ever
*proposes* improvements.

**Controlled.** ARIES evolves, but never by rewriting itself. Every change is observed,
measured, sandboxed, benchmarked against a baseline, versioned, and reversible. An agent
never concludes it has improved and deploys itself.

**Auditable.** Nothing important is invisible. Every action has a trace, every memory has a
provenance, every automation has a history, and every learned preference can be inspected,
corrected or deleted by the user.

**Calm.** Minimal, coherent, predictable, low cognitive load. Complexity belongs inside the
system, not in front of the user. ARIES will have its own visual identity rather than
imitating macOS.

## The rule that everything else depends on

> The user always wins.

Learned behaviour never overrides an explicit preference. Security policy overrides
everything. This ordering (§30) is not a convention in ARIES — it is enforced structurally,
so violating it is not possible rather than merely discouraged. See
`ARCHITECTURE.md` and `decisions/ADR-0003`.

## Where it is going

A universal command bar (`Super + Space`) where the user types an intention in their own
words; an orchestrator that understands it, retrieves context, plans, assembles an agent
team, executes, verifies and reports; twenty automations that run quietly in the background;
a memory that remembers what is useful and forgets what is not; and a settings application
that feels like configuring an operating system rather than an AI framework.

Read `ROADMAP.md` for what exists today and what comes next, and `BUILD_JOURNAL.md` for how
each piece was actually built and why.
