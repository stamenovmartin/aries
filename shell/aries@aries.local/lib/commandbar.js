/* The universal command bar. Super+Space.
 *
 * ONE ROUTER, TWO FRONT ENDS
 * --------------------------
 * Nothing here decides what a typed phrase means. The text goes to
 * `POST /api/aries/command` and comes back as *actions* — `{kind: 'navigate',
 * section: 'news'}`, `{kind: 'run_automation', automation_id: '…'}` — and this
 * file's entire job is to draw them and carry out the ones a shell can carry
 * out. The Control Centre's palette calls the same endpoint.
 *
 * That is the brief's "do not duplicate business logic in the shell", taken
 * literally: the patterns that recognise "scan for news" exist once, in Python,
 * and if they lived here as well the two command bars would diverge the first
 * time either was improved.
 *
 * WHAT THE SHELL CONTRIBUTES
 * --------------------------
 * Applications and windows, because those are the only things the shell knows
 * that ARIES does not. `Shell.AppSystem` already indexes every .desktop file;
 * asking ARIES to keep a second index would be duplication pointing the other
 * way. Files are NOT here — `privacy.excluded_paths` is ARIES policy, and a
 * shell that walked the filesystem itself would be a second implementation of a
 * privacy rule.
 *
 * TYPING MUST NEVER WAIT FOR THE NETWORK
 * --------------------------------------
 * Application results are computed locally and drawn on the keystroke. The ARIES
 * request is debounced and lands later, merging into the list. So the bar is
 * responsive at typing speed even when ARIES is slow, busy or stopped — and when
 * it is stopped, the bar still launches applications and says plainly that the
 * rest is unavailable.
 *
 * Replies can arrive out of order; each carries the query generation that asked
 * for it, and a late reply for an older query is dropped rather than repainting
 * the list with stale results.
 */

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import GObject from 'gi://GObject';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import * as Log from './log.js';

const DEBOUNCE_MS = 90;
const MAX_ROWS = 9;

const KIND_LABEL = {
    command: 'ARIES',
    automation: 'run',
    setting: 'setting',
    file: 'file',
    app: 'app',
    window: 'window',
};

