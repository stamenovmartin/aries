/* The ARIES presence in the top bar.
 *
 * WHAT IT ADDS, AND WHAT IT DELIBERATELY DOES NOT REPLACE
 * ------------------------------------------------------
 * The brief lists workspace, ARIES status, time/date, network, audio, battery,
 * notifications and Control Centre access. GNOME's panel already provides five
 * of those, implemented against NetworkManager, PulseAudio, UPower and the
 * notification daemon, with menus that handle Wi-Fi authentication dialogs,
 * per-application volume and battery estimates.
 *
 * Rebuilding those would mean a worse network menu, a worse volume control and
 * a worse clock, in the name of coherence. That is the opposite of the goal:
 * "not Ubuntu with an AI control app" is about the desktop feeling like one
 * thing, not about ARIES owning every pixel. And the standing rule for this
 * whole system applies — do not duplicate logic that already exists and works.
 *
 * So ARIES adds what GNOME has no opinion about — its own status, the workspace
 * pills, and one route into everything ARIES knows — and restyles the rest to
 * the same language. The result reads as one bar rather than two.
 *
 * WHY THE SEVERITY COMES FROM THE SERVER
 * --------------------------------------
 * "Is ARIES all right?" is a judgement. If this file decided that a degraded
 * runtime plus two warnings is amber, the rule would exist twice and the panel
 * could contradict the window it opens. `/api/aries/shell/status` answers with a
 * severity from the one vocabulary; this file chooses a colour for it, which is
 * all a panel should do.
 */

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import * as Log from './log.js';
import {Pulse} from './pulse.js';

const SEVERITY_CLASS = {
    ok: 'aries-sev-ok',
    info: 'aries-sev-info',
    notice: 'aries-sev-notice',
    warning: 'aries-sev-warning',
    critical: 'aries-sev-critical',
};

