"""A deliberately badly-behaved ARIES, for testing the shell's HTTP layer.

The shell must survive an ARIES that is slow, stopped, truncated or lying, and
none of those can be produced reliably by pointing at the real one. So this
serves each failure on its own path:

    /ok          a normal reply
    /slow        never answers — the timeout path
    /garbage     200, but the body is not JSON
    /truncated   200, valid JSON prefix that stops mid-object
    /empty       200 with no body at all
    /404, /500   error statuses, with and without a JSON detail
    /echo        returns what it was posted, to prove the body survives

Only loopback, only these paths, and it exits with the test.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass                                   # the test's output is the output

    def _send(self, status, body, content_type="application/json"):
        raw = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):                          # noqa: N802
        path = self.path.split("?")[0]
        if path == "/ok":
            self._send(200, json.dumps({"state": "RUNNING", "severity": "ok", "n": 1}))
        elif path == "/slow":
            time.sleep(30)                     # longer than any client timeout
            self._send(200, "{}")
        elif path == "/garbage":
            self._send(200, "<html>this is not json at all</html>")
        elif path == "/truncated":
            self._send(200, '{"results": [{"title": "half a re')
        elif path == "/empty":
            self._send(200, b"")
        elif path == "/404":
            self._send(404, json.dumps({"detail": "no such thing"}))
        elif path == "/500":
            self._send(500, "Internal Server Error", content_type="text/plain")
        else:
            self._send(404, json.dumps({"detail": "unknown path"}))

    def do_POST(self):                         # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if self.path == "/echo":
            try:
                parsed = json.loads(raw or b"{}")
            except ValueError:
                self._send(400, json.dumps({"detail": "the client sent bad JSON"}))
                return
            self._send(200, json.dumps({"received": parsed}))
        else:
            self.do_GET()

    def do_PUT(self):                          # noqa: N802
        self.do_POST()


def main():
    # Threading, not the single-threaded default: `/slow` sleeps for half a
    # minute, and on a serial server every later request queued behind it and
    # failed as a timeout — three tests appeared to be testing the timeout path
    # while testing the fixture.
    server = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("ready", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
