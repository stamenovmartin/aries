/* The application launcher: a grid, search-first, keyboard-navigable.
 *
 * Small on purpose. GNOME's own app grid is already search-first and keyboard
 * navigable, and it is reached from the overview; this exists because the brief
 * asks for an ARIES launcher, and because the overview's grid arrives with the
 * whole overview animation attached when all you wanted was to start a program.
 *
 * So: one key, one grid, no folders, no pagination dots, no "frequent" tab that
 * reorders itself under your fingers. A launcher you can predict is a launcher
 * you stop looking at, which is the point.
 */

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import * as Log from './log.js';

const COLUMNS = 6;
const ICON = 56;

const Tile = GObject.registerClass(
class Tile extends St.Button {
    _init(app) {
        super._init({
            style_class: 'aries-dock-item aries-focusable',
            can_focus: true,
            reactive: true,
            track_hover: true,
            x_expand: true,
        });
        this.app = app;
        const box = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            x_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(app.create_icon_texture(ICON));
        const label = new St.Label({
            text: app.get_name(),
            style_class: 'aries-command-detail',
            x_align: Clutter.ActorAlign.CENTER,
        });
        label.clutter_text.ellipsize = 3;
        label.clutter_text.line_wrap = false;
        box.add_child(label);
        this.set_child(box);
        this.accessible_name = app.get_name();
    }
});

