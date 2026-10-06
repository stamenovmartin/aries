"""Disposable real GTK control for end-to-end accessibility acceptance."""
import gi
gi.require_version('Gtk','4.0')
from gi.repository import Gtk, GLib
GLib.set_prgname('aries-gui-check')
app=Gtk.Application(application_id='org.aries.GUIAcceptance')
def activate(app):
    window=Gtk.ApplicationWindow(application=app,title='ARIES GUI acceptance',default_width=460,default_height=180)
    box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=16)
    for side in ('top','bottom','start','end'): getattr(box,'set_margin_'+side)(24)
    label=Gtk.Label(label='Ready for an independently verified action')
    button=Gtk.Button(label='Complete acceptance check')
    button.connect('clicked',lambda *_:label.set_label('Acceptance complete'))
    box.append(label);box.append(button);window.set_child(box);window.present()
    GLib.timeout_add_seconds(600,lambda: app.quit())
app.connect('activate',activate)
app.run(None)
