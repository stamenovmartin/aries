/* ARIES Notifications — one place for the system's messages and ARIES's own.
 *
 * THE SURFACE IS ARIES'S; THE MECHANISM IS THE DESKTOP'S
 * ------------------------------------------------------
 * The brief asks for a notification centre carrying ARIES decisions, ordinary
 * system notifications and automation results, grouped and prioritised. The
 * desktop already has a notification centre that every application on the
 * machine delivers into, with grouping, do-not-disturb, the lock screen and an
 * accessibility story.
 *
 * Building a second one would mean the user's messages arriving in two places
 * and having to learn which — which is precisely the split the product identity
 * principle exists to prevent. So ARIES becomes a *source* in that centre, with
 * its own identity, its own grouping and its own priorities, and the user has
 * one place to look. That is "ARIES capability implemented using Linux".
 *
 * PRIORITY IS ARIES'S JUDGEMENT, NOT THE SHELL'S
 * ----------------------------------------------
 * §26's notification policy already decided what deserves interrupting someone
 * for, including quiet hours and the repeat gate. This file does not re-decide
 * it: ARIES's own severity maps to the desktop's urgency, and a notification
 * ARIES held is never delivered here — it was held for a reason, and a shell
 * that showed it anyway would be overriding the policy from outside.
 *
 * DELIVER-ONCE
 * ------------
 * The poll returns the recent notifications every time, so the highest id
 * already delivered is remembered and only newer ones are raised. Without that,
 * every poll would re-notify everything and the centre would fill with
 * duplicates within a minute. The watermark starts at whatever is newest when
 * the shell starts, so enabling ARIES does not replay the day's history at you.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as MessageTray from 'resource:///org/gnome/shell/ui/messageTray.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import * as Log from './log.js';

const URGENCY = {
    ok: MessageTray.Urgency.LOW,
    info: MessageTray.Urgency.LOW,
    notice: MessageTray.Urgency.NORMAL,
    warning: MessageTray.Urgency.HIGH,
    critical: MessageTray.Urgency.CRITICAL,
};

export class Notifications {
    constructor(shell) {
        this._shell = shell;
        this._source = null;
        this._watermark = null;          // null = "we have not looked yet"
        this._pollId = 0;
    }

    start() {
        const seconds = Math.max(5, (this._shell.config.status_poll_seconds ?? 8) * 2);
        this._pollId = this._shell.api.poll(
            '/api/aries/notifications?limit=12', seconds,
            result => this._onPoll(result));
    }

    _ensureSource() {
        if (this._source)
            return this._source;
        this._source = new MessageTray.Source({
            title: 'ARIES',
            iconName: 'system-run-symbolic',
        });
        this._source.connect('destroy', () => {
            this._source = null;
        });
        Main.messageTray.add(this._source);
        return this._source;
    }

    _onPoll(result) {
        if (!result.ok)
            return;                       // ARIES being down is not a notification
        const rows = result.data?.notifications ?? [];
        if (rows.length === 0)
            return;

        const ids = rows.map(r => r.id).filter(Number.isFinite);
        const newest = ids.length ? Math.max(...ids) : 0;

        if (this._watermark === null) {
            // First poll: adopt the current high-water mark silently. Enabling
            // the shell must not replay everything that happened before it.
            this._watermark = newest;
            return;
        }

        const fresh = rows
            .filter(r => Number.isFinite(r.id) && r.id > this._watermark)
            // ARIES already decided what to deliver; held ones stay held.
            .filter(r => (r.disposition ?? 'delivered') === 'delivered')
            .sort((a, b) => a.id - b.id);

        this._watermark = Math.max(this._watermark, newest);
        for (const row of fresh)
            this._raise(row);
    }

    _raise(row) {
        Log.guard('raise notification', () => {
            const source = this._ensureSource();
            const severity = row.severity ?? 'info';
            const notification = new MessageTray.Notification({
                source,
                title: row.title ?? 'ARIES',
                body: row.body ?? row.summary ?? '',
                urgency: URGENCY[severity] ?? MessageTray.Urgency.NORMAL,
                isTransient: severity === 'ok' || severity === 'info',
                gicon: new Gio.ThemedIcon({name: this._icon(row)}),
            });
            notification.connect('activated', Log.guarded('notification activated', () => {
                this._shell.openControlCentre(this._section(row));
            }));
            source.addNotification(notification);
        });
    }

    _icon(row) {
        switch (row.severity) {
        case 'critical': return 'dialog-error-symbolic';
        case 'warning': return 'dialog-warning-symbolic';
        case 'notice': return 'dialog-information-symbolic';
        default: return 'system-run-symbolic';
        }
    }

    _section(row) {
        const source = (row.source ?? '').toLowerCase();
        if (source.includes('news'))
            return 'news';
        if (source.includes('health'))
            return 'system';
        if (source.includes('brief'))
            return 'brief';
        return 'home';
    }

    /** A message from the shell itself — a failed toggle, a refused action. */
    local(title, body) {
        Log.guard('local notification', () => {
            const source = this._ensureSource();
            source.addNotification(new MessageTray.Notification({
                source, title, body: body ?? '',
                urgency: MessageTray.Urgency.NORMAL,
                isTransient: true,
            }));
        });
    }

    destroy() {
        if (this._pollId)
            GLib.source_remove(this._pollId);
        this._pollId = 0;
        this._source?.destroy();
        this._source = null;
    }
}
