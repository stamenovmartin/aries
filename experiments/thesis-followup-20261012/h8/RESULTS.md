# H8 results: verifier strength by fault injection

Preregistration: `docs/preregistration/H8-verifier-fault-injection.md`, with Amendments 1 and 2.
Everything ran in one process, offline, against fakes (see the preregistration's limitation section).
All runs use the same harness (`run_mutants.py` SHA-256 `4f17771d…`), except run 1.

| Run | Folder | Verifiers |
|---|---|---|
| 1 (reported, superseded by Amendment 1) | `runs/20261013T211134Z-baseline` | frozen |
| baseline-2 | `runs/20261018T153000Z-baseline2` | frozen |
| hardened | `runs/20261018T154826Z-hardened` | `ARIES_VERIFY_HARDENED=1` |
| sealed set, hardened | `runs/20261018T154928Z-sealed-hardened` | `ARIES_VERIFY_HARDENED=1` |
| sealed set, frozen | `runs/20261018T155010Z-sealed-frozen` | frozen |
| exploratory 23+2 | `runs/20261018T155139Z-exploratory-hardened-23plus2` | both flags |

Each number below is from that folder's `summary.json`, written by `analyze.py`.

## Primary test (confirmatory, Holm family H4b/H5/H6/H8)

One-sided exact McNemar, paired by mutant, hardened against baseline-2: b = 33 (killed now, not before),
c = 0 (killed before, not now), 218 pairs, p = 1.16 × 10⁻¹⁰.
- Kill rate: 155/218 = 0.711 [0.646, 0.770] at baseline-2, and 188/218 = 0.862 [0.809, 0.905] hardened.
- **Holm:** p < 0.05/4. H8 is therefore rejected under Holm whatever the other three p-values turn out
  to be.

## Criteria (hardened run)

1. Mean kill rate over 58 capabilities ≥ 0.80: **0.873, met.** At baseline-2 it was 0.684. The 23
   hardened capabilities went from 0.482 to 0.960.
2. No noop_success survivor: **not met.** Three survive: `notification.send`, `system.disk` and
   `system.status`.
   - `notification.send` and `system.disk` are INDEPENDENT verifiers, which are not changed (the
     user's Option 1, Amendment 2).
   - All three are probably equivalent mutants (Amendment 2). For `notification.send`, the twin world
     does not include the database, so the noop writes the real row. `system.disk` and
     `system.status` read the real machine, so their noop reports are true, slightly earlier
     observations.
3. False alarms ≤ 2%: **0/174 [0, 0.021], met.**

## Sealed second set (generalisation check, not a criterion)

The SHA-256 matched the committed value `fa8556e9…` before the set was opened.

| | Frozen | Hardened |
|---|---|---|
| Killed | 155/218 = 0.711 | 187/218 = 0.858 [0.804, 0.901] |
| Mean over capabilities | 0.684 | 0.868 |
| False alarms | 0/174 | 0/174 |

- The hardened run differs from the public set in one mutant, `system.processes::wrong_target`. Its
  falsified count fell inside the measured-drift tolerance.
- **Limit of this check:** the set seed changes only the concrete wrong values (markers, offsets).
  The wrong targets are fixed in the harness's case table. With frozen verifiers, all 218 verdicts were
  identical to baseline-2. So the sealed set tests other wrong values, not other targets, and this is a
  weak check of generalisation.

## Exploratory "hardened-23+2, designed after baseline-2"

Not confirmatory. The same hardening was added to `notification.send` and `system.disk`
(`ARIES_VERIFY_HARDENED_EXTRA=1`, see `conditions.md` in its folder). The result is identical to the
hardened run: 188/218, mean 0.873, 0/174 false alarms.
- `notification.send`: 1/3 killed (noop and side-effect survive).
- `system.disk`: 2/3 killed (noop survives).

The extra hardening kills nothing more, which is consistent with those noop mutants being equivalent.

## How the 33 newly killed mutants were killed

`diagnose_kills.py` (descriptive) re-ran them: 33/33 were reproduced, and **33/33 were killed by a
failed agreement or invariant check, none by UNVERIFIED** (`diagnose_kills-hardened.json`). So no kill
comes from an exception in the hardened code.

## What hardening did not change

- `side_effect_outside_scope` is 0/14 before and after. Those mutants are all in INDEPENDENT verifiers:
  no verifier checks for changes outside the requested target.
- The hardened capabilities below 1.0 are `browser.scroll` (0.75; `wrong_value` survives, since without
  the state before the scroll its size cannot be checked) and `system.processes` and `system.status`
  (0.67).
- The secondary outcome: 2 hardened-run survivors carried the false value into the evidence (both
  `network.wifi_list`, INDEPENDENT), against 7 at baseline-2.