const Row = GObject.registerClass(
class Row extends St.Button {
    _init(result) {
        super._init({
            style_class: 'aries-command-row aries-focusable',
            can_focus: true,
            x_expand: true,
            reactive: true,
            track_hover: true,
        });
        this.result = result;

        const box = new St.BoxLayout({
            orientation: Clutter.Orientation.HORIZONTAL,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });

        const icon = new St.Icon({
            icon_size: 22,
            y_align: Clutter.ActorAlign.CENTER,
            style_class: 'aries-dim',
        });
        if (result.gicon)
            icon.gicon = result.gicon;
        else
            icon.icon_name = iconFor(result);
        box.add_child(icon);

        const text = new St.BoxLayout({
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
            style: 'margin-left: 12px;',
        });
        const title = new St.Label({text: result.title, style_class: 'aries-command-title'});
        title.clutter_text.ellipsize = 3;                      // PANGO_ELLIPSIZE_END
        text.add_child(title);
        if (result.detail) {
            const detail = new St.Label({
                text: result.detail, style_class: 'aries-command-detail',
            });
            detail.clutter_text.ellipsize = 3;
            text.add_child(detail);
        }
        box.add_child(text);

        const kind = new St.Label({
            text: KIND_LABEL[result.kind] ?? result.kind,
            style_class: 'aries-command-kind',
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(kind);

        this.set_child(box);
        this.accessible_name = `${result.title}. ${result.detail ?? ''}`;
    }
});

function iconFor(result) {
    switch (result.kind) {
    case 'automation': return 'media-playback-start-symbolic';
    case 'setting': return 'preferences-system-symbolic';
    case 'file': return result.action?.is_dir ? 'folder-symbolic' : 'text-x-generic-symbolic';
    case 'window': return 'focus-windows-symbolic';
    default: return 'system-search-symbolic';
    }
}

export class CommandBar {
    constructor(shell) {
        this._shell = shell;
        this._generation = 0;
        this._debounceId = 0;
        this._grab = null;
        this._rows = [];
        this._selected = 0;
        this._build();
    }

    _build() {
        this._container = new St.BoxLayout({
            style_class: 'aries-command aries-raised',
            orientation: Clutter.Orientation.VERTICAL,
            visible: false,
            reactive: true,
        });
        this._container.accessible_name = 'ARIES command bar';

        this._entry = new St.Entry({
            style_class: 'aries-command-entry',
            hint_text: 'What would you like ARIES to do?',
            can_focus: true,
            x_expand: true,
        });
        this._entry.clutter_text.connect('text-changed',
            Log.guarded('command typing', () => this._onTyped()));
        this._entry.clutter_text.connect('key-press-event',
            (actor, event) => this._onKey(event));
        this._container.add_child(this._entry);

        this._list = new St.BoxLayout({
            style_class: 'aries-command-list',
            orientation: Clutter.Orientation.VERTICAL,
            x_expand: true,
        });
        this._scroll = new St.ScrollView({
            style_class: 'aries-command-scroll',
            x_expand: true,
            y_expand: true,
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
        });
        this._scroll.set_child(this._list);
        this._container.add_child(this._scroll);

        this._footer = new St.Label({
            text: 'Enter to run · ↑↓ to choose · Esc to close',
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
        if (this.visible)
            return;
        Log.guard('command open', () => {
            this._position();
            this._container.visible = true;
            this._container.opacity = 0;
            this._container.ease({
                opacity: 255,
                duration: this._shell.motion(160),
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
            });

            this._grab = Main.pushModal(this._container, {
                actionMode: Shell.ActionMode.NORMAL,
            });
            this._entry.set_text('');
            this._entry.grab_key_focus();
            this._update('');
        });
    }

    close() {
        if (!this.visible)
            return;
        Log.guard('command close', () => {
            if (this._grab) {
                Main.popModal(this._grab);
                this._grab = null;
            }
            this._container.ease({
                opacity: 0,
                duration: this._shell.motion(90),
                mode: Clutter.AnimationMode.EASE_OUT_QUAD,
                onComplete: () => {
                    this._container.visible = false;
                },
            });
        });
    }

    /** Fill the field from outside — `aries search "…"`, or a test harness. */
    setQuery(text) {
        this._entry.set_text(text ?? '');
        this._entry.clutter_text.set_cursor_position(-1);
    }

    /* An actor added with `addChrome` is parented to `uiGroup`, which does not
     * lay its children out — the actor must set its own position AND its own
     * size. Setting only the position (and letting the height come from the
     * preferred size) left the container allocated at zero height, so every row
     * drew on top of the one before it and the whole panel sat in the corner.
     *
     * So size is computed from the content every time the content changes, and
     * clamped to a share of the monitor. Nothing here is a magic number that
     * happens to look right at one resolution.
     */
    /* Resize AFTER the new rows have been laid out, not in the same turn.
     *
     * `get_preferred_height()` called immediately after `add_child()` returns
     * the height the box had before the children were allocated. So the panel
     * was sized for the entry plus whatever rows existed when the user stopped
     * typing — and the results that arrived from ARIES a moment later drew
     * outside it, on the bare wallpaper, unreadable over whatever was behind.
     *
     * One idle turn is enough: by then Clutter has allocated, and the preferred
     * height is the real one.
     */
    _resizeSoon() {
        if (!this.visible)
            return;
        if (this._resizeId)
            GLib.source_remove(this._resizeId);
        this._resizeId = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
            this._resizeId = 0;
            Log.guard('command resize', () => this._position());
            return GLib.SOURCE_REMOVE;
        });
    }

    _position() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        const width = Math.min(680, Math.round(monitor.width * 0.6));
        const maxListHeight = Math.min(420, Math.round(monitor.height * 0.45));

        /* The height is ADDED UP, not asked for.
         *
         * `this._container.get_preferred_height()` does not account for a child
         * whose height was set explicitly — so the box reported the height it
         * would have wanted, the scroll view was taller than that, and the rows
         * drew outside the container's allocation: results on bare wallpaper,
         * below a panel that stopped after the first row. Deferring the call by
         * an idle turn changed nothing, because the number was not stale, it was
         * measuring the wrong thing.
         *
         * The parts are known, so they are summed. The chrome comes from the
         * theme node rather than a constant, so changing the padding in the
         * tokens cannot silently clip the last row.
         */
        const [, entryHeight] = this._entry.get_preferred_height(width);
        const [, footerHeight] = this._footer.get_preferred_height(width);
        const [, listNatural] = this._list.get_preferred_height(width);
        const scrollHeight = Math.max(0, Math.min(listNatural, maxListHeight));
        this._scroll.set_height(scrollHeight);

        const node = this._container.get_theme_node();
        const chrome = node.get_padding(St.Side.TOP) + node.get_padding(St.Side.BOTTOM) +
            node.get_border_width(St.Side.TOP) + node.get_border_width(St.Side.BOTTOM);

        const height = Math.min(
            entryHeight + scrollHeight + footerHeight + chrome,
            Math.round(monitor.height * 0.8));
        this._container.set_size(width, height);
        this._container.set_position(
            Math.round(monitor.x + (monitor.width - width) / 2),
            Math.round(monitor.y + monitor.height * 0.16));
    }

    _onKey(event) {
        const symbol = event.get_key_symbol();
        if (symbol === Clutter.KEY_Escape) {
            this.close();
            return Clutter.EVENT_STOP;
        }
        if (symbol === Clutter.KEY_Down || symbol === Clutter.KEY_Tab) {
            this._select(this._selected + 1);
            return Clutter.EVENT_STOP;
        }
        if (symbol === Clutter.KEY_Up || symbol === Clutter.KEY_ISO_Left_Tab) {
            this._select(this._selected - 1);
            return Clutter.EVENT_STOP;
        }
        if (symbol === Clutter.KEY_Return || symbol === Clutter.KEY_KP_Enter) {
            this._activate();
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _onTyped() {
        const text = this._entry.get_text();
        // Applications are drawn immediately: typing must never wait for HTTP.
        this._update(text, this._apps(text));
        if (this._debounceId)
            GLib.source_remove(this._debounceId);
        this._debounceId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, DEBOUNCE_MS, () => {
            this._debounceId = 0;
            this._ask(text);
            return GLib.SOURCE_REMOVE;
        });
    }

    _apps(text) {
        const query = (text ?? '').trim().toLowerCase();
        if (query.length < 1)
            return [];
        const out = [];
        // These are Gio.DesktopAppInfo, not Shell.App. Only name, id, description
        // and icon are read here, all of which GAppInfo has; the Shell.App is
        // looked up at launch time in `perform()`, where it is actually needed.
        for (const app of Shell.AppSystem.get_default().get_installed()) {
            if (app.should_show && !app.should_show())
                continue;
            const name = app.get_name?.() ?? app.get_display_name?.() ?? '';
            const low = name.toLowerCase();
            if (!low.includes(query))
                continue;
            const score = low === query ? 1 : low.startsWith(query) ? 0.9 : 0.5;
            out.push({score, result: {
                kind: 'app', id: app.get_id(), title: name,
                detail: app.get_description?.() ?? '',
                gicon: app.get_icon?.(),
                action: {kind: 'launch_app', id: app.get_id()},
            }});
        }
        out.sort((a, b) => b.score - a.score);
        return out.slice(0, 5).map(o => o.result);
    }

    _ask(text) {
        const generation = ++this._generation;
        this._shell.api.post('/api/aries/command', {text, limit: 10}).then(result => {
            if (generation !== this._generation)
                return;                       // a newer keystroke has superseded this
            Log.guard('command results', () => {
                if (!result.ok) {
                    this._update(text, this._apps(text), {
                        note: `${result.reason} — applications still work`,
                    });
                    return;
                }
                this._update(text, this._apps(text), {
                    aries: result.data?.results ?? [],
                    note: result.data?.unmatched_reason ?? '',
                    suggestions: result.data?.suggestions ?? [],
                });
            });
        });
    }

    _update(text, apps = [], extra = {}) {
        const results = [...apps, ...(extra.aries ?? [])].slice(0, MAX_ROWS);
        this._list.destroy_all_children();
        this._rows = [];

        if (results.length === 0) {
            const empty = new St.Label({
                style_class: 'aries-empty',
                text: extra.note || (text.trim()
                    ? 'Nothing matches yet.'
                    : 'Type to search applications, files, settings and everything ARIES can do.'),
            });
            empty.clutter_text.line_wrap = true;
            this._list.add_child(empty);
            if (extra.suggestions?.length) {
                for (const suggestion of extra.suggestions.slice(0, 3)) {
                    const row = new Row({
                        kind: 'command', title: suggestion, detail: 'try this',
                        action: {kind: 'fill', text: suggestion},
                    });
                    row.connect('clicked', () => {
                        this._entry.set_text(suggestion);
                    });
                    this._list.add_child(row);
                    this._rows.push(row);
                }
            }
            this._footer.text = extra.note ? 'Esc to close' : 'Enter to run · Esc to close';
            this._select(0);
            this._resizeSoon();
            return;
        }

        for (const result of results) {
            const row = new Row(result);
            row.connect('clicked', Log.guarded('command activate',
                () => this._run(result)));
            this._list.add_child(row);
            this._rows.push(row);
        }
        this._footer.text = extra.note
            ? extra.note
            : 'Enter to run · ↑↓ to choose · Esc to close';
        this._select(0);
        this._resizeSoon();
    }

    _select(index) {
        if (this._rows.length === 0) {
            this._selected = 0;
            return;
        }
        const wrapped = (index + this._rows.length) % this._rows.length;
        this._rows.forEach((row, i) => {
            if (i === wrapped)
                row.add_style_pseudo_class('selected');
            else
                row.remove_style_pseudo_class('selected');
        });
        this._selected = wrapped;
    }

    _activate() {
        const row = this._rows[this._selected];
        if (!row)
            return;
        if (row.result.action?.kind === 'fill') {
            this._entry.set_text(row.result.action.text);
            return;
        }
        this._run(row.result);
    }

    _run(result) {
        this.close();
        this._shell.perform(result.action, result.title);
    }

    destroy() {
        if (this._resizeId)
            GLib.source_remove(this._resizeId);
        if (this._debounceId)
            GLib.source_remove(this._debounceId);
        this._generation += 1;
        if (this._grab) {
            try {
                Main.popModal(this._grab);
            } catch (_) {
                // Popping a grab the shell has already dropped during teardown.
            }
            this._grab = null;
        }
        Main.layoutManager.removeChrome(this._container);
        this._container.destroy();
    }
}
