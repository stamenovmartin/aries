/* The ARIES mark, alive — and alive only while something is actually measured.
 *
 * WHY THIS IS NOT AN ANIMATION
 * ----------------------------
 * A mark that breathes on a timer is a screensaver: it looks identical whether
 * ARIES is listening, thinking, or dead. This whole system is built on not
 * claiming what it has not observed, and the panel is the one surface the user
 * looks at without asking for anything — so it is the last place to start
 * making things up.
 *
 * So there is no clock that runs because the extension is loaded. Every frame
 * drawn here exists because `mk.aries.Voice.Pulse` arrived:
 *
 *     Pulse(d level, s phase, d confidence)
 *       level       the Silero VAD probability for the 32 ms of audio that just
 *                   went past — a measurement, ~31 of them a second while a
 *                   person is speaking
 *       phase       which part of the loop is running
 *       confidence  the calibrated routing probability, or -1.0 for "unknown"
 *
 * When nothing emits, nothing moves. Not "slowly", not "gently" — the mark is a
 * plain severity dot and this file costs one idle D-Bus match rule.
 *
 * WHAT THE MOTION MEANS, SO IT CAN BE READ RATHER THAN ADMIRED
 * -----------------------------------------------------------
 *   size            `level`: the mark reaches as far as the voice is loud
 *   character       `phase`: listening reaches out, thinking pulls inward and
 *                   denser, acting extends, settled is a calm ring, refused is
 *                   a broken one
 *   sharpness       `confidence`: certain is one crisp ring and tight filaments;
 *                   unsure is several faint offset rings and filaments that
 *                   scatter. Unknown confidence (-1) is drawn as unsure,
 *                   because not knowing is not the same as being sure
 *
 * WHERE THE FLICKER COMES FROM, SINCE IT IS NOT A RANDOM NUMBER
 * ------------------------------------------------------------
 * Each filament's length and angle come from ONE REMEMBERED MEASUREMENT — the
 * last twelve `level` values, laid around the ring. So the scatter is the real
 * roughness of the voice signal, the ring advances by exactly one position per
 * measured audio window, and when the measurements stop the pattern freezes
 * where it stands. `Math.random()` would have looked much the same and meant
 * nothing, which is the entire objection to it.
 *
 * WHAT IT DOES NOT TOUCH
 * ----------------------
 * The dot's colour. Severity is the server's judgement about health (see
 * `topbar.js`), it is the same vocabulary as the Control Centre, and a
 * decoration does not get to argue with it. This file reads that colour out of
 * the dot's own theme node and draws with it, so the mark follows both themes
 * and every severity for free, and light/dark needs no second palette here.
 */

import Cairo from 'cairo';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import * as Log from './log.js';

const BUS_NAME = 'mk.aries.Voice';
const OBJECT_PATH = '/mk/aries/Voice';
const INTERFACE = 'mk.aries.Voice';

/* One frame per Silero window. The emitter measures 32 ms of audio at a time,
 * so drawing faster would interpolate between numbers that do not exist yet and
 * drawing slower would throw measurements away. */
const FRAME_MS = 32;

/* Twelve remembered levels: about four hundred milliseconds of voice, which is
 * roughly a syllable. Fewer and the filaments all move together; more and the
 * ring stops reacting to the word being said now. */
const HISTORY = 12;

/* A level is a claim about the last 32 ms. After this long without one, the
 * claim has expired and the mark relaxes to rest — an emitter that dies
 * mid-sentence must not leave the panel insisting someone is still talking.
 * The PHASE is not expired the same way: it is a state the voice loop declared
 * and it stands until the loop says otherwise, or until it leaves the bus. */
const STALE_MS = 1200;

/* Unknown confidence drawn as mostly-unsure. -1.0 means the router has not
 * spoken yet, which is a real thing to show while ARIES listens: it does not
 * know what you want yet, and the mark says so. */
const UNKNOWN = 0.75;

const TAU = 2 * Math.PI;

/* The character of each phase, as numbers that can be interpolated.
 *
 *   arms    how many filaments — density
 *   reach   how far they extend, as a fraction of the room available
 *   ring    where the halo sits
 *   core    what the nucleus does with level: grow, or (thinking) contract
 *   calm    how much this phase suppresses scatter regardless of confidence,
 *           because "settled" that flickers is a contradiction
 *   inward  filaments run from the halo toward the centre rather than out
 *   broken  the halo is drawn with gaps
 */
