/* The ARIES dock: pinned applications, running applications, and what is focused.
 *
 * WHY THIS ONE IS BUILT RATHER THAN BORROWED
 * ------------------------------------------
 * Unlike the network or audio menus, a dock is presentation over data the shell
 * already holds — `Shell.AppSystem` has every .desktop file and every running
 * application, and `AppFavorites` has the pinned list. There is no NetworkManager
 * equivalent to get wrong here, so building it costs little and is the single
 * most visible piece of "this is ARIES, not stock GNOME".
 *
 * It coexists with Ubuntu's dock rather than fighting it: if `ubuntu-dock` is
 * enabled, ARIES says so and stays out of the way instead of drawing a second
 * bar over the first. Two docks is not a coherent environment.
 *
 * PINNED APPS COME FROM ARIES
 * ---------------------------
 * `shell.pinned_apps` is an ARIES setting, not GNOME's favourites list, because
 * the brief asks for one place where the desktop is configured. GNOME's
 * favourites are still honoured as the fallback when the ARIES list is empty —
 * an empty dock on first run would be worse than borrowing a sensible default.
 *
 * MOTION
 * ------
 * Minimal, and honest about why: the running indicator widens when an app takes
 * focus, and the dock slides on auto-hide. No magnification, no bounce, no
 * genie. Motion is here to say *which* thing changed, and anything beyond that
 * is decoration the brief rules out.
 */

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as AppFavorites from 'resource:///org/gnome/shell/ui/appFavorites.js';

import * as Log from './log.js';

const EDGE_GAP = 8;