export const AriesIndicator = GObject.registerClass(
class AriesIndicator extends PanelMenu.Button {
    _init(shell) {
        super._init(0.5, 'ARIES');
        this._shell = shell;
        this.add_style_class_name('aries-panel-button');

        const box = new St.BoxLayout({
            orientation: Clutter.Orientation.HORIZONTAL,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._dot = new St.Widget({
            style_class: 'aries-panel-dot aries-sev-info',
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._label = new St.Label({
            text: 'ARIES',
            style_class: 'aries-panel-label',
            y_align: Clutter.ActorAlign.CENTER,
        });
        box.add_child(this._dot);
        box.add_child(this._label);
        this.add_child(box);

        /* The dot also moves, when ARIES's voice loop is actually running.
         *
         * It is lent, not given: `pulse.js` draws around it and scales it from
         * measured audio, and the severity classes below stay the only thing
         * that decides its colour. It tears itself down with this actor and
         * hands the dot back untouched, so there is nothing to undo here and
         * nothing to forget to undo. */
        this._pulse = new Pulse(shell, this._dot);

        this.accessible_name = 'ARIES status';
        this._buildMenu();

        // Starts as "unknown", not as "fine". An indicator that shows green
        // before it has heard anything is lying for the length of its first
        // request, and the first request is exactly when ARIES might be down.
        this._render({ok: false, reason: 'asking ARIES…'});
    }

    _buildMenu() {
        this._summary = new PopupMenu.PopupMenuItem('Asking ARIES…', {
            reactive: false, style_class: 'aries-card-body',
        });
        this.menu.addMenuItem(this._summary);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._facts = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._facts.label.clutter_text.line_wrap = true;
        this.menu.addMenuItem(this._facts);
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._add('Command…  (Super+Space)', () => this._shell.commandBar?.toggle());
        this._add('Open Control Centre', () => this._shell.openControlCentre());
        this._add('Morning brief', () => this._shell.openControlCentre('brief'));
        this._add('This machine', () => this._shell.openControlCentre('system'));
        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._add('Run a health check now', () => {
            this._shell.act({kind: 'run_automation', automation_id: 'aries.health'},
                'System health');
        });
    }

    _add(label, onActivate) {
        const item = new PopupMenu.PopupMenuItem(label);
        item.connect('activate', Log.guarded(`menu:${label}`, onActivate));
        this.menu.addMenuItem(item);
        return item;
    }

    /** Called with the result of every status poll. Never throws. */
    update(result) {
        this._render(result);
    }

    _render(result) {
        const severity = result.ok ? (result.data?.severity ?? 'ok') : 'critical';
        for (const cls of Object.values(SEVERITY_CLASS))
            this._dot.remove_style_class_name(cls);
        this._dot.add_style_class_name(SEVERITY_CLASS[severity] ?? 'aries-sev-info');

        if (!result.ok) {
            this._label.text = 'ARIES';
            this._label.add_style_class_name('aries-dim');
            this._summary.label.text = result.reason ?? 'ARIES is not answering';
            this._facts.label.text =
                'The desktop keeps working without it.\nStart it with:  aries start';
            this.accessible_name = `ARIES: ${result.reason ?? 'not answering'}`;
            return;
        }

        this._label.remove_style_class_name('aries-dim');
        const s = result.data ?? {};
        const badges = [];
        if (s.decisions > 0)
            badges.push(`${s.decisions} to decide`);
        if (s.brief_ready)
            badges.push('brief');
        this._label.text = badges.length ? `ARIES · ${badges.join(' · ')}` : 'ARIES';

        this._summary.label.text = s.summary ?? 'running';
        const lines = [
            `${s.automations_enabled ?? 0} of ${s.automations_total ?? 0} automations enabled`,
            s.next_run_name ? `next: ${s.next_run_name} ${this._when(s.next_run)}` : 'nothing scheduled',
            `${s.notifications ?? 0} recent notifications`,
            s.health_findings ? `${s.health_findings} health finding(s)` : 'machine healthy',
            `autonomy: ${s.autonomy ?? 'unknown'}`,
        ];
        if (s.background_mode)
            lines.push(s.inhibitor_held ? 'Background Mode: on, holding the machine awake'
                : 'Background Mode: on, but no inhibitor is held');
        this._facts.label.text = lines.join('\n');
        this.accessible_name = `ARIES: ${s.summary ?? 'running'}`;
    }

    _when(iso) {
        if (!iso)
            return '';
        const then = Date.parse(iso);
        if (Number.isNaN(then))
            return '';
        const minutes = Math.round((then - Date.now()) / 60000);
        if (minutes <= 0)
            return 'due now';
        if (minutes < 60)
            return `in ${minutes} min`;
        return `in ${Math.round(minutes / 60)} h`;
    }
});

/* Workspace pills: which workspace you are on, as shape rather than as a number.
 *
 * GNOME's own panel shows workspaces only inside the overview. On a desktop
 * meant to feel like one environment, "where am I" should be answerable without
 * opening anything — so this is one of the few places ARIES genuinely adds
 * something the session does not have.
 */
export const WorkspacePills = GObject.registerClass(
class WorkspacePills extends PanelMenu.Button {
    _init() {
        super._init(0.0, 'Workspaces', true);   // no menu: clicking switches
        this.add_style_class_name('aries-panel-button');
        this._box = new St.BoxLayout({
            orientation: Clutter.Orientation.HORIZONTAL,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this.add_child(this._box);
        this.accessible_name = 'Workspaces';

        const manager = global.workspace_manager;
        this._ids = [
            manager.connect('active-workspace-changed', () => this._refresh()),
            manager.connect('notify::n-workspaces', () => this._refresh()),
        ];
        this._manager = manager;
        this._refresh();
    }

    _refresh() {
        Log.guard('workspace pills', () => {
            this._box.destroy_all_children();
            const manager = this._manager;
            const active = manager.get_active_workspace_index();
            for (let i = 0; i < manager.n_workspaces; i++) {
                const pill = new St.Widget({
                    style_class: i === active
                        ? 'aries-workspace-pill aries-workspace-pill-active'
                        : 'aries-workspace-pill',
                    y_align: Clutter.ActorAlign.CENTER,
                    reactive: true,
                    track_hover: true,
                });
                pill.connect('button-press-event', () => {
                    manager.get_workspace_by_index(i)?.activate(global.get_current_time());
                    return Clutter.EVENT_STOP;
                });
                this._box.add_child(pill);
            }
        });
    }

    destroy() {
        for (const id of this._ids ?? [])
            this._manager?.disconnect(id);
        this._ids = [];
        super.destroy();
    }
});

/** Add ARIES to the panel and restyle it. Returns a teardown function. */
export function install(shell) {
    const added = [];
    let pollId = 0;

    const indicator = new AriesIndicator(shell);
    Main.panel.addToStatusArea('aries-status', indicator, 0, 'right');
    added.push('aries-status');

    // NOT the workspace pills any more. GNOME 50's Activities button already
    // contains WorkspaceIndicators, so adding ours drew dots beside dots — a
    // duplicate that no nested test could see and that one look at the real
    // screen made obvious. GNOME's are styled by the ARIES stylesheet instead.

    const seconds = shell.config.status_poll_seconds ?? 8;
    pollId = shell.api.poll('/api/aries/shell/status', seconds, result => {
        indicator.update(result);
        shell.onStatus(result);
    });

    return {
        indicator,
        destroy() {
            if (pollId)
                GLib.source_remove(pollId);
            for (const role of added)
                Main.panel.statusArea[role]?.destroy();
        },
    };
}
