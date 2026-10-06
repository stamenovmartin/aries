"""Operator — ask ARIES to do something, and see what it could actually confirm.

WHAT THIS SCREEN IS FOR
-----------------------
Not a chat window. The interesting thing about the Operator is not that it
answers; it is that it distinguishes *what it did* from *what it could check*,
and this screen exists to put that distinction in front of a person rather than
in a JSON field.

So every result shows three things that are never merged: what the tool
reported, what ARIES looked at, and what it found. And the headline at the top
is whether ARIES can verify anything at all right now — outside the ARIES
session there is no window list, and a screen that did not say so would let
someone believe every result had been checked.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402
from aries_ui.page import Page  # noqa: E402

VERDICT = {
    "met": ("Verified", "ok"),
    "unmet": ("Not done", "critical"),
    "unverifiable": ("Could not check", "notice"),
}
OUTCOME = {
    "done": ("Done", "ok"),
    "failed": ("Not done", "critical"),
    "unconfirmed": ("Unconfirmed", "notice"),
    "proposed": ("Waiting for you", "notice"),
    "refused": ("Refused", "warning"),
}


class OperatorPage(Page):
    title = "Operator"
    icon = "system-run-symbolic"
    subtitle = "Ask ARIES to do something — and see what it could confirm"

    def __init__(self, app):
        super().__init__(app)
        self._last = None            # the most recent run, kept across reloads

    def fetch(self, client):
        return {"status": client.get("/api/aries/operator"),
                "history": client.get("/api/aries/operator/history", limit=15)}

    def render(self, data):
        status, history = data["status"], data["history"]
        box = widgets.page_box()
        box.append(self._headline(status))
        box.append(self._ask(status))
        if self._last:
            box.append(self._result(self._last))
        box.append(self._history(history))
        box.append(self._vocabulary(status))
        return widgets.scrolled(box)

    # ── can it act, and can it check? ───────────────────────────────────────
    def _headline(self, status) -> Gtk.Widget:
        model = status.get("model") or {}
        group = widgets.section("Right now")

        enabled = status.get("enabled")
        row = widgets.row(
            "Acting on this desktop" if enabled else "Not acting on this desktop",
            "ARIES may open applications, pages and screens" if enabled
            else "ARIES will plan and say what it would do, and do nothing")
        row.add_prefix(widgets.dot("ok" if enabled else "info"))
        group.add(row)

        can = status.get("can_verify")
        row = widgets.row(
            "Can see the desktop" if can else "Cannot see the desktop",
            f"{status.get('windows', 0)} windows — results can be checked against what is "
            f"on screen" if can else
            (status.get("cannot_verify_why") or "") +
            " — ARIES can still act, and will say 'could not check' rather than 'done'")
        row.add_prefix(widgets.dot("ok" if can else "notice"))
        group.add(row)

        gpu = model.get("gpu") or {}
        where = "on this machine" if model.get("location") == "local" else "wherever configured"
        row = widgets.row(
            f"Thinking {where}",
            f"{model.get('name')} · "
            + ("reachable" if model.get("reachable") else model.get("detail", "not reachable"))
            + (f" · {gpu.get('name')}" if gpu.get("available") else " · no GPU — this will be slow"))
        row.add_prefix(widgets.dot("ok" if model.get("has_model") else "warning"))
        group.add(row)
        return group

    # ── the request box ─────────────────────────────────────────────────────
    def _ask(self, status) -> Gtk.Widget:
        group = widgets.section(
            "Ask", "Plain words. ARIES uses an exact match where it has one and the "
                   "local model where it does not — and refuses rather than guessing.")
        entry = Adw.EntryRow(title="What would you like ARIES to do?")
        entry.set_show_apply_button(True)

        def _submit(widget, *_):
            text = (widget.get_text() or "").strip()
            if not text:
                return
            self._send(text, approve=False)

        entry.connect("apply", _submit)
        entry.connect("entry-activated", _submit)
        group.add(entry)

        note = widgets.row(
            "Plans the model made are shown first",
            "A guess is proposed and waits for you; an exact match runs. The interesting "
            "failure is not a model refusing — it is a model answering plausibly.")
        note.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        group.add(note)
        return group

    def _send(self, text: str, *, approve: bool) -> None:
        def _work(client):
            return client.post("/api/aries/operator",
                               {"request": text, "approve": approve})

        def _done(result):
            self._last = result

        self.act(_work, done="", on_ok=_done)

    # ── what happened ───────────────────────────────────────────────────────
    def _result(self, run) -> Gtk.Widget:
        label, severity = OUTCOME.get(run.get("outcome"), (run.get("outcome"), "info"))
        group = widgets.section(f"“{run.get('request', '')}”")

        head = widgets.row(label, run.get("summary") or "")
        head.add_prefix(widgets.dot(severity))
        head.add_suffix(widgets.tag(label, design.SEVERITY_CLASS.get(severity, "")))
        group.add(head)

        plan = run.get("plan") or {}
        if plan.get("steps"):
            origin = ("an exact match" if plan.get("source") == "router"
                      else f"the local model ({plan.get('model')})")
            group.add(widgets.row("Understood by", origin))

        if run.get("outcome") == "proposed":
            row = widgets.row("Do it", "carry out the plan above", activatable=True)
            row.add_prefix(Gtk.Image.new_from_icon_name("media-playback-start-symbolic"))
            row.connect("activated",
                        lambda *_: self._send(run.get("request", ""), approve=True))
            group.add(row)

        for step in run.get("steps") or []:
            group.add(self._step(step))

        if run.get("honesty_gap"):
            row = widgets.row(
                "The tool claimed success and the desktop disagrees",
                "This is the measurement ARIES exists to make, not an error message")
            row.add_prefix(widgets.dot("critical"))
            group.add(row)
        for alt in plan.get("alternatives") or []:
            group.add(widgets.row(alt.get("title") or "", alt.get("example") or ""))
        return group

    def _step(self, step) -> Adw.ExpanderRow:
        v = step.get("verification") or {}
        label, severity = VERDICT.get(v.get("verdict"), (v.get("verdict"), "info"))
        exp = Adw.ExpanderRow(title=label)
        exp.set_subtitle(v.get("found") or "")
        exp.add_prefix(widgets.dot(severity))
        exp.add_suffix(widgets.tag(v.get("grade") or "",
                                   design.SEVERITY_CLASS.get(severity, "")))

        exp.add_row(widgets.row(
            "The tool reported",
            ("it succeeded" if step.get("reported") else "it failed")
            + (f" — {step.get('report_detail')}" if step.get("report_detail") else "")))
        exp.add_row(widgets.row("ARIES checked", v.get("checked") or ""))
        exp.add_row(widgets.row("And found", v.get("found") or ""))
        exp.add_row(widgets.row(
            "How long", f"{step.get('seconds')}s, {step.get('observations')} look(s) at "
                        f"the desktop"))
        return exp

    # ── the record ──────────────────────────────────────────────────────────
    def _history(self, history) -> Gtk.Widget:
        counts = history.get("counts") or {}
        total = counts.get("total", 0)
        group = widgets.section(
            "What ARIES has been asked",
            f"{counts.get('verified_success', 0)} of {total} verified · "
            f"{counts.get('reported_success', 0)} reported success · "
            f"{counts.get('honesty_gap', 0)} where the desktop disagreed")

        if not total:
            group.add(widgets.row("Nothing yet", "Ask for something above"))
            return group

        for run in (history.get("runs") or [])[:12]:
            label, severity = OUTCOME.get(run.get("outcome"), (run.get("outcome"), "info"))
            row = widgets.row(run.get("request") or "",
                              f"{label} · {widgets.when(run.get('at'))}"
                              + (" · the desktop disagreed" if run.get("honesty_gap") else ""))
            row.add_prefix(widgets.dot("critical" if run.get("honesty_gap") else severity))
            group.add(row)
        return group

    def _vocabulary(self, status) -> Gtk.Widget:
        group = widgets.section(
            "What ARIES can be asked for",
            "Every one of these carries its own check, and the best evidence that check "
            "can ever produce. A goal ARIES cannot verify is a goal it will not take.")
        for goal in status.get("goals") or []:
            exp = Adw.ExpanderRow(title=goal["kind"].replace("_", " "))
            exp.set_subtitle(f"best evidence: {goal['ceiling']}")
            exp.add_row(widgets.row("Why not stronger", goal["why_ceiling"]))
            exp.add_row(widgets.row("Needs", ", ".join(goal["params"]) or "nothing"))
            group.add(exp)
        for grade in status.get("grades") or []:
            group.add(widgets.row(grade["grade"], grade["meaning"]))
        return group
