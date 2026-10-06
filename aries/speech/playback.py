"""The PipeWire end of the voice.

`pw-play` reading from a pipe, for two reasons. It is the same choice
aries/workspace/media.py made for wpctl — shell out to the tool that is already
on the machine rather than bind a library — and a pipe is what lets ARIES start
speaking before the whole answer exists. A temporary file cannot do that; it has
to be complete before it is opened.

Two kinds of thing get piped in. Local engines produce raw signed 16-bit mono
samples at a rate they state. The network engine produces MP3, which pw-play
decodes through libsndfile's MPEG-1/2 support — verified from stdin, not
assumed. `Sink(None)` is the second case, and the only difference it makes is
that nothing here knows how long the audio is until the player has finished it.

`pactl` does not exist on this machine. PipeWire's own tools do.
"""
import shutil
import subprocess

PLAYER = "pw-play"
# SPA object syntax, not key=value: pw-play parses -P as a property object and
# rejects anything else. The name is what shows up beside the stream in wpctl.
PROPERTIES = '{ media.name = "ARIES speech" }'
ENCODED_TIMEOUT = 180     # an upper bound for audio whose length is not known here


def available():
    return shutil.which(PLAYER) is not None


def _reason(stream):
    """The first line of what the player complained about, not its whole manual."""
    text = (stream.read() or b"").decode(errors="replace").strip() if stream else ""
    return text.splitlines()[0][:200] if text else ""


class Sink:
    """One utterance's worth of playback. Started empty, fed, then closed.

    Started before the first byte exists on purpose: connecting to PipeWire
    costs real milliseconds, and they are free if they overlap synthesis.
    """

    def __init__(self, sample_rate, *, latency="60ms", role="Notification"):
        self.sample_rate = sample_rate
        self.seconds = 0.0 if sample_rate else None   # None: the player knows, this does not
        self.cancelled = False
        shape = ["--raw", "--rate", str(sample_rate), "--channels", "1",
                 "--format", "s16", "--latency", latency] if sample_rate else []
        self._proc = subprocess.Popen(
            [PLAYER, *shape, "--media-role", role, "-P", PROPERTIES, "-"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def write(self, payload, seconds=0.0):
        """Hand audio to PipeWire. False once the sink can take no more."""
        if self.cancelled or self._proc.stdin is None:
            return False
        try:
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError):
            return False
        if self.seconds is not None:
            self.seconds += seconds
        return True

    def close(self, timeout=None):
        """Wait for the last sample to be heard. Returns (exit code, reason).

        The timeout is the audio's own duration plus slack rather than a fixed
        number: closing the pipe does not stop playback, PipeWire still has a
        buffer to drain, and a long reply legitimately takes long.
        """
        if self._proc.stdin is not None:
            try:
                self._proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        if timeout is None:
            timeout = self.seconds + 5 if self.seconds is not None else ENCODED_TIMEOUT
        try:
            self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.cancel()
            return None, "playback did not finish in the time its own audio needed"
        return self._proc.returncode, _reason(self._proc.stderr)

    def cancel(self):
        """Stop mid-word. This is what interrupting a person sounds like."""
        self.cancelled = True
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()

    def running(self):
        return self._proc.poll() is None
