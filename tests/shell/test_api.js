/* The shell's HTTP layer, against an ARIES that misbehaves on purpose.
 *
 * `lib/api.js` imports Gio, GLib, Soup and `log.js` — and nothing from
 * `gnome-shell`. So it can be loaded and exercised in plain `gjs`, outside a
 * compositor, against a fake server that is slow, truncated, empty or absent on
 * demand. None of those states can be produced reliably by pointing at the real
 * ARIES, and all of them are states the desktop has to survive.
 *
 * This is the half of the shell that can be unit-tested. The half that draws is
 * tested in a nested GNOME Shell by `scripts/test-shell.sh`; nothing here claims
 * to have tested anything visual.
 *
 * Run:  ./scripts/test-shell-api.sh
 */

import GLib from 'gi://GLib';

import {Api} from '../../shell/aries@aries.local/lib/api.js';
import * as Log from '../../shell/aries@aries.local/lib/log.js';

const PORT = ARGV[0] ?? '8099';
let passed = 0;
let failed = 0;

function check(label, condition, detail = '') {
    if (condition) {
        print(`PASS  ${label}${detail ? `   ${detail}` : ''}`);
        passed += 1;
    } else {
        print(`FAIL  ${label}${detail ? `   ${detail}` : ''}`);
        failed += 1;
    }
}

/* Point the client at the fake ARIES. The constructor takes the base address
 * because ARIES already has that concept — the Control Centre honours
 * `ARIES_API` for the same reason — so nothing here is a seam that exists only
 * for the test.
 *
 * The first version of this file overrode `get base()` instead, and every
 * request still went to the real ARIES on :8000: `request()` was using a module
 * constant while the getter returned something else. Two sources of truth for
 * one address, found by a test that appeared to be testing something else. */
function fake() {
    return new Api(`http://127.0.0.1:${PORT}`);
}

const loop = new GLib.MainLoop(null, false);

async function run() {
    // ── a normal reply ──────────────────────────────────────────────────────
    {
        const api = fake();
        const result = await api.get('/ok');
        check('a good reply is ok', result.ok === true);
        check('and carries the parsed body', result.data?.state === 'RUNNING');
        check('with the status', result.status === 200);
        api.destroy();
    }

    // ── ARIES is not running ────────────────────────────────────────────────
    {
        const api = new Api('http://127.0.0.1:1');   // nothing can listen here
        const result = await api.get('/ok');
        check('a refused connection is not an exception', result.ok === false);
        check('it is flagged as offline, which is a state to show', result.offline === true);
        check('and explained in the user\'s language, not the socket\'s',
            result.reason === 'ARIES is not running', result.reason);
        api.destroy();
    }

    // ── the timeout path ────────────────────────────────────────────────────
    {
        const api = fake();
        const started = GLib.get_monotonic_time();
        const result = await api.get('/slow');
        const seconds = (GLib.get_monotonic_time() - started) / 1e6;
        check('a server that never answers does not hang the caller forever',
            result.ok === false, `gave up after ${seconds.toFixed(1)}s`);
        check('within the client timeout, not the server\'s', seconds < 20);
        check('and says so plainly', /did not answer in time|not running/.test(result.reason),
            result.reason);
        api.destroy();
    }

    // ── invalid and partial bodies ──────────────────────────────────────────
    {
        const api = fake();
        let result = await api.get('/garbage');
        check('a 200 that is not JSON is refused rather than parsed hopefully',
            result.ok === false);
        check('and named as what it is', result.reason.startsWith('unreadable reply'),
            result.reason);

        result = await api.get('/truncated');
        check('a truncated body is refused, not half-used', result.ok === false);
        check('with the same honest reason', result.reason.startsWith('unreadable reply'));

        result = await api.get('/empty');
        check('an empty body is ok with null data, which is different from broken',
            result.ok === true && result.data === null);
        api.destroy();
    }

    // ── error statuses ──────────────────────────────────────────────────────
    {
        const api = fake();
        let result = await api.get('/404');
        check('a 404 is not ok', result.ok === false);
        check('and prefers ARIES\'s own explanation to a status number',
            result.reason === 'no such thing', result.reason);
        check('while still reporting the status', result.status === 404);

        result = await api.get('/500');
        check('a 500 with no JSON detail still gives a usable reason',
            result.ok === false && result.reason === 'ARIES answered 500', result.reason);
        api.destroy();
    }

    // ── bodies survive the round trip ───────────────────────────────────────
    {
        const api = fake();
        const result = await api.post('/echo', {text: 'scan for news', limit: 10});
        check('a POST body reaches the server intact',
            result.ok && result.data?.received?.text === 'scan for news');
        check('including numbers, unquoted', result.data?.received?.limit === 10);
        const unicode = await api.post('/echo', {text: 'зошто мислиш така?'});
        check('and survives non-ASCII, which a byte-length header gets wrong',
            unicode.data?.received?.text === 'зошто мислиш така?');
        api.destroy();
    }

    // ── staleness and teardown ──────────────────────────────────────────────
    {
        const api = fake();
        const inFlight = api.get('/slow');
        api.destroy();                          // the user closed the bar
        const result = await inFlight;
        check('a reply arriving after destroy is not delivered to a dead widget',
            result.ok === false);
        check('and is marked stale or offline rather than looking like a failure '
              + 'the user should see',
            result.stale === true || result.offline === true, JSON.stringify(result));
    }
    {
        const api = fake();
        api.destroy();
        const result = await api.get('/ok');
        check('a request made after destroy resolves rather than throwing',
            result.ok === false);
        check('saying the shell is shutting down', /shutting down/.test(result.reason));
    }

    // ── containment ─────────────────────────────────────────────────────────
    {
        Log.state.failures = [];
        const value = Log.guard('deliberate', () => {
            throw new Error('boom');
        }, 'fallback');
        check('guard() swallows a throw and returns the fallback', value === 'fallback');
        check('and records it, so a contained failure is still visible',
            Log.state.failures.length === 1 && Log.state.failures[0].where === 'deliberate');

        const wrapped = Log.guarded('deliberate-callback', () => {
            throw new Error('boom');
        });
        wrapped();
        wrapped();
        check('guarded() protects every call, not only the first',
            Log.state.failures.length === 3);
    }

    print('');
    print(failed === 0 ? `ALL PASSED (${passed} checks)` : `FAILURES (${failed} of ${passed + failed})`);
    loop.quit();
}

run().catch(error => {
    print(`FAIL  the harness itself threw: ${error.message}`);
    print(error.stack ?? '');
    failed += 1;
    loop.quit();
});

loop.run();
imports.system.exit(failed === 0 ? 0 : 1);