export class Launcher {
    constructor(shell) {
        this._shell = shell;
        this._grab = null;
        this._tiles = [];
        this._selected = 0;

        this._container = new St.BoxLayout({
            style_class: 'aries-command aries-raised',
            orientation: Clutter.Orientation.VERTICAL,
            visible: false,
            reactive: true,
        });
        this._container.accessible_name = 'ARIES application launcher';

        this._entry = new St.Entry({
            style_class: 'aries-command-entry',
            hint_text: 'Applications',
            can_focus: true,
            x_expand: true,
        });
        this._entry.clutter_text.connect('text-changed',
            Log.guarded('launcher typing', () => this._refresh()));
        this._entry.clutter_text.connect('key-press-event',
            (actor, event) => this._onKey(event));
        this._container.add_child(this._entry);

        this._grid = new St.Widget({
            layout_manager: new Clutter.GridLayout({
                orientation: Clutter.Orientation.HORIZONTAL,
                column_spacing: 8, row_spacing: 8,
            }),
            x_expand: true,
        });
        this._scroll = new St.ScrollView({
            x_expand: true, y_expand: true,
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
        });
        // St.ScrollView wants an StScrollable, and a bare St.Widget holding a
        // GridLayout is not one. A BoxLayout wrapper is, and costs nothing.
        const gridHolder = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL, x_expand: true,
        });
        gridHolder.add_child(this._grid);
        this._scroll.set_child(gridHolder);
        this._container.add_child(this._scroll);

        this._footer = new St.Label({
            text: 'Enter to open · ↑↓←→ to choose · Esc to close',
            style_class: 'aries-command-footer',
        });
        this._container.add_child(this._footer);

        Main.layoutManager.addChrome(this._container, {
            // NOT trackFullscreen. The LayoutManager sets `visible` itself for
            // actors that opt into it — `actor.visible = !inFullscreen` — which
            // overrode the `visible: false` this was constructed with, and the
            // panel sat on the desktop from the moment the shell started.
            // Overlays that open and close manage their own visibility; the
            // dock, which is always meant to be there, still uses it.
            trackFullscreen: false,
            affectsStruts: false,
        });
    }

    get visible() {
        return this._container.visible;
    }

    toggle() {
        if (this.visible)
            this.close();
        else
            this.open();
    }

    open() {
        Log.guard('launcher open', () => {
            const monitor = Main.layoutManager.primaryMonitor;
            if (!monitor)
                return;
            this._width = Math.min(760, Math.round(monitor.width * 0.7));
            this._container.visible = true;
            this._resize();
            this._container.opacity = 0;
            this._container.ease({
                opacity: 255, duration: this._shell.motion(160),
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });
            this._grab = Main.pushModal(this._container,
                {actionMode: Shell.ActionMode.NORMAL});
            this._entry.set_text('');
            this._entry.grab_key_focus();
            this._refresh();
        });
    }

    close() {
        if (!this.visible)
            return;
        Log.guard('launcher close', () => {
            if (this._grab) {
                Main.popModal(this._grab);
                this._grab = null;
            }
            this._container.ease({
                opacity: 0, duration: this._shell.motion(90),
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => {
                    this._container.visible = false;
                },
            });
        });
    }

    /* Same rule as the command bar: a chrome actor lays itself out, so it must
     * set its own size as well as its own position, and recompute both whenever
     * the number of tiles changes. */
    _resize() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor || !this._width)
            return;
        this._scroll.set_height(Math.min(460, Math.round(monitor.height * 0.55)));
        const [, natural] = this._container.get_preferred_height(this._width);
        const height = Math.min(natural, Math.round(monitor.height * 0.75));
        this._container.set_size(this._width, height);
        this._container.set_position(
            Math.round(monitor.x + (monitor.width - this._width) / 2),
            Math.round(monitor.y + monitor.height * 0.12));
    }

    _apps() {
        // `AppSystem.get_installed()` returns Gio.DesktopAppInfo, NOT Shell.App —
        // they share get_name/get_id and nothing else, so the tiles asked a
        // GAppInfo for `create_icon_texture` and the grid never drew. Looked up
        // through the AppSystem here, once, so everything downstream has the
        // richer object.
        const system = Shell.AppSystem.get_default();
        const query = this._entry.get_text().trim().toLowerCase();
        const apps = [];
        for (const info of system.get_installed()) {
            if (info.should_show && !info.should_show())
                continue;
            const name = info.get_name() ?? '';
            if (query && !name.toLowerCase().includes(query))
                continue;
            const app = system.lookup_app(info.get_id());
            if (app)
                apps.push(app);
        }
        apps.sort((a, b) => (a.get_name() ?? '').localeCompare(b.get_name() ?? ''));
        return apps.slice(0, 48);
    }

    _refresh() {
        Log.guard('launcher refresh', () => {
            this._grid.destroy_all_children();
            this._tiles = [];
            const layout = this._grid.layout_manager;
            this._apps().forEach((app, index) => {
                const tile = new Tile(app);
                tile.connect('clicked', Log.guarded('launch', () => {
                    this.close();
                    app.open_new_window(-1);
                }));
                layout.attach(tile, index % COLUMNS, Math.floor(index / COLUMNS), 1, 1);
                this._tiles.push(tile);
            });
            this._select(0);
            // Same reason as the command bar: the grid's preferred height is
            // not real until Clutter has allocated the tiles.
            if (this.visible) {
                GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                    Log.guard('launcher resize', () => this._resize());
                    return GLib.SOURCE_REMOVE;
                });
            }
        });
    }

    _select(index) {
        if (this._tiles.length === 0)
            return;
        const wrapped = (index + this._tiles.length) % this._tiles.length;
        this._tiles.forEach((tile, i) => {
            if (i === wrapped)
                tile.add_style_pseudo_class('selected');
            else
                tile.remove_style_pseudo_class('selected');
        });
        this._selected = wrapped;
    }

    _onKey(event) {
        const symbol = event.get_key_symbol();
        switch (symbol) {
        case Clutter.KEY_Escape:
            this.close();
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Right:
            this._select(this._selected + 1);
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Left:
            this._select(this._selected - 1);
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Down:
            this._select(this._selected + COLUMNS);
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Up:
            this._select(this._selected - COLUMNS);
            return Clutter.EVENT_STOP;
        case Clutter.KEY_Return:
        case Clutter.KEY_KP_Enter: {
            const tile = this._tiles[this._selected];
            if (tile) {
                this.close();
                tile.app.open_new_window(-1);
            }
            return Clutter.EVENT_STOP;
        }
        default:
            return Clutter.EVENT_PROPAGATE;
        }
    }

    destroy() {
        if (this._grab) {
            try {
                Main.popModal(this._grab);
            } catch (_) {
                // Already dropped during teardown.
            }
            this._grab = null;
        }
        Main.layoutManager.removeChrome(this._container);
        this._container.destroy();
    }
}
