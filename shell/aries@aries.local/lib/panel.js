/* The ARIES mark in the top bar, and the top bar becoming ARIES's.
 *
 * WHAT WAS WRONG BEFORE
 * ---------------------
 * v0.1 added an indicator to GNOME's panel and called it an ARIES top bar. At
 * rest the desktop looked like Ubuntu with one extra label, which is exactly the
 * "GNOME feature with an ARIES add-on" shape `PRODUCT_IDENTITY.md` rules out.
 * The user's verdict was blunt and correct: "I still see essentially Ubuntu."
 *
 * It also shipped a second set of workspace dots. GNOME 50's Activities button
 * already contains `WorkspaceIndicators`, so ARIES was drawing pills beside
 * pills — a duplicate nobody asked for, and the kind of thing that only shows up
 * when somebody looks at the actual screen.
 *
 * WHAT IT DOES NOW
 * ----------------
 * One mark, at the far left, where every desktop puts the thing that tells you
 * whose desktop it is. It is a button: clicking it opens ARIES Search. The rest
 * of the transformation is the stylesheet — the panel's ground, its accent
 * underline, square-ish corners where Yaru uses pills, normal weight where Yaru
 * uses bold — because restyling what GNOME already draws is both less code and
 * less risk than replacing it.
 *
 * WHAT IT DOES NOT DO
 * -------------------
 * It does not remove GNOME's own indicators. Network, audio, battery and the
 * clock stay exactly where they are and keep working, because reimplementing
 * them would mean a worse network menu in the name of coherence. They are
 * restyled to the ARIES language instead, which is the whole difference between
 * owning a surface and rewriting a stack.
 */

import Cairo from 'cairo';
import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';

import * as Log from './log.js';

/* The horns, drawn rather than loaded.
 *
 * The first version used `Gio.FileIcon` on an SVG shipped with the extension,
 * and it rendered nothing at all — silently. This machine has
 * `libpixbufloader_svg.so` on disk but not registered in the gdk-pixbuf loader
 * cache, so a file icon pointing at an SVG resolves to an empty texture. GNOME's
 * own symbolic icons still work because they come from the icon theme, which
 * takes a different path; an arbitrary file does not.
 *
 * Drawing removes the dependency entirely: no loader, no file to install, no
 * path to get wrong when the extension is copied to /usr/local. It is also the
 * only version that is guaranteed to look the same on a machine we have not
 * seen. Cairo is what the shell itself uses for exactly this.
 */
