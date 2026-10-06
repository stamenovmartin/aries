/* A small D-Bus surface for the shell itself: org.aries.Shell.
 *
 * ARIES already has a command-line interface and an HTTP API, and the desktop
 * is now a third surface that neither can reach: `aries search` had no way to
 * open ARIES Search, because the search bar lives inside gnome-shell and the
 * CLI is a separate process.
 *
 * So the shell exports what it — and only it — can do. Three methods, matching
 * the three things that are physically in the compositor:
 *
 *     Search()     open ARIES Search
 *     Launcher()   open the application grid
 *     Ping()       is the ARIES shell actually loaded, and which version
 *     Windows()    what is actually on screen right now — READ ONLY
 *     FocusWindow(id, appId)  present an observed window without launching one
 *
 * It is also what makes the shell testable and screenshotable without a human:
 * a harness can open a surface and capture it. That was not the reason for
 * building it, but a surface that can only be driven by a person is a surface
 * that only gets tested when a person remembers to.
 *
 * Nothing here changes ARIES state. Anything that would goes over HTTP to the
 * runtime, so it meets the same permission checks and audit trail as the CLI —
 * there is no privileged desktop route into ARIES, and this does not become one.
 */

import Gio from 'gi://Gio';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import * as Log from './log.js';

/* Where each named side lands inside a monitor's work area.
 *
 * Halves use ceil for the second tile's origin and floor for both widths, so
 * left and right meet exactly on an odd-width monitor instead of overlapping by
 * a pixel or leaving a gap — a one-pixel seam is the kind of thing that looks
 * like a rendering bug rather than arithmetic. */
const TILE_SIDES = {
    left:        a => ({x: a.x, y: a.y, width: Math.floor(a.width / 2), height: a.height}),
    right:       a => ({x: a.x + Math.ceil(a.width / 2), y: a.y, width: Math.floor(a.width / 2), height: a.height}),
    top:         a => ({x: a.x, y: a.y, width: a.width, height: Math.floor(a.height / 2)}),
    bottom:      a => ({x: a.x, y: a.y + Math.ceil(a.height / 2), width: a.width, height: Math.floor(a.height / 2)}),
    topleft:     a => ({x: a.x, y: a.y, width: Math.floor(a.width / 2), height: Math.floor(a.height / 2)}),
    topright:    a => ({x: a.x + Math.ceil(a.width / 2), y: a.y, width: Math.floor(a.width / 2), height: Math.floor(a.height / 2)}),
    bottomleft:  a => ({x: a.x, y: a.y + Math.ceil(a.height / 2), width: Math.floor(a.width / 2), height: Math.floor(a.height / 2)}),
    bottomright: a => ({x: a.x + Math.ceil(a.width / 2), y: a.y + Math.ceil(a.height / 2), width: Math.floor(a.width / 2), height: Math.floor(a.height / 2)}),
    full:        a => ({x: a.x, y: a.y, width: a.width, height: a.height}),
};

const IFACE = `
<node>
  <interface name="org.aries.Shell">
    <method name="Search">
      <arg type="s" direction="in" name="query"/>
    </method>
    <method name="Launcher"/>
    <method name="Close"/>
    <method name="Ping">
      <arg type="s" direction="out" name="state"/>
    </method>
    <method name="Capabilities"><arg type="s" direction="out" name="state"/></method>
    <method name="WindowAction">
      <arg type="s" direction="in" name="request"/>
      <arg type="s" direction="out" name="result"/>
    </method>
    <method name="Windows">
      <arg type="s" direction="out" name="windows"/>
    </method>
    <method name="FocusWindow">
      <arg type="s" direction="in" name="id"/>
      <arg type="s" direction="in" name="appId"/>
      <arg type="s" direction="out" name="result"/>
    </method>
  </interface>
</node>`;

export class DBusSurface {
    constructor(shell) {
        this._shell = shell;
        this._impl = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        Log.guard('dbus export', () => {
            this._impl.export(Gio.DBus.session, '/org/aries/Shell');
            this._owner = Gio.DBus.session.own_name(
                'org.aries.Shell', Gio.BusNameOwnerFlags.REPLACE, null, null);
        });
    }

    Search(query) {
        Log.guard('dbus Search', () => {
            this._shell.commandBar?.open();
            if (query)
                this._shell.commandBar?.setQuery(query);
        });
    }

