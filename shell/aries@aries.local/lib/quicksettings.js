/* ARIES Quick Settings — the system controls, as ARIES's own surface.
 *
 * THE PRODUCT IDENTITY PRINCIPLE, APPLIED
 * ---------------------------------------
 * The first version of this file added an ARIES tile beside GNOME's Wi-Fi,
 * audio and battery tiles. That is "Linux feature + ARIES add-on", and
 * `docs/PRODUCT_IDENTITY.md` rules it out: the user must not have to know that
 * volume is GNOME's and autonomy is ARIES's. So this panel is ARIES's, and it
 * covers the controls the brief lists — Wi-Fi, audio, Bluetooth, brightness,
 * power and Background Mode, autonomy, privacy — in one place with one language.
 *
 * WHAT THE PRINCIPLE DOES NOT LICENSE
 * -----------------------------------
 * Owning the *surface*, not reimplementing the *foundation*. Every control here
 * drives the real mechanism the rest of the system already uses:
 *
 *   audio        Gvc.MixerControl — the same PulseAudio/PipeWire mixer
 *   brightness   org.gnome.SettingsDaemon.Power.Screen
 *   Wi-Fi        org.freedesktop.NetworkManager, WirelessEnabled
 *   Bluetooth    org.gnome.SettingsDaemon.Rfkill, BluetoothAirplaneMode
 *   power        ARIES itself — /api/aries/power (Entry 013)
 *   autonomy     ARIES itself — the §20 settings service
 *
 * Rewriting a network stack because ARIES should "own" it would produce a worse
 * system and contradicts §3. The test is whether the user has to know, not who
 * wrote the code underneath.
 *
 * WHERE IT HANDS OFF, AND SAYS SO
 * -------------------------------
 * Joining a new Wi-Fi network needs a credentials dialog, enterprise
 * authentication, captive portals and a secret agent. ARIES does not reimplement
 * that; "Choose a network…" opens the system picker. Handing off visibly is
 * honest; pretending to own it and failing at WPA-Enterprise would not be.
 *
 * NOTHING SHOWS A NUMBER IT DOES NOT HAVE
 * ---------------------------------------
 * A tile whose service is unreachable says "unavailable" and why. It never shows
 * 0 % volume for a mixer that did not answer — the rule the health probes have
 * followed since Entry 003.
 */

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Gvc from 'gi://Gvc';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import * as Log from './log.js';

const SLIDER_STEP = 0.05;

/* ── system mechanisms, each behind a small honest wrapper ──────────────── */

class Brightness {
    constructor() {
        this._proxy = null;
        this.available = false;
        Log.guard('brightness proxy', () => {
            this._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, null,
                'org.gnome.SettingsDaemon.Power',
                '/org/gnome/SettingsDaemon/Power',
                'org.gnome.SettingsDaemon.Power.Screen', null);
            this.available = this._proxy.get_cached_property('Brightness') !== null;
        });
    }

    get value() {
        const v = this._proxy?.get_cached_property('Brightness')?.deep_unpack?.();
        return typeof v === 'number' && v >= 0 ? v / 100 : null;
    }

    set value(fraction) {
        Log.guard('set brightness', () => {
            this._proxy?.set_cached_property('Brightness',
                new GLib.Variant('i', Math.round(fraction * 100)));
            this._proxy?.call(
                'org.freedesktop.DBus.Properties.Set',
                new GLib.Variant('(ssv)', [
                    'org.gnome.SettingsDaemon.Power.Screen', 'Brightness',
                    new GLib.Variant('i', Math.round(fraction * 100)),
                ]), Gio.DBusCallFlags.NONE, -1, null, null);
        });
    }
}

class Rfkill {
    constructor() {
        this._proxy = null;
        Log.guard('rfkill proxy', () => {
            this._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, null,
                'org.gnome.SettingsDaemon.Rfkill',
                '/org/gnome/SettingsDaemon/Rfkill',
                'org.gnome.SettingsDaemon.Rfkill', null);
        });
    }

    _get(name) {
        return this._proxy?.get_cached_property(name)?.deep_unpack?.() ?? null;
    }

    get bluetoothPresent() {
        return this._get('BluetoothHasAirplaneMode') === true;
    }

    get bluetoothOn() {
        const mode = this._get('BluetoothAirplaneMode');
        return mode === null ? null : !mode;
    }

    setBluetooth(on) {
        Log.guard('set bluetooth', () => {
            this._proxy?.call('org.freedesktop.DBus.Properties.Set',
                new GLib.Variant('(ssv)', [
                    'org.gnome.SettingsDaemon.Rfkill', 'BluetoothAirplaneMode',
                    new GLib.Variant('b', !on),
                ]), Gio.DBusCallFlags.NONE, -1, null, null);
        });
    }
}

