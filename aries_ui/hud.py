"""Native command-deck components. Every number is supplied by observed data."""
import math
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from aries_ui import widgets
from aries_ui.page import Page


def label(text, css='', wrap=True):
    widget = Gtk.Label(label=str(text), xalign=0, wrap=wrap)
    widget.set_max_width_chars(58)
    if css:
        widget.add_css_class(css)
    return widget


def hero(kicker, title, detail, icon='view-grid-symbolic'):
    box = Gtk.Box(spacing=24)
    box.add_css_class('hud-hero')
    image = Gtk.Image.new_from_icon_name(icon)
    image.set_pixel_size(48)
    image.add_css_class('hud-accent')
    box.append(image)
    text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
    text.append(label(kicker.upper(), 'hud-kicker'))
    text.append(label(title, 'hud-title'))
    text.append(label(detail, 'hud-muted'))
    box.append(text)
    return box


def grid(columns=3):
    return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                       min_children_per_line=1, max_children_per_line=columns,
                       column_spacing=12, row_spacing=12)


def metric(title, value, detail='', fraction=None):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.add_css_class('hud-panel')
    box.append(label(title.upper(), 'hud-kicker'))
    box.append(label(value, 'hud-value'))
    if fraction is not None:
        bar = Gtk.ProgressBar(fraction=max(0, min(1, fraction)))
        box.append(bar)
    caption = label(detail, 'hud-muted')
    caption.set_max_width_chars(26)
    box.append(caption)
    return box


def portal(title, detail, icon, callback):
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    image = Gtk.Image.new_from_icon_name(icon)
    image.set_pixel_size(32)
    image.set_halign(Gtk.Align.START)
    content.append(image)
    content.append(label(title, 'heading'))
    content.append(label(detail, 'hud-muted'))
    button = Gtk.Button(child=content)
    button.add_css_class('hud-portal')
    button.connect('clicked', lambda *_: callback())
    return button


class LivePage(Page):
    """Poll only while visible; retain the viewport when a snapshot changes."""
    def __init__(self, app):
        super().__init__(app)
        self._live_timer = 0
        self.connect('map', self._start)
        self.connect('unmap', self._stop)

    def _start(self, *_):
        if not self._live_timer:
            self._live_timer = GLib.timeout_add_seconds(5, self._tick)

    def _stop(self, *_):
        if self._live_timer:
            GLib.source_remove(self._live_timer)
            self._live_timer = 0

    def _tick(self):
        self.reload(quiet=True)
        return GLib.SOURCE_CONTINUE

    def _on_ok(self, data):
        old = self._slot.get_first_child()
        position = old.get_vadjustment().get_value() if isinstance(old, Gtk.ScrolledWindow) else 0
        super()._on_ok(data)
        new = self._slot.get_first_child()
        if isinstance(new, Gtk.ScrolledWindow):
            def restore():
                new.get_vadjustment().set_value(position)
                return GLib.SOURCE_REMOVE
            GLib.idle_add(restore)


def readings_grid(probes):
    cards = grid(3)
    for probe in probes:
        for reading in probe.get('readings', []):
            if reading['metric'] not in {'cpu.load_per_core','memory.used_pct','disk.used_pct','gpu.utilization_pct','gpu.memory_used_pct','thermal.celsius','gpu.temp_celsius','gpu.util_pct','cpu.pressure','memory.pressure'}:
                continue
            value = reading.get('value')
            unit = reading.get('unit') or ''
            title = reading['metric'].replace('_',' ').replace('.', ' / ')
            detail = reading.get('subject') or ('1-minute load per core, not CPU usage' if reading['metric']=='cpu.load_per_core' else 'Measured on this machine')
            cards.append(metric(title, f'{value:g}{unit}' if isinstance(value,(int,float)) else 'Unavailable',
                                reading.get('unavailable') or detail,
                                fraction=value/100 if unit=='%' and isinstance(value,(int,float)) else None))
        if probe.get('unavailable'):
            cards.append(metric(probe.get('probe','Sensor'), 'Unavailable', probe['unavailable']))
    return cards


def reading(card, open_source, read_source=None):
    """A readable AI response; visual media is fetched and attributed by the core."""
    from gi.repository import Gdk
    import base64
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
    box.add_css_class('reader-sheet')
    box.append(label('ARIES / READING BRIEF', 'hud-kicker'))
    headline = label(card.get('title','Reading brief'), 'reader-title')
    headline.set_max_width_chars(38)
    box.append(headline)
    box.append(label(card.get('source','') + ' · AI-generated from ' + card.get('coverage','source material'), 'hud-muted'))
    if card.get('image_base64'):
        try:
            raw = base64.b64decode(card['image_base64'], validate=True)
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(raw))
            picture = Gtk.Picture.new_for_paintable(texture)
            picture.set_can_shrink(True)
            picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            picture.set_size_request(-1,260)
            box.append(picture)
            from urllib.parse import urlsplit
            box.append(label('Source image · ' + urlsplit(card.get('image_source','')).hostname, 'hud-muted'))
        except Exception:
            box.append(label('The source image could not be displayed.', 'hud-muted'))
    summary = label(card.get('text',''), 'reader-body')
    summary.set_selectable(True)
    box.append(summary)
    for index, point in enumerate(card.get('key_points',[]),1):
        box.append(label(f'{index:02d}   {point}', 'reader-point'))
    box.append(label(card.get('evidence',''), 'hud-muted'))
    if card.get('url'):
        box.append(widgets.button('Open original source ↗', open_source))
    if read_source:
        for source in card.get('source_links',[])[:12]:
            box.append(widgets.button(source['title'][:85]+' ↗', lambda u=source['url']:read_source(u)))
    return box
