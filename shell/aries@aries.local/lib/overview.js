/* ARIES in the workspace overview.
 *
 * WHY THIS IS INTEGRATION AND NOT A REPLACEMENT
 * ---------------------------------------------
 * GNOME's overview is already a mission-control view: live window thumbnails,
 * a workspace strip, drag-between-workspaces, a search field, and the
 * accessibility and touchpad gestures that go with them. Rebuilding it would
 * produce something worse and call it coherence.
 *
 * What it is missing is ARIES. Type "brief" into the overview today and you get
 * files and applications; ARIES knows about your morning brief, your automations
 * and your settings, and the overview cannot see any of it. So ARIES registers
 * as a **search provider** — the mechanism GNOME provides for exactly this — and
 * the overview's own search becomes a way to reach ARIES.
 *
 * That is the product identity principle applied honestly: ARIES owns the
 * capability, GNOME's overview is the surface it is implemented on, and the user
 * does not have to know which is which. Compare the alternative — an "Ask ARIES"
 * button pinned to the corner of someone else's overview — which is exactly the
 * "GNOME feature with an ARIES add-on" shape the principle rules out.
 *
 * ONE ROUTER, NOW THREE FRONT ENDS
 * --------------------------------
 * This provider calls `POST /api/aries/command` — the same endpoint as the
 * Control Centre's palette and ARIES Search. No patterns are written here. A
 * capability added to `aries/shell/intents.py` appears in all three without any
 * of them changing.
 *
 * THE DOCK STEPS ASIDE
 * --------------------
 * The overview draws its own dash. Leaving the ARIES dock on top of it would put
 * two docks on screen at once, which is the same incoherence the dock already
 * avoids when Ubuntu's dock is enabled.
 */

import Gio from 'gi://Gio';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import * as Log from './log.js';

const MAX_RESULTS = 5;

/* GNOME hands a provider terms and a cancellable and expects ids back, then asks
 * separately for each id's presentation. ARIES returns whole results in one
 * reply, so they are held between the two calls, keyed by id. */
class AriesSearchProvider {
    constructor(shell) {
        this._shell = shell;
        this.id = 'aries';
        this.isRemoteProvider = false;
        this.canLaunchSearch = true;
        this._results = new Map();

        // The provider's heading in the overview comes from an appInfo. Using
        // the Control Centre's means the section reads "ARIES" with the ARIES
        // icon, and clicking the heading opens it — rather than an unlabelled
        // block of results from nowhere.
        this.appInfo = Gio.DesktopAppInfo.new('aries-control-centre.desktop');
    }

    getInitialResultSet(terms, cancellable) {
        const query = (terms ?? []).join(' ').trim();
        return new Promise(resolve => {
            if (query.length < 2) {
                resolve([]);
                return;
            }
            // GNOME cancels a search as soon as the user types again. Honour it:
            // a provider that keeps working after cancellation is why overview
            // search feels heavy.
            let cancelled = false;
            const handler = cancellable?.connect(() => {
                cancelled = true;
                resolve([]);
            });

            this._shell.api.post('/api/aries/command', {
                text: query, limit: MAX_RESULTS,
                // Applications and files are already provided by GNOME's own
                // providers. Offering them again would show every result twice.
                include: ['command', 'automation', 'setting'],
            }).then(result => {
                if (handler)
                    cancellable.disconnect(handler);
                if (cancelled)
                    return;
                if (!result.ok) {
                    // ARIES being down must not make the overview look broken:
                    // no results, no error banner, GNOME's own providers intact.
                    resolve([]);
                    return;
                }
                const ids = [];
                for (const item of result.data?.results ?? []) {
                    const id = `aries:${item.kind}:${item.id ?? item.title}`;
                    this._results.set(id, item);
                    ids.push(id);
                }
                resolve(ids);
            });
        });
    }

    getSubsearchResultSet(previous, terms, cancellable) {
        // Refined rather than filtered: "brief" → "brief shorter" is a different
        // intent, not a subset of the first one's results.
        return this.getInitialResultSet(terms, cancellable);
    }

    filterResults(results, max) {
        return results.slice(0, max);
    }

    getResultMetas(ids) {
        return new Promise(resolve => {
            resolve(ids.map(id => {
                const item = this._results.get(id) ?? {};
                return {
                    id,
                    name: item.title ?? 'ARIES',
                    description: item.detail ?? '',
                    createIcon: size => new St.Icon({
                        icon_name: iconFor(item),
                        icon_size: size,
                    }),
                };
            }));
        });
    }

    activateResult(id) {
        Log.guard('overview activate', () => {
            const item = this._results.get(id);
            if (!item)
                return;
            Main.overview.hide();
            this._shell.perform(item.action, item.title);
        });
    }

    launchSearch(terms) {
        Log.guard('overview launch search', () => {
            Main.overview.hide();
            this._shell.commandBar?.open();
            this._shell.commandBar?.setQuery((terms ?? []).join(' '));
        });
    }
}

function iconFor(item) {
    switch (item.kind) {
    case 'automation': return 'media-playback-start-symbolic';
    case 'setting': return 'preferences-system-symbolic';
    default: return 'system-search-symbolic';
    }
}

export class Overview {
    constructor(shell) {
        this._shell = shell;
        this._provider = null;
        this._ids = [];

        Log.guard('register search provider', () => {
            this._provider = new AriesSearchProvider(shell);
            Main.overview.searchController.addProvider(this._provider);
        });

        // The overview brings its own dash; two docks is not one environment.
        this._ids.push(Main.overview.connect('showing', Log.guarded('overview showing',
            () => this._shell.dock?.setVisible(false))));
        this._ids.push(Main.overview.connect('hiding', Log.guarded('overview hiding',
            () => this._shell.dock?.setVisible(true))));
    }

    destroy() {
        for (const id of this._ids)
            Log.guard('overview disconnect', () => Main.overview.disconnect(id));
        this._ids = [];
        if (this._provider) {
            Log.guard('unregister search provider',
                () => Main.overview.searchController.removeProvider(this._provider));
            this._provider = null;
        }
        // Leaving the dock hidden because the overview happened to be open when
        // the extension was disabled would be a teardown that changed the desktop.
        Log.guard('restore dock', () => this._shell.dock?.setVisible(true));
    }
}