const AriesHorns = GObject.registerClass(
class AriesHorns extends St.DrawingArea {
    _init(size) {
        super._init({
            width: size,
            height: size,
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'aries-mark-icon',
        });
        // Guarded like everything else: a drawing error must not repeat on every
        // frame, and must be visible in the failure list rather than only in the
        // journal, where it went unnoticed because the message never says
        // "aries".
        this.connect('repaint', Log.guarded('draw the mark', () => this._draw()));
    }

    _draw() {
        const cr = this.get_context();
        const [w, h] = this.get_surface_size();
        // The stroke colour comes from the stylesheet, so the mark follows the
        // theme rather than pinning a hue that breaks in a light session.
        //
        // `cr.setSourceColor(colour)` — a method on the CONTEXT. The first
        // version called `Clutter.cairo_set_source_color(cr, colour)`, which
        // does not exist in GNOME 50: every repaint threw
        // "cairo_set_source_color is not a function" and the mark drew nothing.
        // The shell's own BarLevel and BoxPointer use this form.
        const colour = this.get_theme_node().get_foreground_color();
        cr.setSourceColor(colour);

        const s = Math.min(w, h) / 24;          // the SVG was drawn on a 24 grid
        cr.setLineWidth(1.9 * s);
        cr.setLineCap(Cairo.LineCap.ROUND);
        cr.setLineJoin(Cairo.LineJoin.ROUND);
        const x = v => v * s;
        const y = v => v * s;

        // the brow
        cr.moveTo(x(12), y(20));
        cr.lineTo(x(12), y(8));
        // right horn: out, over, curling back
        cr.moveTo(x(12), y(8));
        cr.curveTo(x(12), y(5.2), x(13.6), y(3.4), x(15.8), y(3.4));
        cr.curveTo(x(18.6), y(3.4), x(20.6), y(5.8), x(20.6), y(9));
        cr.curveTo(x(20.6), y(11.9), x(19.1), y(13.8), x(17.2), y(13.8));
        cr.curveTo(x(15.8), y(13.8), x(14.9), y(12.8), x(14.9), y(11.5));
        cr.curveTo(x(14.9), y(10.4), x(15.6), y(9.6), x(16.5), y(9.6));
        // left horn: the mirror
        cr.moveTo(x(12), y(8));
        cr.curveTo(x(12), y(5.2), x(10.4), y(3.4), x(8.2), y(3.4));
        cr.curveTo(x(5.4), y(3.4), x(3.4), y(5.8), x(3.4), y(9));
        cr.curveTo(x(3.4), y(11.9), x(4.9), y(13.8), x(6.8), y(13.8));
        cr.curveTo(x(8.2), y(13.8), x(9.1), y(12.8), x(9.1), y(11.5));
        cr.curveTo(x(9.1), y(10.4), x(8.4), y(9.6), x(7.5), y(9.6));

        cr.stroke();
        cr.$dispose();
    }
});

export const AriesMark = GObject.registerClass(
class AriesMark extends PanelMenu.Button {
    _init(shell) {
        super._init(0.0, 'ARIES', true);      // no menu — it opens ARIES Search
        this._shell = shell;
        this.add_style_class_name('aries-panel-button');
        this.add_style_class_name('aries-mark-button');

        const box = new St.BoxLayout({
            orientation: Clutter.Orientation.HORIZONTAL,
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._icon = new AriesHorns(20);
        box.add_child(this._icon);

        this._label = new St.Label({
            text: 'ARIES',
            style_class: 'aries-mark',
            y_align: Clutter.ActorAlign.CENTER,
        });
        // The panel gave the label a narrower allocation than its natural width
        // and St ellipsized it to "ARI…" without complaint. A four-letter name
        // that does not fit is a name nobody reads.
        this._label.clutter_text.ellipsize = 0;         // PANGO_ELLIPSIZE_NONE
        this._label.clutter_text.single_line_mode = true;
        box.add_child(this._label);
        this.add_child(box);

        // Said out loud, because a mark with no name is a logo nobody can look
        // up — and because a screen reader gets nothing from a path.
        this.accessible_name = 'ARIES — open search';

        this.connect('button-press-event', Log.guarded('mark clicked', () => {
            this._shell.commandBar?.toggle();
            return Clutter.EVENT_STOP;
        }));
        this.connect('key-press-event', Log.guarded('mark keyed', (actor, event) => {
            const symbol = event.get_key_symbol();
            if (symbol === Clutter.KEY_Return || symbol === Clutter.KEY_space) {
                this._shell.commandBar?.toggle();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        }));
    }
});

/** Put ARIES in the panel and mark the panel as ARIES's. Returns a teardown. */
export function install(shell) {
    const added = [];

    Log.guard('panel class', () => Main.panel.add_style_class_name('aries-panel'));

    Log.guard('aries mark', () => {
        const mark = new AriesMark(shell);
        // Position 0 in the left box: before Activities, where the thing that
        // says whose desktop this is belongs.
        Main.panel.addToStatusArea('aries-mark', mark, 0, 'left');
        added.push('aries-mark');
    });

    return {
        destroy() {
            Log.guard('panel class off',
                () => Main.panel.remove_style_class_name('aries-panel'));
            for (const role of added)
                Main.panel.statusArea[role]?.destroy();
        },
    };
}
