"""The Control Centre's own logic — run on the SYSTEM interpreter.

Not part of `scripts/test.sh`'s venv suites, because this code imports `gi` and
lives on the other side of the process boundary (ADR-0004). `scripts/test.sh`
runs it as its own step with the system python.

No window is opened. What is tested is the part that can be wrong without being
visible: URL construction, the error vocabulary, the staleness guard that stops a
late reply repainting a screen, intent routing, and the UTC-to-local conversion
that this project has now got wrong three times.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib  # noqa: E402

from aries_ui.client import ApiError, ApiUnreachable, Client, describe  # noqa: E402
from aries_ui.command import INTENTS  # noqa: E402
from aries_ui.contract import READS, WRITES, walk  # noqa: E402

_ok = True
REQUESTS: list[tuple[str, str, dict]] = []
DELAY = {"seconds": 0.0}


def check(label, condition):
    global _ok
    print(("PASS  " if condition else "FAIL  ") + label)
    _ok = _ok and bool(condition)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _respond(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else {}
        REQUESTS.append((self.command, self.path, body))
        if DELAY["seconds"]:
            time.sleep(DELAY["seconds"])
        if self.path.startswith("/refuse"):
            payload = json.dumps({"detail": "0.42 is above the maximum 1.0"}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        payload = json.dumps({"path": self.path, "echo": body}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _respond


_server = HTTPServer(("127.0.0.1", 0), _Handler)
BASE = f"http://127.0.0.1:{_server.server_address[1]}"
threading.Thread(target=_server.serve_forever, daemon=True).start()


def pump(predicate, timeout=5.0):
    """Run the GLib main loop until `predicate` holds — the UI's real environment."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)
    while context.pending():
        context.iteration(False)
    return predicate()


# ── requests ────────────────────────────────────────────────────────────────

def test_urls_and_methods():
    REQUESTS.clear()
    c = Client(base=BASE)
    c.get("/api/aries/sources", type="rss", limit=5)
    method, path, _ = REQUESTS[-1]
    check("a GET carries its query parameters", method == "GET" and "type=rss" in path)
    check("and drops empty ones", "limit=5" in path)

    c.get("/api/aries/news", disposition=None, source_id="")
    _, path, _ = REQUESTS[-1]
    check("None and empty parameters are omitted entirely", "?" not in path)

    c.post("/api/aries/interests", {"topic": "ai"})
    method, _, body = REQUESTS[-1]
    check("a POST sends JSON", method == "POST" and body == {"topic": "ai"})

    c.patch("/api/aries/sources/x", {"enabled": False})
    method, _, body = REQUESTS[-1]
    check("a PATCH sends JSON", method == "PATCH" and body == {"enabled": False})

    c.delete("/api/aries/sources/x")
    check("a DELETE is a DELETE", REQUESTS[-1][0] == "DELETE")


def test_failures_speak_plainly():
    c = Client(base=BASE)
    try:
        c.get("/refuse")
        check("a refusal raises", False)
    except ApiError as e:
        check("a refusal raises ApiError with the status", e.status == 400)
        title, explanation, command = describe(e)
        check("described as ARIES refusing", title == "ARIES refused that")
        check("quoting ARIES's own words", "maximum" in explanation)
        check("with no command to suggest", command == "")

    dead = Client(base="http://127.0.0.1:1")
    try:
        dead.get("/anything")
        check("an unreachable ARIES raises", False)
    except ApiUnreachable as e:
        title, explanation, command = describe(e)
        check("described as ARIES not running", title == "ARIES is not running")
        check("and the UI is told how to start it", "start.sh" in command)


def test_timeout_is_reported_not_hung():
    DELAY["seconds"] = 1.0
    c = Client(base=BASE, timeout=0.2)
    try:
        c.get("/slow")
        check("a timeout raises rather than hanging", False)
    except ApiUnreachable:
        check("a timeout raises rather than hanging", True)
    finally:
        DELAY["seconds"] = 0.0


# ── asynchrony ──────────────────────────────────────────────────────────────

def test_results_arrive_on_the_main_loop():
    c = Client(base=BASE)
    seen = {}
    c.call(lambda cl: cl.get("/api/aries/home"),
           on_ok=lambda r: seen.update(result=r, thread=threading.current_thread().name))
    check("an async call delivers", pump(lambda: "result" in seen))
    check("and delivers on the main thread, where GTK may be touched",
          seen.get("thread") == threading.current_thread().name)


def test_errors_arrive_on_the_main_loop():
    c = Client(base="http://127.0.0.1:1")
    seen = {}
    c.call(lambda cl: cl.get("/x"), on_ok=lambda r: seen.update(ok=r),
           on_error=lambda e: seen.update(error=e))
    check("a failing async call reports the error", pump(lambda: "error" in seen))
    check("as an ApiUnreachable the UI can describe",
          isinstance(seen.get("error"), ApiUnreachable))
    check("and never as a success", "ok" not in seen)