class Network {
    constructor() {
        this._proxy = null;
        Log.guard('network proxy', () => {
            this._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, null,
                'org.freedesktop.NetworkManager',
                '/org/freedesktop/NetworkManager',
                'org.freedesktop.NetworkManager', null);
        });
    }

    _get(name) {
        return this._proxy?.get_cached_property(name)?.deep_unpack?.() ?? null;
    }

    get available() {
        return this._proxy !== null;
    }

    get wirelessEnabled() {
        return this._get('WirelessEnabled');
    }

    get connectivity() {
        // NM_CONNECTIVITY: 1 none, 2 portal, 3 limited, 4 full
        switch (this._get('Connectivity')) {
        case 4: return 'connected';
        case 3: return 'limited';
        case 2: return 'sign-in needed';
        case 1: return 'no network';
        default: return 'unknown';
        }
    }

    setWireless(on) {
        Log.guard('set wireless', () => {
            this._proxy?.call('org.freedesktop.DBus.Properties.Set',
                new GLib.Variant('(ssv)', [
                    'org.freedesktop.NetworkManager', 'WirelessEnabled',
                    new GLib.Variant('b', on),
                ]), Gio.DBusCallFlags.NONE, -1, null, null);
        });
    }
}

class Audio {
    constructor() {
        this._control = null;
        Log.guard('audio mixer', () => {
            this._control = new Gvc.MixerControl({name: 'ARIES'});
            this._control.open();
        });
    }

    get sink() {
        return this._control?.get_default_sink?.() ?? null;
    }

    get volume() {
        const sink = this.sink;
        if (!sink || !this._control)
            return null;
        return sink.volume / this._control.get_vol_max_norm();
    }

    set volume(fraction) {
        Log.guard('set volume', () => {
            const sink = this.sink;
            if (!sink || !this._control)
                return;
            const max = this._control.get_vol_max_norm();
            sink.volume = Math.round(Math.max(0, Math.min(1, fraction)) * max);
            sink.push_volume();
        });
    }

    get muted() {
        return this.sink?.is_muted ?? null;
    }

    toggleMute() {
        const sink = this.sink;
        if (sink)
            sink.change_is_muted(!sink.is_muted);
    }
}

/* ── the panel ──────────────────────────────────────────────────────────── */

export class AriesQuickSettings {
    constructor(shell) {
        this._shell = shell;
        this._brightness = new Brightness();
        this._rfkill = new Rfkill();
        this._network = new Network();
        this._audio = new Audio();
        this._status = null;

        this._button = new PanelMenu.Button(0.5, 'ARIES Quick Settings');
        this._button.add_style_class_name('aries-panel-button');
        const icon = new St.Icon({
            icon_name: 'preferences-system-symbolic',
            style_class: 'system-status-icon',
        });
        this._button.add_child(icon);
        this._button.accessible_name = 'ARIES quick settings';

        this._build();
        this._button.menu.connect('open-state-changed', (menu, open) => {
            if (open)
                Log.guard('quick settings refresh', () => this._refresh());
        });
        Main.panel.addToStatusArea('aries-quick-settings', this._button, 2, 'right');
    }

