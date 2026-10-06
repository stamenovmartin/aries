/* Containment. The most important file in the extension.
 *
 * A GNOME Shell extension runs INSIDE gnome-shell's own process, and on Wayland
 * a shell that throws during startup cannot be restarted without logging out —
 * there is no Alt+F2 'r'. That single fact shapes everything here: an ARIES bug
 * must degrade ARIES, never the user's session, and the user must keep their
 * desktop even when nothing of ARIES works.
 *
 * So every entry point the shell calls into us — enable, disable, a timer, a
 * signal handler, an HTTP reply — goes through `guard()`. A component that
 * throws is logged, marked broken and left out; the rest of the shell carries
 * on; GNOME never sees the exception.
 *
 * This is the same discipline as the Control Centre's page rendering (Entry
 * 011), where a render bug shows an error card rather than a blank window. The
 * stakes here are just higher: there, the worst case was one blank screen.
 */

const PREFIX = '[ARIES]';

export const state = {
    failures: [],
};

export function log(message) {
    console.log(`${PREFIX} ${message}`);
}

export function warn(message) {
    console.warn(`${PREFIX} ${message}`);
}

export function fail(where, error) {
    const text = error?.message ?? String(error);
    state.failures.push({where, text, at: Date.now()});
    console.error(`${PREFIX} ${where}: ${text}`);
    if (error?.stack)
        console.error(`${PREFIX}   ${error.stack.split('\n').slice(0, 4).join(' | ')}`);
}

/** Run `fn`, and never let it throw past this point. Returns `fallback` on failure. */
export function guard(where, fn, fallback = null) {
    try {
        return fn();
    } catch (error) {
        fail(where, error);
        return fallback;
    }
}

/** Wrap a callback so it is guarded every time it is called, not only once. */
export function guarded(where, fn) {
    return (...args) => guard(where, () => fn(...args));
}