const DockItem = GObject.registerClass(
class DockItem extends St.Button {
    _init(app, iconSize) {
        super._init({
            style_class: 'aries-top-app aries-focusable',
            can_focus: true,
            reactive: true,
            track_hover: true,
        });
        this._app = app;

        const box = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._icon = app.create_icon_texture(iconSize);
        box.add_child(this._icon);

        this._running = new St.Widget({
            style_class: 'aries-dock-running',
            x_align: Clutter.ActorAlign.CENTER,
            opacity: 0,
        });
        box.add_child(this._running);
        this.set_child(box);

        this.accessible_name = app.get_name();
        this.connect('clicked', Log.guarded('dock click', () => this._activate()));
    }

    _activate() {
        const windows = this._app.get_windows();
        if (windows.length === 0) {
            this._app.open_new_window(-1);
            return;
        }
        const focused = global.display.focus_window;
        if (windows.includes(focused) && windows.length > 1) {
            // Already looking at this app: cycle rather than re-raise the same
            // window, which is what a second click on a dock icon should mean.
            const next = windows[(windows.indexOf(focused) + 1) % windows.length];
            Main.activateWindow(next);
            return;
        }
        Main.activateWindow(windows[0]);
    }

    setState(running, focused, animate) {
        const opacity = running ? 255 : 0;
        const wide = focused;
        if (wide)
            this._running.add_style_class_name('aries-dock-running-wide');
        else
            this._running.remove_style_class_name('aries-dock-running-wide');

        if (!animate) {
            this._running.opacity = opacity;
            return;
        }
        this._running.ease({
            opacity,
            duration: 90,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
    }

    get app() {
        return this._app;
    }
});

export class Dock {
    constructor(shell) {
        this._shell = shell;
        this._items = new Map();
        this._signals = [];
        this._rebuildId = 0;

        this._container = new St.BoxLayout({
            style_class: 'aries-dock aries-surface',
            orientation: Clutter.Orientation.HORIZONTAL,
            reactive: true,
            track_hover: true,
        });
        this._container.accessible_name = 'ARIES dock';

        // Application strip shares the panel allocation; no bottom/side chrome.
        this._container.style_class = 'aries-top-apps';
        this._container.accessible_name = 'ARIES applications';
        Main.panel._leftBox.insert_child_at_index(this._container, 1);

        const appSystem = Shell.AppSystem.get_default();
        this._signals.push([appSystem, appSystem.connect('app-state-changed',
            () => this._scheduleRebuild())]);
        this._signals.push([appSystem, appSystem.connect('installed-changed',
            () => this._scheduleRebuild())]);
        this._signals.push([global.display, global.display.connect('notify::focus-window',
            () => this._refreshState())]);
        this._signals.push([Main.layoutManager, Main.layoutManager.connect('monitors-changed',
            () => this._reposition())]);

        this._rebuild();
    }

    get config() {
        return this._shell.config ?? {};
    }

    _scheduleRebuild() {
        // App state changes arrive in bursts when a window opens. Coalesce them
        // so a launching application does not rebuild the dock five times.
        if (this._rebuildId)
            return;
        this._rebuildId = GLib.timeout_add(GLib.PRIORITY_DEFAULT_IDLE, 120, () => {
            this._rebuildId = 0;
            Log.guard('dock rebuild', () => this._rebuild());
            return GLib.SOURCE_REMOVE;
        });
    }

    _pinnedIds() {
        const configured = this.config.pinned_apps;
        if (Array.isArray(configured) && configured.length > 0)
            return configured;
        return AppFavorites.getAppFavorites().getFavoriteMap
            ? Object.keys(AppFavorites.getAppFavorites().getFavoriteMap())
            : [];
    }

    _rebuild() {
        const appSystem = Shell.AppSystem.get_default();
        const iconSize = 18;
        const order = [];
        const seen = new Set();

        for (const id of this._pinnedIds()) {
            const app = appSystem.lookup_app(id);
            if (app && !seen.has(app.get_id())) {
                seen.add(app.get_id());
                order.push(app);
            }
        }
        for (const app of Shell.AppSystem.get_default().get_running()) {
            if (!seen.has(app.get_id())) {
                seen.add(app.get_id());
                order.push(app);
            }
        }

        this._container.destroy_all_children();
        this._items.clear();
        // Leave room for clock/status even with many running applications.
        const monitorWidth = Main.layoutManager.primaryMonitor?.width ?? 1280;
        const limit = Math.max(3, Math.min(8, Math.floor((monitorWidth - 750) / 30)));
        for (const app of order.slice(0, limit)) {
            const item = new DockItem(app, iconSize);
            this._container.add_child(item);
            this._items.set(app.get_id(), item);
        }
        const more = new St.Button({style_class: 'aries-top-app', can_focus: true,
            reactive: true, accessible_name: 'All applications',
            child: new St.Icon({icon_name: 'view-app-grid-symbolic', icon_size: 18})});
        more.connect('clicked', Log.guarded('all apps', () => this._shell.launcher?.toggle()));
        this._container.add_child(more);
        this._refreshState(false);
        this._reposition();
    }

    _refreshState(animate = true) {
        Log.guard('dock state', () => {
            const focused = global.display.focus_window;
            const focusedApp = focused
                ? Shell.WindowTracker.get_default().get_window_app(focused)
                : null;
            for (const [id, item] of this._items) {
                const running = item.app.get_windows().length > 0;
                item.setState(running, focusedApp?.get_id() === id, animate);
            }
        });
    }

    _reposition() {
        // The panel owns position and work area; no independent dock actor.
    }

    reconfigure() {
        this._rebuild();
    }

    /** Step aside — the overview brings its own dash. */
    setVisible(visible) {
        if (!this._container)
            return;
        if (!this._shell.motion(1)) {
            this._container.visible = visible;
            this._container.opacity = 255;
            return;
        }
        if (visible)
            this._container.visible = true;
        this._container.ease({
            opacity: visible ? 255 : 0,
            duration: this._shell.motion(160),
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            onComplete: () => {
                this._container.visible = visible;
            },
        });
    }

    destroy() {
        if (this._rebuildId)
            GLib.source_remove(this._rebuildId);
        for (const [object, id] of this._signals)
            object.disconnect(id);
        this._signals = [];

        this._container.destroy();
        this._items.clear();
    }
}

const OTHER_DOCKS = [
    'ubuntu-dock@ubuntu.com',
    'dash-to-dock@micxgx.gmail.com',
    'dash-to-panel@jderose9.github.com',
];

/* Whether another dock is running, so ARIES can stay out of the way.
 *
 * THE TIMING BUG THIS EXISTS TO SURVIVE
 * -------------------------------------
 * The first version asked `extension.state === ACTIVE` once, during `enable()`.
 * In a session that loads several extensions at startup, ARIES is frequently
 * enabled BEFORE Ubuntu's dock finishes activating — so the check saw
 * INITIALIZED, concluded there was no other dock, and drew a second one. Which
 * is exactly what the ARIES session did on its first real login: two docks.
 *
 * So the question is asked of what is CONFIGURED as well as what is currently
 * running. A uuid in the user's `enabled-extensions` will be a dock in a moment
 * even if it is not one yet, and that is knowable immediately.
 */
export function conflictingDock(extensionManager) {
    let configured = [];
    try {
        configured = new Gio.Settings({schema_id: 'org.gnome.shell'})
            .get_strv('enabled-extensions');
    } catch (_) {
        configured = [];
    }
    for (const uuid of OTHER_DOCKS) {
        const ext = extensionManager?.lookup?.(uuid);
        const live = ext && ext.state === 1;             // ACTIVE
        if (live || configured.includes(uuid))
            return uuid;
    }
    return null;
}

/* …and keep asking. An extension enabled after us must still win, because the
 * alternative is two docks appearing the moment someone switches one on. */
export function watchForDocks(extensionManager, onChange) {
    if (!extensionManager?.connect)
        return 0;
    return extensionManager.connect('extension-state-changed', (manager, ext) => {
        if (OTHER_DOCKS.includes(ext?.uuid))
            Log.guard('dock conflict', () => onChange(conflictingDock(manager)));
    });
}