const PHASES = {
    idle:      {arms: 0,  reach: 0.00, ring: 0.00, core:  0.00, calm: 1.00},
    listening: {arms: 7,  reach: 0.95, ring: 0.50, core:  0.20, calm: 0.15},
    thinking:  {arms: 11, reach: 0.46, ring: 0.42, core: -0.16, calm: 0.20, inward: true},
    acting:    {arms: 7,  reach: 1.00, ring: 0.60, core:  0.28, calm: 0.10},
    settled:   {arms: 5,  reach: 0.30, ring: 0.52, core:  0.08, calm: 1.00},
    refused:   {arms: 4,  reach: 0.36, ring: 0.46, core:  0.00, calm: 0.85, broken: true},
};

const REST = {amp: 0, reach: 0, ring: 0, core: 0, calm: 1, unc: 0};
const SHAPE = ['reach', 'ring', 'core', 'calm', 'unc'];

const clamp = (v, lo, hi) => (Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : lo);

export class Pulse {
    /** `dot` is the panel's severity dot; it stays the nucleus and stays in charge of colour. */
    constructor(shell, dot) {
        this._shell = shell;
        this._dot = dot;
        this._gone = false;
        this._phase = 'idle';
        this._cfg = PHASES.idle;
        this._history = new Array(HISTORY).fill(0);
        this._cursor = 0;
        this._mean = 0;
        this._last = 0;
        this._clock = 0;
        this._size = 0;
        this._state = {...REST};
        this._target = {...REST};

        Log.guard('pulse attach', () => this._attach());
        Log.guard('pulse listen', () => this._listen());
    }

    /* ── the mark ───────────────────────────────────────────────────────── */

