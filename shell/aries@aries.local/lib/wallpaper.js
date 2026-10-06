/* The ARIES background, borrowed and returned.
 *
 * A wallpaper is the most personal setting on a desktop, so ARIES does not take
 * it because an extension was switched on. `shell.wallpaper` defaults to
 * `system`, which changes nothing at all.
 *
 * When the user does choose an ARIES background, the same discipline as Entry
 * 013's display timeout applies: **record what was there before writing.** The
 * previous value goes into `shell.restore_wallpaper` — in ARIES's settings
 * service, not in this process — so a crash does not lose it, and choosing
 * `system` again puts back exactly what was there rather than a guess at a
 * default.
 *
 * `aries` (rather than `aries-dark` or `aries-light`) sets both the light and
 * the dark keys, so the background follows the user's own light/dark preference
 * instead of being a second thing they have to switch by hand.
 */

import Gio from 'gi://Gio';

import * as Log from './log.js';

const SCHEMA = 'org.gnome.desktop.background';
const LIGHT_KEY = 'picture-uri';
const DARK_KEY = 'picture-uri-dark';

export class Wallpaper {
    constructor(shell) {
        this._shell = shell;
        this._settings = Log.guard('wallpaper settings',
            () => new Gio.Settings({schema_id: SCHEMA}));
        this._applied = null;
    }

    /** Called whenever ARIES's configuration arrives or changes. */
    apply(choice, base) {
        if (!this._settings || !choice || choice === this._applied)
            return;
        Log.guard('apply wallpaper', () => {
            if (choice === 'system') {
                this._restore();
                this._applied = choice;
                return;
            }
            this._remember();

            // Inside the extension, not beside the repository. `base` is the
            // extension's own directory, and the system copy lives in
            // /usr/local/share — where `share/backgrounds/` does not exist. The
            // wallpaper keys were set to a path with nothing behind it, which
            // GNOME answers by drawing the previous wallpaper: the setting
            // "worked", the log said so, and the desktop did not change.
            // An extension has to carry everything it references.
            const light = `file://${base}/backgrounds/aries-light.svg`;
            const dark = `file://${base}/backgrounds/aries-dark.svg`;
            const pick = {
                'aries': [light, dark],
                'aries-light': [light, light],
                'aries-dark': [dark, dark],
            }[choice];
            if (!pick)
                return;

            this._settings.set_string(LIGHT_KEY, pick[0]);
            this._settings.set_string(DARK_KEY, pick[1]);
            this._settings.set_string('picture-options', 'zoom');
            this._applied = choice;
            Log.log(`background set to ${choice}`);
        });
    }

    _remember() {
        // Only the FIRST time. Recording again after ARIES has already changed
        // it would overwrite the user's wallpaper with an ARIES one and call
        // that the thing to restore.
        const shell = this._shell;
        const existing = shell.config.restore_wallpaper;
        if (existing)
            return;
        const current = this._settings.get_string(LIGHT_KEY);
        const currentDark = this._settings.get_string(DARK_KEY);
        const payload = JSON.stringify({light: current, dark: currentDark});
        shell.api.put('/api/aries/settings/shell.restore_wallpaper', {value: payload})
            .then(result => {
                if (result.ok)
                    shell.config.restore_wallpaper = payload;
                else
                    Log.warn(`could not record the previous background: ${result.reason}`);
            });
    }

    _restore() {
        const recorded = this._shell.config.restore_wallpaper;
        if (!recorded)
            return;
        let previous;
        try {
            previous = JSON.parse(recorded);
        } catch (error) {
            Log.warn(`the recorded background is unreadable: ${error.message}`);
            return;
        }
        if (previous.light)
            this._settings.set_string(LIGHT_KEY, previous.light);
        if (previous.dark)
            this._settings.set_string(DARK_KEY, previous.dark);
        this._shell.api.put('/api/aries/settings/shell.restore_wallpaper', {value: ''});
        this._shell.config.restore_wallpaper = '';
        Log.log('background restored to what was there before ARIES');
    }

    destroy() {
        // Deliberately nothing. Disabling the extension does not undo a
        // background the user chose — that would be a teardown with an opinion.
        // `shell.wallpaper = system` is how you ask for it back.
        this._settings = null;
    }
}