    Launcher() {
        Log.guard('dbus Launcher', () => this._shell.launcher?.open());
    }

    Close() {
        Log.guard('dbus Close', () => {
            this._shell.commandBar?.close();
            this._shell.launcher?.close();
        });
    }

    /* What actually got built, as data.
     *
     * A shell that "loaded" tells you almost nothing — every component is
     * guarded, so the extension reaches ENABLED whether six surfaces were built
     * or one. The harness needs to know which, and so does anyone diagnosing a
     * desktop where the dock is missing and nothing looks wrong. */
    Ping() {
        return JSON.stringify({
            version: this._shell.metadata?.version ?? null,
            build: this._shell.buildId(),
            built: this._shell.builtParts(),
            failures: Log.state.failures.map(f => ({where: f.where, error: f.text})),
            aries: this._shell.lastStatus()
                ? {state: this._shell.lastStatus().state,
                   severity: this._shell.lastStatus().severity}
                : null,
        });
    }

    /* What is actually on screen, as data.
     *
     * WHY THIS EXISTS
     * ---------------
     * The ARIES Operator has to be able to tell whether a task it was given
     * actually happened. "Open YouTube" is not complete when a command exits 0;
     * it is complete when a browser is on YouTube. Deciding that needs the
     * window list, and on Wayland no client outside the compositor can have it
     * — which is a deliberate security property, not an oversight. Mutter knows,
     * and this extension runs inside Mutter.
     *
     * READ ONLY, ON PURPOSE. This method observes and returns; it does not
     * focus, raise, move or close anything. Acting on a window is a separate
     * decision with a separate audit trail, and mixing the two would mean the
     * call ARIES makes to check its work could also change it — after which no
     * verification means anything.
     *
     * PIDs are included because process identity is the only cross-check
     * available for a window: a title can say anything, but a title on a window
     * owned by a `firefox` process is a stronger claim than either alone. */
    Capabilities() {
        return JSON.stringify({protocol_version: 4,
            capabilities: ['Ping', 'Windows', 'FocusWindow', 'WindowAction', 'Capabilities'],
            window_actions: ['focus', 'close', 'move', 'resize', 'maximize', 'unmaximize',
                'minimize', 'tile'],
            // Keys, not the object: the values are functions, and JSON.stringify
            // drops those silently — the handshake advertised "tile_sides":{} and
            // looked like the shell supported no sides at all.
            tile_sides: Object.keys(TILE_SIDES)});
    }

    WindowAction(request) {
        const r = JSON.parse(request);
        const allowed = ['focus', 'close', 'move', 'resize', 'maximize', 'unmaximize',
            'minimize', 'tile'];
        const refused = (code, reason) => JSON.stringify({accepted: false, code, reason});
        if (!allowed.includes(r.action) || typeof r.id !== 'string' || !r.app_id)
            return refused('CAPABILITY_UNAVAILABLE', 'Invalid window operation');
        const tracker = Shell.WindowTracker.get_default();
        const w = global.get_window_actors().map(a => a.meta_window)
            .find(w => w && `${w.get_stable_sequence()}` === r.id);
        if (!w || tracker.get_window_app(w)?.get_id() !== r.app_id)
            return refused('TARGET_NOT_FOUND', 'Window identity changed or closed');
        if (r.action === 'focus')
            return this.FocusWindow(r.id, r.app_id);
        if (r.action === 'close') w.delete(global.get_current_time());
        if (r.action === 'minimize') w.minimize();
        if (r.action === 'maximize') w.maximize();
        if (r.action === 'unmaximize') {
            // Maximize used to be one-way here, which made "split the screen" a
            // trap: a maximised window ignores move_resize_frame, so tiling had
            // to be able to undo it. Fullscreen is cleared for the same reason.
            if (w.is_maximized()) w.unmaximize();
            if (w.is_fullscreen()) w.unmake_fullscreen();
        }
        if (r.action === 'tile') {
            const rect = TILE_SIDES[r.side];
            if (!rect) return refused('NON_RETRYABLE', 'Unknown tile side');
            if (!w.allows_move() || !w.allows_resize())
                return refused('NON_RETRYABLE', 'Window refuses to be moved or resized');
            // Mutter has no public tile(): GNOME's own edge-tiling lives inside
            // windowManager.js and tiling-assistant exposes neither D-Bus nor an
            // API. So compute the rect ourselves from the monitor's work area —
            // work area, not monitor size, because the dock and panel are not
            // ours to cover.
            if (w.is_maximized()) w.unmaximize();
            if (w.is_fullscreen()) w.unmake_fullscreen();
            const a = w.get_work_area_for_monitor(w.get_monitor());
            const t = rect(a);
            w.move_resize_frame(false, t.x, t.y, t.width, t.height);
            return JSON.stringify({accepted: true, id: r.id, action: 'tile',
                side: r.side, expected: t});
        }
        if (r.action === 'move') {
            if (![r.x, r.y].every(v => Number.isInteger(v) && Math.abs(v) <= 32768))
                return refused('NON_RETRYABLE', 'Invalid position');
            w.move_frame(true, r.x, r.y);
        }
        if (r.action === 'resize') {
            if (![r.width, r.height].every(v => Number.isInteger(v) && v >= 64 && v <= 16384))
                return refused('NON_RETRYABLE', 'Invalid dimensions');
            const rect = w.get_frame_rect();
            w.move_resize_frame(true, rect.x, rect.y, r.width, r.height);
        }
        return JSON.stringify({accepted: true, id: r.id, action: r.action});
    }

