"""Render every Control Centre screen against real ARIES payloads.

WHY THIS RUNS IN A SEPARATE INTERPRETER
---------------------------------------
The Control Centre is a GTK4 process that cannot import ARIES, and the ARIES
virtual environment cannot import `gi` (ADR-0004). Neither half can test the
other in one process, which is exactly why `render()` had no test at all: the
contract suite proved the endpoints return the right keys, and then nobody
proved a screen could actually draw them.

So this half runs on the system interpreter and reads payloads captured from the
live API by the other half. The fixtures are real responses, not invented ones —
a screen that renders a hand-written dictionary and crashes on the real thing is
precisely the failure this is for.

Widgets are built without a display. GTK4 constructs and packs widgets fine with
no DISPLAY; only presenting a window needs one. That is enough: the bugs this
catches are missing keys, wrong types and bad markup, all of which throw during
construction.

    python3 tests/ui_render.py <fixture-dir>
"""
from __future__ import annotations

import json
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

Gtk.init_check()
Adw.init()

from aries_ui.pages import SECTIONS  # noqa: E402

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


class FixtureClient:
    """Serves captured responses. Query parameters are ignored deliberately —
    what is being tested is rendering, not routing, and a page that asks for an
    endpoint nobody captured should say so loudly rather than get an empty dict.
    """

    def __init__(self, fixtures: dict):
        self.fixtures = fixtures
        self.asked: list[str] = []

    def get(self, path, **params):
        self.asked.append(path)
        if path not in self.fixtures:
            raise KeyError(
                f"{path} was not captured — add it to aries_ui/contract.READS "
                f"so both halves know the screen depends on it")
        return self.fixtures[path]

    def post(self, path, body=None, **params):        # never called during render
        raise AssertionError(f"render() must not write: POST {path}")

    put = patch = delete = post

    def bump(self, key):
        return 1

    def call(self, work, on_ok=None, on_error=None, key=None, generation=None):
        raise AssertionError("render() must not start a request")


class StubApp:
    """Just enough app for a page to construct and draw."""

    def __init__(self, client):
        self.client = client
        self.toasts: list[str] = []

    def go(self, section):
        pass

    def toast(self, message):
        self.toasts.append(message)


def main(fixture_dir: str) -> int:
    fixtures = {}
    for name in os.listdir(fixture_dir):
        if name.endswith(".json"):
            with open(os.path.join(fixture_dir, name)) as fh:
                entry = json.load(fh)
            fixtures[entry["path"]] = entry["body"]
    check(f"captured {len(fixtures)} endpoint payload(s)", len(fixtures) > 0)

    for key, cls in SECTIONS:
        client = FixtureClient(fixtures)
        try:
            page = cls(StubApp(client))
        except Exception as exc:                       # noqa: BLE001
            traceback.print_exc()
            check(f"{key} constructs", False, f"{type(exc).__name__}: {exc}")
            continue
        check(f"{key} constructs", True)

        try:
            data = page.fetch(client)
        except Exception as exc:                       # noqa: BLE001
            check(f"{key} fetches what it declares", False, f"{type(exc).__name__}: {exc}")
            continue
        check(f"{key} fetches what it declares", True, ", ".join(client.asked))

        try:
            widget = page.render(data)
        except Exception as exc:                       # noqa: BLE001
            traceback.print_exc()
            check(f"{key} renders real ARIES data", False, f"{type(exc).__name__}: {exc}")
            continue
        check(f"{key} renders real ARIES data", isinstance(widget, Gtk.Widget),
              type(widget).__name__)

        # A screen that renders an empty widget tree is a blank page with no
        # error — the failure mode that looks like everything is fine.
        try:
            page._show(widget)
            drawn = page._slot.get_first_child() is not None
        except Exception as exc:                       # noqa: BLE001
            drawn = False
            check(f"{key} can be shown", False, f"{type(exc).__name__}: {exc}")
        else:
            check(f"{key} puts something on screen", drawn)

    print()
    if FAILURES:
        print(f"FAILURES: {len(FAILURES)}")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