    /* The dot is reparented into a small square field with the drawing area
     * behind it, rather than the drawing area being made a child of the dot.
     * A child painted outside its parent's 8×8 allocation depends on nothing in
     * the panel ever setting `clip_to_allocation`, which is a bet on somebody
     * else's code that costs the whole effect when it is lost. Inside a field
     * everything is within its own allocation and cannot be clipped away. */
    _attach() {
        const parent = this._dot.get_parent();
        if (!parent)
            return;

        this._area = new St.DrawingArea({
            x_expand: true,
            y_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._field = new St.Widget({
            layout_manager: new Clutter.BinLayout(),
            y_align: Clutter.ActorAlign.CENTER,
        });

        parent.insert_child_at_index(this._field, parent.get_children().indexOf(this._dot));
        parent.remove_child(this._dot);
        this._field.add_child(this._area);
        this._field.add_child(this._dot);

        // Centred in the field rather than filled: a BinLayout stretches a FILL
        // child, and the dot is a circle made from an 8px square.
        this._dot.x_align = Clutter.ActorAlign.CENTER;
        this._dot.y_align = Clutter.ActorAlign.CENTER;
        // The stylesheet puts the gap between dot and label on the dot's own
        // margin. Inside the field that margin would push the nucleus off the
        // centre of its own halo; the field is wider than the dot, so it
        // already provides the gap.
        this._dot.set_style('margin-right: 0;');
        this._dot.set_pivot_point(0.5, 0.5);

        this._area.connect('repaint', () => this._hot('pulse draw', () => this._draw()));
        // Both the size and the colour come from the dot's theme node, so a
        // theme change, a severity change and a HiDPI scale change all arrive
        // through the one signal St already emits for them.
        this._styleId = this._dot.connect('style-changed',
            Log.guarded('pulse restyle', () => this._measure()));
        this._destroyId = this._dot.connect('destroy', () => this.destroy());
        this._measure();
    }

    _measure() {
        const dot = Log.guard('pulse dot size',
            () => this._dot.get_theme_node().get_length('height'), 0) || 8;
        // Room to draw in, measured from the dot rather than assumed: this is
        // also what makes the mark right on a HiDPI screen, where the
        // stylesheet's 8px dot is really sixteen.
        const size = Math.round(Math.max(20, dot * 3.4));
        this._nucleus = dot / 2;
        if (size !== this._size) {
            this._size = size;
            this._area?.set_size(size, size);
        }
        this._area?.queue_repaint();
    }

    /* ── the signal ─────────────────────────────────────────────────────── */

    _listen() {
        this._subId = Gio.DBus.session.signal_subscribe(
            // Matched on the well-known name, which `pulse.py` claims for
            // exactly this reason: a second process cannot drive the panel by
            // emitting the same signal from its own connection.
            BUS_NAME, INTERFACE, 'Pulse', OBJECT_PATH, null,
            Gio.DBusSignalFlags.NONE,
            (_c, _s, _p, _i, _n, params) => this._hot('pulse signal', () => this._onPulse(params)));

        // Not for starting anything — the subscription above is already live
        // and costs nothing while unowned. It is for the other direction: when
        // the voice loop leaves the bus, whatever it last said is no longer
        // true of anything, so the mark stops saying it.
        this._watchId = Gio.bus_watch_name(
            Gio.BusType.SESSION, BUS_NAME, Gio.BusNameWatcherFlags.NONE,
            null, () => this._hot('pulse vanished', () => this._rest()));
    }

    /* Stores numbers. Draws nothing.
     *
     * Deliberate: the emitter controls how often this runs and the compositor
     * does not, so a chatty or broken emitter must not be able to make the
     * desktop repaint at its own rate. Drawing happens on this file's own
     * frame budget, at most once per measurement window. */
    _onPulse(params) {
        const [level, name, confidence] = params.deepUnpack();
        const amp = clamp(level, 0, 1);
        // An unknown phase claims nothing rather than guessing a character.
        const phase = PHASES[name] ? name : 'idle';
        const conf = Number.isFinite(confidence) ? confidence : -1;

        /* Reduced motion gets the STATE and not the movement.
         *
         * Snapping instead of easing was not enough and measuring said so: the
         * level still arrived thirty-one times a second, so the mark still
         * changed thirty-one times a second — unsmoothed motion rather than
         * less of it, which is the opposite of what the preference asks for.
         * So level is ignored entirely and only a phase change redraws. What
         * is left still answers both questions the mark exists to answer: what
         * ARIES is doing, and how sure it is. */
        this._reduced = this._shell?.motion?.(FRAME_MS) === 0;
        if (this._reduced && phase === this._phase)
            return;

        this._last = GLib.get_monotonic_time() / 1000;
        this._push(amp);
        if (phase !== this._phase) {
            this._phase = phase;
            Log.log(`pulse: ${phase}`);
        }

        const cfg = PHASES[phase];
        this._cfg = cfg;
        const t = this._target;
        t.amp = amp;
        t.reach = cfg.reach;
        t.ring = cfg.ring;
        t.core = cfg.core;
        t.calm = cfg.calm;
        t.unc = conf < 0 ? UNKNOWN : clamp(1 - conf, 0, 1);
        this._wake();
    }

    _push(level) {
        this._cursor = (this._cursor + 1) % HISTORY;
        this._history[this._cursor] = level;
        let sum = 0;
        for (let i = 0; i < HISTORY; i++)
            sum += this._history[i];
        this._mean = sum / HISTORY;
    }

    _rest() {
        if (this._phase === 'idle' && this._target.amp === 0)
            return;
        this._phase = 'idle';
        this._cfg = PHASES.idle;
        Object.assign(this._target, REST);
        this._history.fill(0);
        this._mean = 0;
        this._wake();
    }

    /* ── the frame budget ───────────────────────────────────────────────── */

    /* Started by a measurement, and stopped by the drawing catching up with it.
     * That is the whole reason a GLib source is acceptable here: it cannot run
     * unless something was measured, and it removes itself as soon as there is
     * nothing left to show. Between two measurements it is not inventing
     * motion, it is joining up two real values. */
    _wake() {
        if (this._gone || this._clock)
            return;
        // No frame loop under reduced motion, and no measured roughness either:
        // one even amplitude all the way round, so each phase draws a single
        // still figure rather than a frozen sample of somebody's voice.
        if (this._reduced) {
            this._history.fill(0.6);
            this._mean = 0.6;
            this._target.amp = this._cfg.reach > 0 ? 0.6 : 0;
            Object.assign(this._state, this._target);
            this._apply();
            return;
        }
        this._clock = GLib.timeout_add(GLib.PRIORITY_DEFAULT, FRAME_MS,
            () => this._hot('pulse frame', () => this._tick()) ?? GLib.SOURCE_REMOVE);
    }

    _tick() {
        const t = this._target;
        const s = this._state;

        if (GLib.get_monotonic_time() / 1000 - this._last > STALE_MS)
            t.amp = 0;

        // An envelope follower, asymmetric like every other one: a voice starts
        // faster than it stops, and a mark that fell as fast as it rose would
        // strobe on every consonant.
        s.amp += (t.amp - s.amp) * (t.amp > s.amp ? 0.55 : 0.16);
        let settled = Math.abs(t.amp - s.amp) < 0.004;
        for (const key of SHAPE) {
            s[key] += (t[key] - s[key]) * 0.22;
            settled = settled && Math.abs(t[key] - s[key]) < 0.004;
        }

        this._apply();
        if (!settled)
            return GLib.SOURCE_CONTINUE;
        // Land exactly on the target so the next comparison starts from truth.
        Object.assign(s, t);
        this._apply();
        this._clock = 0;
        return GLib.SOURCE_REMOVE;
    }

    /* Scale is set here rather than while drawing: changing an actor's
     * transform from inside its own repaint queues another repaint, which is a
     * loop that never gives the compositor a frame off. */
    _apply() {
        const scale = 1 + this._state.core * this._state.amp;
        this._dot?.set_scale(scale, scale);
        this._area?.queue_repaint();
    }

    /* ── drawing ────────────────────────────────────────────────────────── */

    _draw() {
        const cr = this._area.get_context();
        try {
            const [w, h] = this._area.get_surface_size();
            const dot = this._dot;
            // The dot's own centre, not the field's: whatever margin or
            // alignment the stylesheet gives it, the halo stays concentric.
            const cx = dot.x + dot.width / 2 - this._area.x;
            const cy = dot.y + dot.height / 2 - this._area.y;
            const nucleus = Math.max(2, this._nucleus ?? dot.width / 2);
            // Never ask for a pixel outside the texture: a DrawingArea clips to
            // its allocation, and a halo silently cut in half reads as a bug.
            const room = Math.min(cx, w - cx, cy, h - cy) - 1;
            const s = this._state;
            // Everything is drawn in the ring of space OUTSIDE the nucleus, and
            // the nucleus is the dot AS SCALED — the first version measured from
            // its resting radius, so at the moment a loud voice grew the dot it
            // also grew over the filaments that were reporting that voice, and
            // listening rendered as a featureless blob.
            const base = Math.max(nucleus, nucleus * (1 + s.core * s.amp)) + 1;
            const span = room - base;
            if (span <= 0.5 || (s.amp <= 0.005 && s.ring <= 0.005))
                return;

            // Severity's colour, straight from the dot. St hands out Cogl
            // colours as floats now and handed out 0-255 before; both are
            // accepted rather than assumed, because the wrong one is not an
            // error, it is a mark that draws black on black.
            const bg = dot.get_theme_node().get_background_color();
            const ch = v => (v > 1.0001 ? v / 255 : v);
            const [R, G, B] = [ch(bg.red), ch(bg.green), ch(bg.blue)];

            // How unsure ARIES is, after the phase has had its say.
            const blur = clamp(s.unc * (1 - s.calm), 0, 1);
            const cfg = this._cfg;

            cr.setLineCap(Cairo.LineCap.ROUND);
            cr.setLineJoin(Cairo.LineJoin.ROUND);

            // ── the halo: one crisp ring when certain, several faint offset
            // ones when not. Cairo has no blur and a blur would cost more than
            // the whole rest of this file; three rings 0.3 px apart read as the
            // same thing at this size.
            const rr = base + span * s.ring * (0.45 + 0.55 * s.amp);
            if (s.ring > 0.005) {
                const layers = 1 + Math.round(2 * blur);
                const alpha = (0.16 + 0.46 * s.amp) / layers;
                cr.setLineWidth(Math.max(0.6, 1.4 - 0.7 * blur));
                for (let i = 0; i < layers; i++) {
                    const off = layers === 1
                        ? 0 : (i / (layers - 1) - 0.5) * span * 0.5 * blur;
                    const r = Math.max(1, rr + off);
                    cr.setSourceRGBA(R, G, B, alpha);
                    if (cfg.broken) {
                        // A refusal is a ring that does not close.
                        cr.newSubPath(); cr.arc(cx, cy, r, 0.25 * TAU, 0.72 * TAU);
                        cr.newSubPath(); cr.arc(cx, cy, r, 0.78 * TAU, 1.19 * TAU);
                    } else {
                        cr.newSubPath(); cr.arc(cx, cy, r, 0, TAU);
                    }
                    cr.stroke();
                }
            }

            // ── the filaments. Each one is a remembered measurement: its
            // length is a level ARIES actually heard, and its angle is that
            // level's distance from the recent average, so a steady voice draws
            // a neat star and a hesitant one draws a scatter. The ring of
            // measurements advances once per measurement, never per frame,
            // which is why the pattern freezes rather than idles.
            const arms = cfg.arms;
            if (arms > 0 && s.reach > 0.005 && s.amp > 0.01) {
                const gate = 0.35 + 0.65 * s.amp;
                const tips = [];
                cr.setLineWidth(Math.max(0.6, 1.4 - 0.5 * blur));
                cr.setSourceRGBA(R, G, B, (0.22 + 0.62 * s.amp) * (1 - 0.35 * blur));
                for (let i = 0; i < arms; i++) {
                    const hv = this._history[(this._cursor + i) % HISTORY];
                    const dev = hv - this._mean;
                    const ang = (i / arms) * TAU + dev * blur * 2.2;
                    const len = span * s.reach * (0.25 + 0.75 * hv) * gate;
                    if (len < 0.4)
                        continue;
                    // Thinking runs the filaments from the halo back toward the
                    // nucleus: the same signal, pointing inward, reads as
                    // gathering rather than reaching.
                    const from = cfg.inward ? Math.max(base, rr) : base;
                    const to = cfg.inward ? Math.max(base, rr - len) : base + len;
                    const mid = (from + to) / 2;
                    // A curve rather than a spoke, bowed by how far this
                    // measurement sat from the average — a straight line is a
                    // dial, a bent one is a dendrite.
                    const bow = clamp(dev * 3, -1, 1) * span * 0.3 + (cfg.inward ? -0.6 : 0.6);
                    const [c, sn] = [Math.cos(ang), Math.sin(ang)];
                    const px = cx + c * mid - sn * bow;
                    const py = cy + sn * mid + c * bow;
                    const tx = cx + c * to;
                    const ty = cy + sn * to;
                    cr.moveTo(cx + c * from, cy + sn * from);
                    cr.curveTo(px, py, px, py, tx, ty);
                    tips.push(tx, ty, hv);
                }
                cr.stroke();

                // The terminal nodes, in one fill: a filament ending in nothing
                // is a spike, a filament ending in a node is a cell.
                cr.setSourceRGBA(R, G, B, (0.35 + 0.55 * s.amp) * (1 - 0.35 * blur));
                for (let i = 0; i < tips.length; i += 3) {
                    cr.newSubPath();
                    cr.arc(tips[i], tips[i + 1],
                        Math.max(0.6, 2.0 * tips[i + 2] * (1 - 0.35 * blur)), 0, TAU);
                }
                cr.fill();
            }
        } finally {
            cr.$dispose();
        }
    }

    /* ── containment ────────────────────────────────────────────────────── */

    /* The hot paths do not use `Log.guarded`, on purpose.
     *
     * `Log.guarded` records every failure, and these run up to thirty-one times
     * a second: one bad frame would push thirty entries a second into the
     * failure list and into every `Ping()` reply for the rest of the session,
     * which is a memory leak wearing a diagnostic's clothes. So the first
     * failure is reported once through the normal channel — it still appears in
     * the panel's failure list, where it belongs — and then the pulse stands
     * itself down for good. A decoration that breaks goes quiet; it does not
     * narrate, and it does not take the dot with it. */
    _hot(where, fn) {
        if (this._gone || this._broken)
            return GLib.SOURCE_REMOVE;
        try {
            return fn();
        } catch (error) {
            this._broken = true;
            Log.fail(where, error);
            // Sources first: removing a timer or a match rule is safe from
            // anywhere, including from inside the repaint that just threw.
            this._stop();
            // Actors afterwards, on an idle. The failure can have come from
            // `_draw`, and hiding an actor in the middle of painting it is how
            // a drawing bug becomes a compositor bug.
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                this.destroy();
                return GLib.SOURCE_REMOVE;
            });
            return GLib.SOURCE_REMOVE;
        }
    }

    _stop() {
        if (this._subId)
            Log.guard('pulse unsubscribe', () => Gio.DBus.session.signal_unsubscribe(this._subId));
        if (this._watchId)
            Log.guard('pulse unwatch', () => Gio.bus_unwatch_name(this._watchId));
        if (this._clock)
            GLib.source_remove(this._clock);
        this._subId = 0;
        this._watchId = 0;
        this._clock = 0;
    }

    destroy() {
        if (this._gone)
            return;
        this._gone = true;
        this._stop();
        // The dot is handed back exactly as it was lent: its own size, its own
        // margin, and nothing of this file left on it. It outlives the pulse in
        // every case, including the one where the pulse died of a drawing bug.
        Log.guard('pulse release', () => {
            if (this._styleId)
                this._dot.disconnect(this._styleId);
            if (this._destroyId)
                this._dot.disconnect(this._destroyId);
            this._dot.set_scale(1, 1);
            this._dot.set_style(null);
            this._area?.hide();
        });
        this._styleId = 0;
        this._destroyId = 0;
    }
}
