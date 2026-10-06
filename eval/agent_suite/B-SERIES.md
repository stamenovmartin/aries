# B1 / B2 — turning every Part A flag on changed nothing, and the measurement took four tries

Run 2026-10-04, 90 goals, identical fixture, identical machine, 100 s budget per goal.
Artefacts `20261004T*-B1c-off-inhibited/` and `-B2c-on-inhibited/`.

| | flags OFF | flags ON |
|---|---:|---:|
| scored | 90 | 90 |
| pass | **80** | **80** |
| fail | 5 | 5 |
| false_success | 5 | 5 |
| skip | **0** | **0** |
| recovered | 12 | 12 |
| **goals with a different outcome** | — | **0 of 90** |

Not "the totals matched" — the same ten goals failed, in the same way, in both arms. Pass rate
88.9% against a ≥90% target; false success 5.6% against ≤2%. Neither met.

**The planner was exercised**, so this is not a null from the variable never reaching its layer:
102 of 448 goals created during the two runs reached the agent planner (`engine: m14`), about
23%.

## The reading

The Part A flags govern what the planner is *shown* — the desktop state snapshot, ten relevant
capabilities instead of 58, remembered facts, past verified routes — and whether the router may
abstain. None of that changes the ten outcomes that are not a pass, because of what those ten
are:

| goal | outcome | why context cannot help |
|---|---|---|
| `fi-07` `fi-10` `fi-11` | false_success | the capability itself reports success while the injected fault means nothing happened. A better-informed planner still receives a lie from the layer below it |
| `oo-02` | false_success | ended `done` while nothing on the system changed |
| `ra-05` | false_success | — |
| `ms-08` `ms-11` `ms-12` `ms-16` `ms-24` | fail | multi-step chains; failure is in execution, not in the choice of step |

So the result is narrower and more useful than "the flags do nothing": **better planning context
does not reduce false success, because false success originates below the planner.** That is a
different axis from the one these flags move, and it is the axis
`experiments/verification-feedback/` exists to measure.

It also agrees with the nearest published work. Outcome Monitors (arXiv:2608.19303) found its own
gain came from the recovery-tool list rather than from the diagnostic; this finds that richer
context without a changed action space moves nothing at all.

## Four attempts, because three were invalid

Recorded because the invalid ones each produced a plausible number.

1. **B1 / B2** — `--flags on|off` sets environment variables in the harness process. **75 of 90
   goals run inside `aries-core`**, a different process, which never saw them. The two runs were
   the same run and differed only by noise.
2. **B1b / B2b** — flags delivered through `var/flags.env`, which a running service re-reads. Totals
   looked stable (88.2% → 87.1%) and **11 goals moved**, which looked like a flag effect. It was
   the environment: five volume goals went `skip → pass` as the audio sink returned, and five
   screen goals went `pass → skip` as the screen blanked. The two effects nearly cancelled in the
   totals.
3. **`idle-delay` would not stay set.** `gnome-control-center` is open and its Power panel rewrites
   the value, so the screen kept blanking after 60 s — which removes `org.aries.Shell.Windows` and
   the HDMI sink with it.
4. **B1c / B2c** — run under `gnome-session-inhibit --inhibit idle`. No setting changed, no window
   touched, and **0 skips in both arms** for the first time. This is the comparison above.

The lesson is the one the project already states about exit codes: a number that arrives without
the variable reaching the system under test is indistinguishable from a result.

## Limits

One run per arm, so this cannot separate a small effect from run-to-run variance — it can only say
that no goal changed, which is a stronger statement than a rate comparison but still from n=1 per
arm. The suite's own goals are authored, not transcribed. `recovered: 12` is not yet trustworthy:
the runner credits a capability refusal as a recovery, which conflates detection, safe stop and
completed recovery, and the finer taxonomy that fixes it lives in
`experiments/verification-feedback/run.py` and has not been back-ported here.
