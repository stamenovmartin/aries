/* ARIES Shell — the desktop surface of ARIES.
 *
 * ARCHITECTURE
 * ------------
 *      ARIES Shell (this extension, inside gnome-shell)
 *              │  HTTP, asynchronous, 127.0.0.1:8000
 *              ▼
 *      typed ARIES APIs  (/api/aries/shell/*, /api/aries/command)
 *              ▼
 *      ARIES runtime  (aries-core.service)
 *
 * The shell holds no state ARIES could hold instead and decides nothing ARIES
 * could decide. It has no settings of its own, no second copy of the command
 * router, no private index of files, no opinion about whether ARIES is healthy.
 * It draws what the runtime says and sends back what the user did.
 *
 * WHY AN EXTENSION AND NOT A WINDOW
 * ---------------------------------
 * A top bar, a dock and a workspace overview must anchor to screen edges and sit
 * above ordinary windows. On Wayland that needs `wlr-layer-shell`, and Mutter
 * does not implement it — verified on this machine, GNOME Shell 50.1. A GTK4
 * window cannot do it, gtk4-layer-shell is not installed and would not help, and
 * writing a compositor was explicitly out of scope. Inside gnome-shell is the
 * only place this can be built on a GNOME Wayland session. ADR-0008.
 *
 * THE CONSEQUENCE, TAKEN SERIOUSLY
 * --------------------------------
 * Code here runs in the process that draws the user's desktop, and on Wayland a
 * shell that throws on startup cannot be restarted without logging out. So:
 *
 *   · every entry point is wrapped in `Log.guard` — a broken component is left
 *     out and the rest still runs;
 *   · nothing blocks: there is no synchronous HTTP path in the extension at all;
 *   · the dock does not reserve struts, because a crash with struts held would
 *     leave every window's work area wrong until logout;
 *   · `disable()` removes everything it added, in reverse, and tolerates parts
 *     that were never created.
 *
 * A user whose ARIES is stopped, broken, or mid-restart still has a working
 * desktop. That is the first requirement, ahead of every feature.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {Api} from './lib/api.js';
import {CommandBar} from './lib/commandbar.js';
import {DBusSurface} from './lib/dbus.js';
import {Dock, conflictingDock, watchForDocks} from './lib/dock.js';
import {Launcher} from './lib/launcher.js';
import {Notifications} from './lib/notifications.js';
import {Overview} from './lib/overview.js';
import {AriesQuickSettings} from './lib/quicksettings.js';
import {Shortcut} from './lib/shortcut.js';
import * as AriesPanel from './lib/panel.js';
import * as TopBar from './lib/topbar.js';
import {Wallpaper} from './lib/wallpaper.js';
import * as Log from './lib/log.js';

const CONTROL_CENTRE = 'aries-ui';
/* The Control Centre's .desktop id, for RAISING a window that already exists.
 *
 * Launching it again is not enough. On Wayland a process that is not the
 * focused one cannot raise its own window — `Gtk.Window.present()` without an
 * activation token is ignored and the window is marked as demanding attention
 * instead. So asking ARIES for a section while the Control Centre sat behind a
 * terminal navigated the window correctly and left it exactly where it was,
 * which reads as nothing happening.
 *
 * The compositor is allowed to raise it, and this code runs inside the
 * compositor. That is the whole reason this line exists here rather than a
 * `present()` somewhere in the Control Centre, where it cannot work. */
const CONTROL_CENTRE_ID = 'aries-control-centre.desktop';

export default class AriesShell extends Extension {
    enable() {
        this.config = {};
        this._parts = [];
        this._keybindings = [];
        this._status = null;

        Log.state.failures = [];
        Log.log(`enabling ${this.metadata.version} on GNOME ${Main.sessionMode?.currentMode ?? '?'}`);

        this.api = new Api();

        // Everything below is built with whatever configuration is already known
        // — which at this instant is nothing. The shell must come up with ARIES
        // stopped, so defaults are assumed and the real configuration is folded
        // in when it arrives. A shell that waited for an HTTP reply before
        // drawing would be a shell that never drew when ARIES was down.
        this._buildAll();

        this.api.get('/api/aries/shell/config').then(Log.guarded('config', result => {
            if (!result.ok) {
                Log.warn(`no configuration from ARIES (${result.reason}); using defaults`);
                return;
            }
            this.config = result.data?.settings ?? {};
            this._applyConfig();
        }));
    }

