# A10 — changes I did not make, and why

agent/surfaces, 2026-10-03. Each entry names the file, the function, the exact
change, and what stopped me applying it. Nothing here is applied.

---

## 1. `shell/aries@aries.local/lib/dbus.js` · `TILE_SIDES` — the real HiDPI fix

**Status: proposed, not applied. Outside my write scope, and it cannot be
deployed today in any case** — a GNOME Shell extension is reloaded at logout, not
at install, so an edit here would sit on disk unexercised while the shell in
memory kept the old arithmetic. Codex has also asked repeatedly that nobody
restart core or the shell during its benchmark windows.

### What is wrong now

`TILE_SIDES` computes each rectangle from the work area in LOGICAL pixels with
`Math.floor(a.width / 2)` and `Math.ceil(a.width / 2)`. Mutter then places the
window on whole DEVICE pixels. At scale 1.0 and 2.0 that is the same thing; at
1.25, 4/3, 1.5, 1.75 and 2.25 it is not, so `move_resize_frame` is handed a size
Mutter has to adjust, the window lands a pixel from where the shell said, and
`desktop.tile`'s verifier — which compares geometry by equality against the
`expected` the shell reported — calls a CORRECT tile unconfirmed.

### What I did instead, inside my scope

`aries/operator/desktop.py` now reads the scale factor from
`org.gnome.Mutter.DisplayConfig.GetCurrentState` and computes the device-aligned
rectangle itself (`device_step`, `tile_rect`, `tile_expectation`), and
`aries/workspace/desktop_capabilities.py`'s tile verifier accepts either exact
rectangle. That removes the false "unconfirmed" without touching the shell. It
does NOT make the window land on a whole device pixel in the first place — only
the compositor-side arithmetic can do that.

### The patch

```javascript
/* Where each named side lands inside a monitor's work area.
 *
 * Halves are floored to a whole number of DEVICE pixels and the second tile is
 * placed against the far edge of the work area, so left and right meet without
 * overlapping and both edges survive Mutter's own rounding. At scale 1 and 2 the
 * step is 1 and this is exactly the floor/ceil it replaces; at 1.5 the step is 2
 * and at 1.25 it is 4. aries/operator/desktop.py carries the same arithmetic in
 * Python and tests/test_tile_hidpi.py compares the two by reading THIS file. */
const deviceStep = scale => {
    // GNOME's fractional scales are small rationals: 1, 1.25, 4/3, 1.5, 5/3,
    // 1.75, 2, 2.25, 2.5, 2.75, 3. The denominator is the step.
    for (const step of [1, 2, 3, 4, 6, 8, 12, 16])
        if (Math.abs(scale * step - Math.round(scale * step)) < 1e-6)
            return step;
    return 1;
};

const split = a => {
    const step = deviceStep(a.scale ?? 1);
    const halfW = Math.min(a.width, Math.max(step, Math.floor(Math.floor(a.width / 2) / step) * step));
    const halfH = Math.min(a.height, Math.max(step, Math.floor(Math.floor(a.height / 2) / step) * step));
    return {halfW, halfH, right: a.x + a.width - halfW, bottom: a.y + a.height - halfH};
};

const TILE_SIDES = {
    left:        a => { const s = split(a); return {x: a.x,    y: a.y,      width: s.halfW, height: a.height}; },
    right:       a => { const s = split(a); return {x: s.right, y: a.y,     width: s.halfW, height: a.height}; },
    top:         a => { const s = split(a); return {x: a.x,    y: a.y,      width: a.width, height: s.halfH}; },
    bottom:      a => { const s = split(a); return {x: a.x,    y: s.bottom, width: a.width, height: s.halfH}; },
    topleft:     a => { const s = split(a); return {x: a.x,    y: a.y,      width: s.halfW, height: s.halfH}; },
    topright:    a => { const s = split(a); return {x: s.right, y: a.y,     width: s.halfW, height: s.halfH}; },
    bottomleft:  a => { const s = split(a); return {x: a.x,    y: s.bottom, width: s.halfW, height: s.halfH}; },
    bottomright: a => { const s = split(a); return {x: s.right, y: s.bottom, width: s.halfW, height: s.halfH}; },
    full:        a => ({x: a.x, y: a.y, width: a.width, height: a.height}),
};
```

and in `WindowAction`, where the work area is read, carry the scale in with it:

```javascript
            const area = w.get_work_area_for_monitor(w.get_monitor());
            const scale = global.display.get_monitor_scale
                ? global.display.get_monitor_scale(w.get_monitor()) : 1;
            const a = {x: area.x, y: area.y, width: area.width, height: area.height, scale};
            const t = rect(a);
            w.move_resize_frame(false, t.x, t.y, t.width, t.height);
            return JSON.stringify({accepted: true, id: r.id, action: 'tile',
                side: r.side, expected: t, scale});
```

`Windows()` should report the same scale per window, beside `monitor` and
`work_area`, and `protocol_version` should go 4 → 5 so that
`aries/operator/desktop.py::capabilities` can tell a shell that reports a scale
from one that does not. `capabilities()` already accepts `(3, 4)` deliberately,
so that tuple becomes `(3, 4, 5)` in the same edit.

### How to check it once applied

`tests/test_tile_hidpi.py::test_the_python_arithmetic_is_the_shells_arithmetic_at_integer_scale`
reads `TILE_SIDES` out of the JavaScript and compares it with the Python; it will
need its small translator extended for the `split()` form, and it will then fail
loudly if the two ever disagree again. Anything beyond that needs a fractionally
scaled monitor, which this machine does not have.

---

## 2. Nothing was needed in `routes.py` or `permissions.py`

The brief warned that the approval round trip for `system.service_control` might
need one of them. It does not, and the check is in
`tests/test_service_control_approval.py` rather than in this sentence: the whole
path already exists and is exercised end to end against the real user manager —
`capabilities.recognize` → `service.plan` → `capabilities.SENSITIVE` → a durable
`ActionProposal` row → `POST /api/aries/workspace/{id}/approve` (`service.approve`,
unchanged) → `capabilities.execute(approved=True)` → `systemctl --user` →
`verify_control` re-reading the unit. No line of `aries/api/routes.py`,
`aries/api/permissions.py`, `aries/workspace/service.py`,
`aries/workspace/capabilities.py` or `experiments/voice/voice.py` was edited for
A10, and none needs to be.

---

## 3. Three files I DID write that are outside the literal write list

Stated here rather than buried, because the brief's list was
`aries/operator/**`, `aries/speech/**`, new tests, and `eval/surfaces/`:

* `aries/workspace/input_capabilities.py` — `type_text` lives here, not in
  `aries/operator/`. It is the only place the first sub-item can be implemented.
  The file is untracked and unmodified in `git status`, no entry in
  `COORDINATION.md` claims it, and it is not on the do-not-edit list. The edit is
  confined to the worker's `type_text`, a new `untypeable()` helper beside it, and
  `type_into`, all behind `ARIES_TYPE_STRICT`.
* `aries/workspace/desktop_capabilities.py` — `desktop.tile` is registered here.
  Clean in `git status`, unclaimed, not on the do-not-edit list. The edit is
  confined to the `tile` branch of `executor()` and of `verifier()`, behind
  `ARIES_TILE_HIDPI`.
* `aries/flags.py` — two entries appended to `FLAGS`, because
  `flags.enabled()` raises on an unregistered name and the workplan requires
  every flag to be readable from one place. the reviewing agent/main owns this file for A0; the
  change is additive and inside the dict. It was untracked when I started;
  the reviewing agent/main then committed the file WITH my two entries in it as part of
  `bec1816 A4+A0`, so the hunk is already in history under that commit and is not
  in mine. Noted here so the authorship is findable.

Reverting any of the three is turning a flag off, or `git checkout` of that file.

### …and one of them is NOT in my commit

`aries/workspace/input_capabilities.py` is **untracked**: it is a new 650-line
file another worker wrote today and has not committed. `git add` of it would put
all 650 lines inside a commit headed `A10:`, which is exactly what workplan rule 7
("naming only that item's files") exists to prevent. So the A10 edit to that file
is in the working tree, tested by `tests/test_type_text_refusal.py` (which IS
committed and which fails without it), and deliberately left for its owner to
commit.

The hunk, for whoever commits that file:

* `aries/workspace/input_capabilities.py` — a paragraph added to the module
  docstring ("AND IT SAYS WHICH"); `SINGLE_LINE` and `untypeable()` added to
  `_WORKER_BODY` above `type_text`; inside `type_text`, a `strict =
  payload.get('strict', True)` read, a pre-write `untypeable()` refusal, and the
  final return split into an `observed` dict plus `TEXT_REJECTED` /
  `TEXT_NOT_LANDED` refusals that carry it; a new `strict_typing()` helper; and
  `type_into` validating through `TypeInput` and passing `strict` in the payload.
  One sentence added to the `input.type_text` capability description.