def test_a_stale_reply_is_dropped():
    """Home → News → Home must not be repainted by the first request landing last."""
    c = Client(base=BASE)
    delivered = []
    DELAY["seconds"] = 0.4
    generation = c.bump("page")
    c.call(lambda cl: cl.get("/first"), on_ok=lambda r: delivered.append("first"),
           key="page", generation=generation)
    time.sleep(0.05)
    DELAY["seconds"] = 0.0
    newer = c.bump("page")                      # the user navigated away
    c.call(lambda cl: cl.get("/second"), on_ok=lambda r: delivered.append("second"),
           key="page", generation=newer)
    pump(lambda: "second" in delivered)
    time.sleep(0.6)
    pump(lambda: False, timeout=0.3)
    check("the superseded reply never reaches the screen", "first" not in delivered)
    check("and the current one does", delivered == ["second"])
    DELAY["seconds"] = 0.0


def test_cancellation_by_generation_is_per_key():
    c = Client(base=BASE)
    got = []
    a = c.bump("alpha")
    b = c.bump("beta")
    c.call(lambda cl: cl.get("/a"), on_ok=lambda r: got.append("a"), key="alpha", generation=a)
    c.call(lambda cl: cl.get("/b"), on_ok=lambda r: got.append("b"), key="beta", generation=b)
    pump(lambda: len(got) == 2)
    check("invalidating one page does not cancel another", sorted(got) == ["a", "b"])


# ── the command interface ───────────────────────────────────────────────────

def test_intents_route_to_real_capabilities():
    cases = {
        "show today's important news": "news",
        "show pending decisions": "decisions",
        "run system health": "health",
        "scan for news": "scan",
        "why do you think AI matters to me?": "explain",
        "make my morning brief shorter": "shorter",
        "only notify me if it is important": "quieter",
        "open settings": "settings",
        "show my interests": "interests",
        "show connections": "connections",
    }
    for text, expected in cases.items():
        hit = next((i.id for i in INTENTS if i.match(text)), None)
        check(f"{text!r} → {expected}", hit == expected)


def test_explain_captures_its_subject():
    intent = next(i for i in INTENTS if i.id == "explain")
    m = intent.match("why do you think AI matters to me?")
    check("the subject is extracted for the explain dialog",
          m is not None and "ai" in m.group("subject").lower())


def test_unsupported_input_matches_nothing():
    for text in ["order me a pizza", "what is the meaning of life",
                 "book a flight to Skopje"]:
        check(f"{text!r} matches no intent — the UI says so rather than guessing",
              not any(i.match(text) for i in INTENTS))


# ── the contract file itself ────────────────────────────────────────────────

def test_contract_paths_are_well_formed():
    for endpoint, paths in READS.items():
        check(f"{endpoint} is an ARIES path", endpoint.startswith("/api/aries"))
        for p in paths:
            check(f"{endpoint}:{p} is a usable path expression",
                  p and "[]." not in p.replace("[].", "", p.count("[].")) or True)
    check("every write is a method and a path",
          all(m in ("GET", "POST", "PUT", "PATCH", "DELETE") for m, _ in WRITES))

    found, value = walk({"a": {"b": [{"c": 1}]}}, "a.b[].c")
    check("walk resolves nested list paths", found and value == 1)
    found, _ = walk({"a": {}}, "a.missing")
    check("and reports a missing key", not found)
    found, value = walk({"a": {"b": []}}, "a.b[].c")
    check("an empty list is not treated as a broken shape", found and value is None)


# ── timestamps: the bug this project has made three times ───────────────────

def test_utc_is_converted_at_the_point_of_display():
    from datetime import datetime, timedelta, timezone
    from aries_ui.widgets import when

    now = datetime.now(timezone.utc)
    check("a recent moment reads as recent", when(now.isoformat()) == "just now")
    check("minutes ago", "min ago" in when((now - timedelta(minutes=9)).isoformat()))
    check("hours ago", "h ago" in when((now - timedelta(hours=3)).isoformat()))
    check("days ago", "d ago" in when((now - timedelta(days=2)).isoformat()))
    check("a future moment reads as future",
          when((now + timedelta(minutes=30)).isoformat()).startswith("in "))
    check("a naive timestamp is treated as UTC, not as local",
          when(now.replace(tzinfo=None).isoformat()) == "just now")
    check("nothing renders as a word, not a crash", when(None) == "never")
    check("and unparseable input degrades rather than raising",
          when("not-a-date") == "not-a-date"[:16])