    disable() {
        Log.log('disabling');
        for (const name of [...this._keybindings].reverse())
            Log.guard(`unbind ${name}`, () => Main.wm.removeKeybinding(name));
        this._keybindings = [];
        Log.guard('give the shortcut back', () => this.shortcut?.destroy());
        this.shortcut = null;
        if (this._dockWatch)
            Log.guard('stop watching for docks',
                () => Main.extensionManager.disconnect(this._dockWatch));
        this._dockWatch = 0;

        for (const part of [...this._parts].reverse())
            Log.guard(`destroy ${part.name}`, () => part.object?.destroy?.());
        this._parts = [];

        Log.guard('api teardown', () => this.api?.destroy());
        this.api = null;
        this.commandBar = null;
        this.launcher = null;
        this.dock = null;
        this.notifications = null;
        this.quickSettings = null;
        this.overview = null;
        this.mark = null;
        this.wallpaper = null;
        this.topBar = null;
    }

    /* ── construction ───────────────────────────────────────────────────── */

    _buildAll() {
        this._part('aries mark', () => {
            this.mark = AriesPanel.install(this);
            return this.mark;
        });

        this._part('top bar', () => {
            this.topBar = TopBar.install(this);
            return this.topBar;
        });

        this._part('quick settings', () => {
            this.quickSettings = new AriesQuickSettings(this);
            return this.quickSettings;
        });

        this._part('ARIES Search', () => {
            this.commandBar = new CommandBar(this);
            return this.commandBar;
        });

        this._part('launcher', () => {
            this.launcher = new Launcher(this);
            return this.launcher;
        });

        this._part('notifications', () => {
            this.notifications = new Notifications(this);
            this.notifications.start();
            return this.notifications;
        });

        this._part('dock', () => {
            this._dockConflict = conflictingDock(Main.extensionManager);
            if (this._dockConflict) {
                Log.warn(`${this._dockConflict} is enabled, so the ARIES dock is not ` +
                         'drawn. Disable it to use the ARIES dock.');
            } else {
                this.dock = new Dock(this);
            }
            // An extension enabled after us must still win, or switching one on
            // later puts two docks on screen until the next login.
            this._dockWatch = watchForDocks(Main.extensionManager, conflict => {
                if (conflict && this.dock) {
                    Log.warn(`${conflict} was enabled; standing the ARIES dock down`);
                    this.dock.destroy();
                    this.dock = null;
                    this._dockConflict = conflict;
                } else if (!conflict && !this.dock) {
                    this._dockConflict = null;
                    this.dock = new Dock(this);
                }
            });
            return this.dock ?? {destroy: () => {}};
        });

        // After the dock, because it steps the dock aside when the overview
        // opens and needs something to step aside.
        this._part('overview', () => {
            this.overview = new Overview(this);
            return this.overview;
        });

        this._part('wallpaper', () => {
            this.wallpaper = new Wallpaper(this);
            return this.wallpaper;
        });

        this._part('dbus surface', () => new DBusSurface(this));

        this._bindKeys();
    }

    _part(name, build) {
        const object = Log.guard(`build ${name}`, build);
        if (object)
            this._parts.push({name, object});
        else if (Log.state.failures.some(f => f.where === `build ${name}`))
            Log.warn(`${name} is not available; the rest of the shell continues`);
    }

    _bindKeys() {
        // Mutter takes a global shortcut only from a GSettings key, which is why
        // this extension has a schema at all. The VALUE comes from ARIES —
        // `shell.command_shortcut` — so there is still one place a person
        // changes it; it is mirrored into the key in `_applyConfig`.
        Log.guard('bind command bar', () => {
            this._settings = this.getSettings();
            // GNOME gives Super+Space to switch-input-source by default, and
            // Mutter will not hand one accelerator to two actions — so without
            // this the binding registers and the key does nothing at all.
            this.shortcut = new Shortcut(this);
            const note = this.shortcut.claim(this._settings.get_strv('command-bar')[0]);
            if (note)
                this._shortcutNote = note;
            Main.wm.addKeybinding(
                'command-bar', this._settings,
                Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
                Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
                () => this.commandBar?.toggle());
            this._keybindings.push('command-bar');
        });
    }

    _applyConfig() {
        Log.guard('apply config', () => {
            const shortcut = this.config.command_shortcut;
            if (shortcut && this._settings) {
                const current = this._settings.get_strv('command-bar');
                if (current[0] !== shortcut) {
                    this._settings.set_strv('command-bar', [shortcut]);
                    this.shortcut?.claim(shortcut);
                }
            }
            if (this._shortcutNote) {
                this.notifyLocal('ARIES Search', this._shortcutNote);
                this._shortcutNote = null;
            }
            if (this._dockConflict) {
                this.notifyLocal('ARIES dock',
                    `${this._dockConflict} is on, so the ARIES dock is hidden. ` +
                    `Run: gnome-extensions disable ${this._dockConflict}`);
            }
            this.dock?.reconfigure();
            this.wallpaper?.apply(this.config.wallpaper, this.path);
        });
    }