    _build() {
        const menu = this._button.menu;

        this._sliders = {};
        for (const [key, label, icon, apply] of [
            ['volume', 'Volume', 'audio-volume-high-symbolic',
                v => {
                    this._audio.volume = v;
                }],
            ['brightness', 'Brightness', 'display-brightness-symbolic',
                v => {
                    this._brightness.value = v;
                }],
        ]) {
            const item = new PopupMenu.PopupBaseMenuItem({activate: false});
            const box = new St.BoxLayout({
                orientation: Clutter.Orientation.HORIZONTAL,
                x_expand: true, y_align: Clutter.ActorAlign.CENTER,
            });
            box.add_child(new St.Icon({icon_name: icon, style_class: 'popup-menu-icon'}));
            const value = new St.Label({
                text: '—', style_class: 'aries-card-meta',
                y_align: Clutter.ActorAlign.CENTER,
                style: 'margin-left: 10px; min-width: 56px;',
            });
            box.add_child(value);

            const minus = new St.Button({
                style_class: 'aries-dock-item aries-focusable', can_focus: true,
                child: new St.Icon({icon_name: 'list-remove-symbolic', icon_size: 14}),
            });
            const plus = new St.Button({
                style_class: 'aries-dock-item aries-focusable', can_focus: true,
                child: new St.Icon({icon_name: 'list-add-symbolic', icon_size: 14}),
            });
            minus.connect('clicked', Log.guarded(`${key}-`, () => {
                const current = this._sliders[key].current;
                if (current !== null)
                    apply(Math.max(0, current - SLIDER_STEP));
                this._refresh();
            }));
            plus.connect('clicked', Log.guarded(`${key}+`, () => {
                const current = this._sliders[key].current;
                if (current !== null)
                    apply(Math.min(1, current + SLIDER_STEP));
                this._refresh();
            }));
            box.add_child(minus);
            box.add_child(plus);
            item.add_child(box);
            item.accessible_name = label;
            menu.addMenuItem(item);
            this._sliders[key] = {label: value, current: null};
        }

        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        this._wifi = new PopupMenu.PopupSwitchMenuItem('Wi-Fi', false);
        this._wifi.connect('toggled', Log.guarded('wifi toggle',
            (item, state) => this._network.setWireless(state)));
        menu.addMenuItem(this._wifi);

        this._wifiDetail = new PopupMenu.PopupMenuItem('Choose a network…');
        this._wifiDetail.connect('activate', Log.guarded('wifi picker',
            () => this._shell.spawn(['gnome-control-center', 'wifi'])));
        menu.addMenuItem(this._wifiDetail);

        this._bluetooth = new PopupMenu.PopupSwitchMenuItem('Bluetooth', false);
        this._bluetooth.connect('toggled', Log.guarded('bluetooth toggle',
            (item, state) => this._rfkill.setBluetooth(state)));
        menu.addMenuItem(this._bluetooth);

        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // ── the half only ARIES has ─────────────────────────────────────────
        this._background = new PopupMenu.PopupSwitchMenuItem('Background Mode', false);
        this._background.connect('toggled', Log.guarded('background toggle', (item, state) => {
            this._shell.api.put('/api/aries/power', {background_mode: state})
                .then(result => {
                    if (!result.ok)
                        this._shell.notifyLocal('Background Mode', result.reason);
                });
        }));
        menu.addMenuItem(this._background);

        this._privacy = new PopupMenu.PopupSwitchMenuItem('Privacy mode', false);
        this._privacy.connect('toggled', Log.guarded('privacy toggle', (item, state) => {
            this._shell.api.put('/api/aries/settings/privacy.local_only', {value: state})
                .then(result => {
                    if (!result.ok)
                        this._shell.notifyLocal('Privacy mode', result.reason);
                });
        }));
        menu.addMenuItem(this._privacy);

        this._autonomy = new PopupMenu.PopupMenuItem('Autonomy: —', {reactive: false});
        menu.addMenuItem(this._autonomy);

        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const settings = new PopupMenu.PopupMenuItem('ARIES Settings');
        settings.connect('activate', Log.guarded('open settings',
            () => this._shell.openControlCentre('settings')));
        menu.addMenuItem(settings);
    }

    /** Fold in the latest ARIES status, so the ARIES half is never stale. */
    setStatus(status) {
        this._status = status;
        Log.guard('quick settings status', () => {
            if (!status) {
                this._autonomy.label.text = 'ARIES is not answering';
                return;
            }
            this._background.setToggleState(!!status.background_mode);
            this._autonomy.label.text =
                `Autonomy: ${status.autonomy ?? 'unknown'}` +
                (status.background_mode
                    ? status.inhibitor_held
                        ? '  ·  staying awake'
                        : '  ·  Background Mode on, no inhibitor held'
                    : '');
        });
    }

    _refresh() {
        const show = (key, fraction, unavailable) => {
            const slot = this._sliders[key];
            slot.current = fraction;
            slot.label.text = fraction === null
                ? unavailable
                : `${Math.round(fraction * 100)} %`;
        };
        show('volume', this._audio.volume, 'no mixer');
        show('brightness', this._brightness.value, 'no backlight');

        const wireless = this._network.wirelessEnabled;
        this._wifi.setToggleState(wireless === true);
        this._wifi.setSensitive(this._network.available);
        this._wifi.label.text = this._network.available
            ? `Wi-Fi · ${this._network.connectivity}`
            : 'Wi-Fi · NetworkManager unavailable';
        this._wifiDetail.setSensitive(this._network.available);

        const bluetooth = this._rfkill.bluetoothOn;
        this._bluetooth.setSensitive(bluetooth !== null);
        this._bluetooth.setToggleState(bluetooth === true);
        if (bluetooth === null)
            this._bluetooth.label.text = 'Bluetooth · no adapter';

        this.setStatus(this._status);
    }

    destroy() {
        Main.panel.statusArea['aries-quick-settings']?.destroy();
    }
}
