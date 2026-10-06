/* Super+Space, which GNOME had already given to somebody else.
 *
 * THE BUG
 * -------
 * `Super+Space` is GNOME's default binding for `switch-input-source` — cycling
 * keyboard layouts. Mutter will not give one accelerator to two actions, so
 * ARIES's binding registered and did nothing. On a machine with a single
 * keyboard layout the key appeared completely dead, which is a worse failure
 * than an error: nothing to search for, nothing in a log.
 *
 * THE RULE THIS FOLLOWS
 * ---------------------
 * Super+Space is the specified primary interaction surface of ARIES, so in an
 * ARIES session it should be ARIES's. But it belongs to the user's desktop, not
 * to us — the same shape of thing as the display timeout in Entry 013 and the
 * wallpaper in Entry 014. So it is **borrowed and returned**:
 *
 *   · the previous value is recorded before anything is written,
 *   · in ARIES's settings service rather than in this process, so a crash does
 *     not lose it,
 *   · and put back exactly on disable.
 *
 * WHAT IT WILL NOT DO
 * -------------------
 * Take a shortcut the user is actually using. If more than one input source is
 * configured, layout switching is something they do daily, and silently
 * removing it to make room for a command bar would be ARIES deciding it matters
 * more than the user's keyboard. In that case it leaves the binding alone and
 * says so — the command bar is still on the top bar menu and the overview.
 */

import Gio from 'gi://Gio';

import * as Log from './log.js';

const WM_KEYS = 'org.gnome.desktop.wm.keybindings';
const INPUT_SOURCES = 'org.gnome.desktop.input-sources';
const CONFLICTS = ['switch-input-source', 'switch-input-source-backward'];

export class Shortcut {
    constructor(shell) {
        this._shell = shell;
        this._wm = Log.guard('wm keybindings', () => new Gio.Settings({schema_id: WM_KEYS}));
        this._taken = null;
    }

    /** How many keyboard layouts the user actually has. */
    _inputSourceCount() {
        return Log.guard('input sources', () => {
            const sources = new Gio.Settings({schema_id: INPUT_SOURCES}).get_value('sources');
            return sources.n_children();
        }, 0) ?? 0;
    }

    /**
     * Make `accelerator` available, if that can be done without taking something
     * the user needs. Returns a sentence about what happened, or null if there
     * was nothing to do.
     */
    claim(accelerator) {
        if (!this._wm || !accelerator)
            return null;

        const clashes = CONFLICTS.filter(key =>
            (this._wm.get_strv(key) ?? []).includes(accelerator));
        if (clashes.length === 0)
            return null;

        if (this._inputSourceCount() > 1) {
            const message =
                `${accelerator} is used for switching keyboard layouts, and you have ` +
                'more than one. ARIES has left it alone — open ARIES Search from the ' +
                'top bar, or change shell.command_shortcut in Settings.';
            Log.warn(message);
            return message;
        }

        // Record before writing, in ARIES rather than in memory.
        const previous = {};
        for (const key of clashes)
            previous[key] = this._wm.get_strv(key);
        this._remember(previous);

        for (const key of clashes) {
            this._wm.set_strv(key,
                previous[key].filter(binding => binding !== accelerator));
        }
        this._taken = clashes;
        Log.log(`took ${accelerator} from ${clashes.join(', ')}`);
        return null;
    }

    _remember(previous) {
        const shell = this._shell;
        if (shell.config.restore_shortcut)
            return;                                  // already borrowed; do not re-record
        const payload = JSON.stringify(previous);
        shell.api.put('/api/aries/settings/shell.restore_shortcut', {value: payload})
            .then(result => {
                if (result.ok)
                    shell.config.restore_shortcut = payload;
                else
                    Log.warn(`could not record the previous shortcut: ${result.reason}`);
            });
    }

    /** Put back whatever was there before ARIES took it. */
    release() {
        const recorded = this._shell.config?.restore_shortcut;
        if (!recorded || !this._wm)
            return;
        Log.guard('restore shortcut', () => {
            const previous = JSON.parse(recorded);
            for (const [key, value] of Object.entries(previous))
                this._wm.set_strv(key, value);
            this._shell.api?.put('/api/aries/settings/shell.restore_shortcut', {value: ''});
            this._shell.config.restore_shortcut = '';
            Log.log('gave the shortcut back');
        });
    }

    destroy() {
        this.release();
        this._wm = null;
    }
}