    /* ── what the components call back into ─────────────────────────────── */

    /** Motion duration, honouring both ARIES's setting and the system's. */
    motion(milliseconds) {
        if (!St_animationsEnabled())
            return 0;
        switch (this.config.animations) {
        case 'none': return 0;
        case 'reduced': return Math.round(milliseconds / 2);
        default: return milliseconds;
        }
    }

    /* Which revision this RUNNING shell is.
     *
     * Read once, from a file the install stamps, because the alternative —
     * asking what is on disk — answers a different question. Disabling and
     * re-enabling an extension does not reload it; only a new gnome-shell does.
     * So "what is installed" and "what is running" can differ for hours, and
     * during Entry 016 they did, through three rounds of confident verification.
     */
    buildId() {
        if (this._buildId !== undefined)
            return this._buildId;
        this._buildId = Log.guard('read build id', () => {
            const file = Gio.File.new_for_path(`${this.path}/BUILD`);
            const [ok, bytes] = file.load_contents(null);
            if (!ok)
                return null;
            return new TextDecoder().decode(bytes).split('\n')[0].trim() || null;
        }, null);
        return this._buildId;
    }

    /** Which surfaces are actually up — for the D-Bus surface and the harness. */
    builtParts() {
        return this._parts.map(p => p.name);
    }

    lastStatus() {
        return this._status;
    }

    onStatus(result) {
        this._status = result.ok ? result.data : null;
        this.quickSettings?.setStatus(this._status);
    }

    notifyLocal(title, body) {
        this.notifications?.local(title, body);
    }

    spawn(argv) {
        Log.guard(`spawn ${argv[0]}`, () => {
            const context = global.create_app_launch_context(0, -1);
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
            void context;
        });
    }

    openControlCentre(section = '') {
        const argv = [CONTROL_CENTRE];
        if (section)
            argv.push('--section', section);
        this.spawn(argv);
        /* Then raise it, if it is already running. The spawn navigates an
         * existing window; only the compositor can bring it to the front. A
         * short delay lets a COLD start register its window first — and when
         * there is nothing to raise yet, the launch itself puts the window in
         * front, so nothing is lost by trying and finding nothing. */
        this.raiseControlCentre();
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, 900, () => {
            this.raiseControlCentre();
            return GLib.SOURCE_REMOVE;
        });
    }

    raiseControlCentre() {
        Log.guard('raise control centre', () => {
            const app = Shell.AppSystem.get_default().lookup_app(CONTROL_CENTRE_ID);
            const windows = app?.get_windows() ?? [];
            if (windows.length === 0)
                return;
            Main.activateWindow(windows[0]);
        });
    }

    /** Ask ARIES to carry out an action, and report what happened. */
    act(action, label) {
        this.api.post('/api/aries/shell/act', action).then(Log.guarded('act', result => {
            if (!result.ok) {
                this.notifyLocal(label ?? 'ARIES', result.reason);
                return;
            }
            const message = result.data?.message;
            if (message)
                this.notifyLocal(label ?? 'ARIES', message);
        }));
    }

    /**
     * Carry out one result from ARIES Search.
     *
     * The split is the whole architecture in one method: kinds the SHELL can
     * perform are performed here, and everything that changes ARIES goes back
     * over the API so it takes the same permission-checked, audited path as the
     * CLI. There is no privileged desktop route into ARIES.
     */
    perform(action, label) {
        if (!action)
            return;
        switch (action.kind) {
        case 'launch_app': {
            const app = Shell.AppSystem.get_default().lookup_app(action.id);
            if (app)
                app.open_new_window(-1);
            else
                this.notifyLocal('ARIES Search', `${action.id} is no longer installed`);
            return;
        }
        case 'open_path':
            this.spawn(['gio', 'open', action.path]);
            return;
        case 'navigate':
            this.openControlCentre(action.section ?? '');
            return;
        case 'explain':
        case 'run_automation':
        case 'feedback':
        case 'interest_avoid':
            this.act(action, label);
            return;
        default:
            this.notifyLocal('ARIES Search', `ARIES does not know how to '${action.kind}' yet`);
        }
    }
}

/** The system's own reduce-motion preference, which always wins. */
function St_animationsEnabled() {
    try {
        return !Meta.prefs_get_gnome_animations || Meta.prefs_get_gnome_animations();
    } catch (_) {
        return true;
    }
}
