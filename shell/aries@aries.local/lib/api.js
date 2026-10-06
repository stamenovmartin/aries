/* The only way the shell talks to ARIES: HTTP, asynchronous, always.
 *
 * NOTHING HERE MAY BLOCK
 * ----------------------
 * This code runs on the thread that draws the desktop. A synchronous request —
 * `session.send_and_read()` — would freeze the pointer, the animations and
 * every window's redraw for as long as ARIES took to answer, and ARIES answers
 * some questions by reading sensors and some by running an automation. So there
 * is no synchronous path in this file at all, not even a "quick" one, because a
 * quick one is what gets reused later for a slow question.
 *
 * The performance requirement in the brief — "no blocking AI calls on the UI
 * thread, AI work must not freeze desktop interaction" — is satisfied here, once,
 * rather than remembered at each call site.
 *
 * ARIES BEING DOWN IS A NORMAL STATE
 * ----------------------------------
 * `aries-core.service` can be stopped, restarting, or broken, and the desktop
 * must stay usable throughout. Every request resolves to a result object rather
 * than throwing: `{ok: false, reason}` is data the panel renders as "ARIES is
 * not running", not an exception that takes a component down. The shell is a
 * window onto ARIES, and a window onto something absent should show the absence.
 *
 * STALENESS
 * ---------
 * Replies can arrive out of order and after the thing that asked for them is
 * gone. Each client carries a generation counter, bumped on destroy, and a
 * reply from a superseded generation is dropped — the same guard the Control
 * Centre uses for exactly the same reason.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Soup from 'gi://Soup';

import * as Log from './log.js';

const DEFAULT_BASE = 'http://127.0.0.1:8000';
const TIMEOUT_S = 8;

export class Api {
    constructor(base = null) {
        // One source of truth for where ARIES is. `request()` used the module
        // constant while `get base()` returned something else, so overriding the
        // address changed what the getter said and not where the requests went —
        // which is the same shape of bug as a status panel reporting its own
        // intentions. `ARIES_API` matches the Control Centre's override, so both
        // surfaces are pointed at a different ARIES the same way.
        this._base = base ?? GLib.getenv('ARIES_API') ?? DEFAULT_BASE;
        this._session = new Soup.Session({timeout: TIMEOUT_S, idle_timeout: 20});
        this._generation = 0;
        this._cancellable = new Gio.Cancellable();
    }

    destroy() {
        this._generation += 1;
        this._cancellable.cancel();
        try {
            this._session.abort();
        } catch (_) {
            // Aborting a session with nothing in flight is not an error worth
            // reporting during teardown.
        }
        this._session = null;
    }

    get base() {
        return this._base;
    }

    set base(value) {
        this._base = value || DEFAULT_BASE;
    }

    /**
     * One request. Never throws, never blocks.
     * Resolves to {ok, status, data} or {ok: false, reason, offline}.
     */
    request(method, path, body = null) {
        const generation = this._generation;
        return new Promise(resolve => {
            if (!this._session) {
                resolve({ok: false, reason: 'the shell is shutting down', offline: true});
                return;
            }
            let message;
            try {
                message = Soup.Message.new(method, `${this._base}${path}`);
                message.request_headers.append('Accept', 'application/json');
                if (body !== null) {
                    const payload = new TextEncoder().encode(JSON.stringify(body));
                    message.set_request_body_from_bytes(
                        'application/json', new GLib.Bytes(payload));
                }
            } catch (error) {
                resolve({ok: false, reason: `bad request: ${error.message}`});
                return;
            }

            this._session.send_and_read_async(
                message, GLib.PRIORITY_DEFAULT, this._cancellable,
                (session, result) => {
                    if (generation !== this._generation) {
                        resolve({ok: false, reason: 'superseded', stale: true});
                        return;
                    }
                    let bytes;
                    try {
                        bytes = session.send_and_read_finish(result);
                    } catch (error) {
                        // A refused connection is ARIES being stopped, which is
                        // a state to show rather than an error to report.
                        resolve({
                            ok: false,
                            offline: true,
                            reason: this._explain(error),
                        });
                        return;
                    }
                    const status = message.get_status();
                    const failed = status < 200 || status >= 300;
                    let data = null;
                    let unreadable = null;
                    try {
                        const text = new TextDecoder().decode(bytes.get_data() ?? new Uint8Array());
                        data = text ? JSON.parse(text) : null;
                    } catch (error) {
                        unreadable = error.message;
                    }

                    if (failed) {
                        // The STATUS is the news here. A 500 whose body is an
                        // HTML error page is not an "unreadable reply" — it is a
                        // server error, and saying the reply could not be parsed
                        // sends the reader looking in the wrong place. ARIES's
                        // own `detail` is preferred when there is one.
                        resolve({
                            ok: false, status, data,
                            reason: data?.detail ?? `ARIES answered ${status}`,
                        });
                        return;
                    }
                    if (unreadable !== null) {
                        resolve({ok: false, status, reason: `unreadable reply: ${unreadable}`});
                        return;
                    }
                    resolve({ok: true, status, data});
                });
        });
    }

    _explain(error) {
        const text = error?.message ?? String(error);
        if (/refused|Could not connect|connect/i.test(text))
            return 'ARIES is not running';
        if (/timed? out/i.test(text))
            return 'ARIES did not answer in time';
        return text;
    }

    get(path) {
        return this.request('GET', path);
    }

    post(path, body) {
        return this.request('POST', path, body ?? {});
    }

    put(path, body) {
        return this.request('PUT', path, body ?? {});
    }

    /**
     * Poll `path` every `seconds`, handing each result to `onResult`.
     * The timer is returned so the caller can stop it; the callback is guarded,
     * so a rendering bug inside it cannot kill the timer or the session.
     */
    poll(path, seconds, onResult) {
        const tick = () => {
            this.get(path).then(Log.guarded('poll callback', onResult));
            return GLib.SOURCE_CONTINUE;
        };
        tick();
        return GLib.timeout_add_seconds(GLib.PRIORITY_LOW, Math.max(2, seconds), tick);
    }
}
