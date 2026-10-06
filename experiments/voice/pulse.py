"""The live signal behind the ARIES mark.

The mark in the top bar should move because something is actually happening, not
because a timer says so. Everything emitted here is measured: `level` is the
Silero probability for the 32 ms of audio that just went past, `phase` is which
part of the loop is running, and `confidence` is the calibrated routing
probability — the real one, not a self-report.

Why a D-Bus signal rather than the shell polling ARIES over HTTP, which is how it
learns everything else: the mark has to follow a voice, and the existing status
poll is seconds apart. A signal is push, costs the shell nothing while nobody is
speaking, and needs no new port or file to keep in sync.

Degrades to silence. If the session bus is unavailable the voice loop must keep
working — an animation that cannot be drawn is not a reason to stop listening.
"""
import os

BUS_NAME = 'mk.aries.Voice'
OBJECT_PATH = '/mk/aries/Voice'
INTERFACE = 'mk.aries.Voice'

IDLE, LISTENING, THINKING, ACTING, SETTLED, REFUSED = (
    'idle', 'listening', 'thinking', 'acting', 'settled', 'refused')


class Pulse:
    """Emits mk.aries.Voice.Pulse(level, phase, confidence). Never raises."""

    def __init__(self, enabled=True):
        self._conn = None
        self._msg = None
        self._last = None
        if not enabled or not os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
            return
        try:
            from jeepney import DBusAddress, new_signal
            from jeepney.io.blocking import open_dbus_connection
            self._conn = open_dbus_connection(bus='SESSION')
            self._addr = DBusAddress(OBJECT_PATH, bus_name=BUS_NAME, interface=INTERFACE)
            self._new_signal = new_signal
            # Claiming the name is what lets the shell match on sender, so a
            # second process cannot drive the mark by pretending to be this one.
            from jeepney import message_bus
            self._conn.send(message_bus.RequestName(BUS_NAME, 4))
        except Exception:
            self._conn = None

    def emit(self, level, phase, confidence=-1.0):
        """level 0..1, phase one of the constants, confidence -1 when unknown."""
        if self._conn is None:
            return
        # Skip frames that would redraw the same thing. At 31 frames a second
        # most of them are identical silence, and a signal nobody can see is
        # still a wakeup for the shell's main loop.
        key = (round(float(level), 2), phase, round(float(confidence), 2))
        if key == self._last:
            return
        self._last = key
        try:
            self._conn.send(self._new_signal(
                self._addr, 'Pulse', 'dsd',
                (float(level), str(phase), float(confidence))))
        except Exception:
            self._conn = None          # the bus went away; stop trying, keep listening

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