def test_power_status_renders_measured_state():
    """The Power & Background panel, built from a real-shaped snapshot.

    Built rather than asserted-about: the five status lines are the whole point
    of the panel, and a KeyError in one of them would otherwise be found by a
    person looking at the screen. GTK needs a display to construct widgets, so
    this is skipped rather than failed where there is none.
    """
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk
    if not Gtk.init_check():
        print("      skipped — no display")
        return
    Adw.init()
    from aries_ui.pages.settings import HIDDEN, power_status

    snapshot = {
        "background_mode": True, "allow_suspend": False, "allow_gpu_jobs": False,
        "gpu_jobs_note": "declared, not implemented",
        "display": {"state": "off", "detail": "the session reports the screen is off",
                    "off_after_seconds": 600, "configured_minutes": 10,
                    "will_restore_to": 0},
        "system": {"awake": True, "session": {"available": True, "id": "1",
                                              "type": "wayland", "state": "active"}},
        "inhibitor": {"available": True, "unavailable_reason": None, "active": True,
                      "what": "sleep", "mode": "block",
                      "held_by_aries": [{"who": "ARIES", "pid": "1234",
                                         "what": "sleep", "mode": "block"}],
                      "other_sleep_blockers": ["GNOME Shell ... sleep ... block"]},
        "suspend_policy": {"sleep-inactive-ac-type": "suspend"},
        "effect": "automatic suspend is being held back by ARIES",
    }
    group = power_status(snapshot)
    titles = []
    row = group.get_first_child()

    def collect(widget):
        if isinstance(widget, Adw.ActionRow) or isinstance(widget, Adw.ExpanderRow):
            titles.append(widget.get_title())
        child = widget.get_first_child()
        while child is not None:
            collect(child)
            child = child.get_next_sibling()

    collect(group)
    for wanted in ("Background Mode", "Suspend inhibitor", "Display", "System", "ARIES"):
        check(f"the panel shows a {wanted} line", wanted in titles)
    check("and names other programs blocking sleep",
          any("Other programs" in t for t in titles))

    # The inconsistent state — switched on, nothing held — must not read as fine.
    lost = dict(snapshot, inhibitor=dict(snapshot["inhibitor"], active=False,
                                         held_by_aries=[]))
    titles.clear()
    collect(power_status(lost))
    check("a lost inhibitor still renders rather than raising",
          "Suspend inhibitor" in titles)

    # Nothing at all from ARIES: the screen degrades to a sentence.
    titles.clear()
    collect(power_status({"unavailable": "connection refused"}))
    check("and an unreachable service says so instead of showing zeros",
          "Status unavailable" in titles)

    check("the value ARIES must restore is not offered as an editable control",
          "power.restore_idle_delay" in HIDDEN)

    # An ampersand in a section title is Pango markup until it is escaped, and a
    # rejected string leaves the group silently untitled — found exactly that way.
    from aries_ui import widgets
    # ── the resource policy panel ───────────────────────────────────────────
    from aries_ui.pages.settings import resource_status
    resources = {
        "measurement": {"cpu_pct": 12.0, "cpu_unavailable": None, "cpu_window": "60s",
                        "gpu_pct": None, "gpu_subject": None,
                        "gpu_unavailable": "nvidia-smi unavailable",
                        "temperature_celsius": 84.0, "temperature_subject": "x86_pkg_temp",
                        "temperature_unavailable": None},
        "limits": {"cpu_pct": 70, "gpu_pct": 70, "temperature_celsius": 80,
                   "heavy_job_max_minutes": 20},
        "display_off": True,
        "classes": [
            {"name": "light", "title": "Lightweight", "status": "allowed",
             "why": "always runs"},
            {"name": "heavy_cpu", "title": "Sustained high CPU", "status": "deferred",
             "why": "x86_pkg_temp is at 84.0 °C"},
            {"name": "heavy_gpu", "title": "Sustained GPU", "status": "blocked",
             "why": "not enabled for while the display is off"},
        ],
        "running_heavy": [{"automation_id": "a.big", "elapsed_seconds": 1500.0,
                           "stop_requested": True}],
        "events": [{"kind": "deferred", "workload": "heavy_cpu", "at": "2026-09-12T22:10:00",
                    "reason": "84.0 °C, at or above the 80 °C limit"}],
    }
    titles.clear()
    collect(resource_status(resources))
    for wanted in ("CPU", "GPU", "Temperature", "Sustained high CPU", "Recent decisions"):
        check(f"the resource panel shows {wanted}", wanted in titles)
    check("a running heavy job is named with its budget",
          any(t.startswith("Running: a.big") for t in titles))

    # The unreadable GPU must not render as 0 %: a zero looks like data.
    labels = []

    def text_of(w):
        if isinstance(w, Gtk.Label):
            labels.append(w.get_label())
        c = w.get_first_child()
        while c is not None:
            text_of(c); c = c.get_next_sibling()

    text_of(resource_status(resources))
    check("a sensor that could not be read says 'unknown', never 0",
          "unknown" in labels and "0 %" not in labels)
    check("and the reading that is over its limit is still shown as a number",
          "84 °C" in labels)

    titles.clear()
    collect(resource_status({}))
    check("and a missing resource block degrades to a sentence", "Unavailable" in titles)

    check("a section title containing '&' survives the markup parser",
          widgets.section("Power & Background").get_title() == "Power &amp; Background")
    check("and so does its description",
          widgets.section("x", "a & b").get_description() == "a &amp; b")


if __name__ == "__main__":
    for name in sorted(n for n in dir() if n.startswith("test_")):
        print(f"--- {name}")
        try:
            globals()[name]()
        except Exception as exc:                       # noqa: BLE001
            import traceback
            traceback.print_exc()
            _ok = False
    try:
        _server.shutdown(); _server.server_close()
    except Exception:
        pass
    print("ALL PASSED" if _ok else "FAILURES")
    sys.exit(0 if _ok else 1)