    Windows() {
        let payload = {error: 'Desktop observation failed', shell: {build: this._shell.buildId()}};
        Log.guard('dbus Windows', () => {
            const tracker = Shell.WindowTracker.get_default();
            const focused = global.display.focus_window;
            const workspaces = global.workspace_manager;
            const windows = [];

            for (const actor of global.get_window_actors()) {
                const w = actor.meta_window;
                if (!w)
                    continue;
                // Skip the compositor's own furniture — a desktop-type window is
                // the wallpaper, and counting it as "a window is open" would make
                // every verification trivially true.
                const type = w.get_window_type();
                if (type === Meta.WindowType.DESKTOP || type === Meta.WindowType.DOCK)
                    continue;

                const app = tracker.get_window_app(w);
                const workspace = w.get_workspace();
                windows.push({
                    id: `${w.get_stable_sequence()}`,
                    title: w.get_title() ?? '',
                    wm_class: w.get_wm_class() ?? '',
                    app_id: app?.get_id() ?? '',
                    pid: w.get_pid() > 0 ? w.get_pid() : null,
                    focused: w === focused,
                    workspace: workspace ? workspace.index() : 0,
                    minimised: w.minimized === true,
                    maximized: typeof w.is_maximized === 'function' ? w.is_maximized() : (w.maximized_horizontally && w.maximized_vertically),
                    geometry: (() => { const r = w.get_frame_rect();
                        return {x: r.x, y: r.y, width: r.width, height: r.height}; })(),
                    // Geometry alone cannot be checked against anything: "the
                    // left half" is meaningless without knowing which monitor
                    // and how much of it the panel and dock have already taken.
                    // Sending the work area makes a tile verifiable by equality
                    // rather than by trusting that the shell did what it said.
                    monitor: w.get_monitor(),
                    work_area: (() => { const a = w.get_work_area_for_monitor(w.get_monitor());
                        return a ? {x: a.x, y: a.y, width: a.width, height: a.height} : null; })(),
                });
            }

            payload = {
                windows,
                workspace: workspaces?.get_active_workspace_index?.() ?? 0,
                shell: {build: this._shell.buildId()},
            };
        });
        return JSON.stringify(payload);
    }

    // Called by the audited open-app tool, separately from observation.
    FocusWindow(id, appId) {
        const tracker = Shell.WindowTracker.get_default();
        for (const actor of global.get_window_actors()) {
            const w = actor.meta_window;
            if (!w || `${w.get_stable_sequence()}` !== id)
                continue;
            if (!appId || tracker.get_window_app(w)?.get_id() !== appId)
                return JSON.stringify({accepted: false, reason: 'Window application identity changed'});
            if (w.minimized)
                w.unminimize();
            const timestamp = global.get_current_time();
            w.get_workspace()?.activate_with_focus(w, timestamp);
            w.activate(timestamp);
            return JSON.stringify({accepted: true, reason: 'Existing window activation requested'});
        }
        return JSON.stringify({accepted: false, reason: 'Observed window has closed'});
    }

    destroy() {
        Log.guard('dbus unexport', () => {
            this._impl?.unexport();
            if (this._owner)
                Gio.bus_unown_name(this._owner);
        });
        this._impl = null;
        this._owner = 0;
    }
}
