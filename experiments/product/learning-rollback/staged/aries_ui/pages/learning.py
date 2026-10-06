"""Learning — the transparent interface.

Everything ARIES has concluded, why, and what is currently contested. The screen
is ordered by how much the user might want to intervene: pending reversals first
(ARIES is about to change its mind), then feedback awaiting an answer, then what
has settled.
"""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from aries_ui import design, widgets  # noqa: E402
from aries_ui.explain import ExplainDialog  # noqa: E402
from aries_ui.page import Page  # noqa: E402

CLASSIFICATION_SEVERITY = {
    "sustained": "critical", "fatigue": "warning", "contextual": "notice",
    "temporary": "notice", "noise": "info",
}


class LearningPage(Page):
    title = "Learning"
    icon = "emblem-synchronizing-symbolic"
    subtitle = "What ARIES concluded, and why"

    def fetch(self, client):
        return {
            "task_reviews": client.get("/api/aries/learning/task-reviews"),
            "reversals": client.get("/api/aries/learning/reversals"),
            "feedback": client.get("/api/aries/learning/feedback", limit=15),
            "preferences": client.get("/api/aries/learning/preferences"),
            "evidence": client.get("/api/aries/learning/evidence"),
            "controls": client.get("/api/aries/learning/controls"),
        }

    def render(self, data):
        box = widgets.page_box()
        rev = data["reversals"] or {}
        box.append(self._say())
        box.append(self._task_reviews(data.get("task_reviews", {})))

        pending = [r for r in rev.get("reversals", []) if r.get("status") == "pending"]
        if pending:
            box.append(self._pending(pending))

        unanswered = [f for f in (data["feedback"] or {}).get("feedback", [])
                      if f.get("ambiguous") and not f.get("answered")]
        if unanswered:
            box.append(self._questions(unanswered))

        contested = rev.get("contested") or []
        if contested:
            box.append(self._contested(contested))

        box.append(self._preferences(data["preferences"] or {}))
        box.append(self._learned_controls(data.get('controls') or {}))
        box.append(self._evidence(data["evidence"] or {}))
        box.append(self._feedback_history((data["feedback"] or {}).get("feedback", [])))
        box.append(self._applied([r for r in rev.get("reversals", [])
                                  if r.get("status") != "pending"]))
        return widgets.scrolled(box)

    def _learned_controls(self, data):
        group=widgets.section('Manage learned values',
            'Reset a learned value while keeping your explicit preferences. Future learning can infer a new value.')
        for item in data.get('items',[]):
            row=widgets.row(item['label'],f"Learned: {item['value']} · {item.get('scope') or 'Global'}")
            payload={'kind':item['kind'],'target_id':item['id'],'revision':item['revision']}
            row.add_suffix(widgets.button('Reset learned value',lambda p=payload:self.act(
                lambda c:c.post('/api/aries/learning/controls/reset',p),done='Learned value reset'),css='flat'))
            group.add(row)
        if any(data.get('truncated',{}).values()):
            group.add(widgets.row('More learned values exist', 'Showing the 50 most recent values of each kind.'))
        if not data.get('items'):
            group.add(widgets.row('No learned values to reset', 'Your explicit preferences are separate.'))
        for event in data.get('history',[])[:10]:
            row=widgets.row(event['label'],f"{event['action'].capitalize()} · {widgets.when(event.get('at'))}")
            if event.get('can_undo'):
                row.add_suffix(widgets.button('Undo reset',lambda eid=event['id']:self.act(
                    lambda c:c.post(f'/api/aries/learning/controls/{eid}/undo',{}),
                    done='Previous learned value restored'),css='flat'))
            group.add(row)
        return group

    def _task_reviews(self, data):
        counts = data.get('counts', {})
        group = widgets.section('Learning from completed tasks',
            f"{counts.get('useful', 0)} useful · {counts.get('needs_work', 0)} need correction. Your judgments are separate from execution checks.")
        for review in data.get('reviews', [])[:8]:
            row = widgets.row(review['episode']['request'][:140],
                              review['rating'].replace('_', ' ') + ' · ' + (review['comment'] or 'No additional correction'))
            row.add_suffix(widgets.button('Open task', lambda gid=review['goal_id']:self.app.open_goal(gid), css='flat'))
            row.add_suffix(widgets.button('Retire review', lambda fid=review['id']:self.act(
                lambda c:c.post(f'/api/aries/learning/feedback/{fid}/scope', {'scope':'current_result'}),
                done='Review retired; previous reviews remain historical'), css='flat'))
            group.add(row)
        versions = ('overlap-v1', 'focused-v2')
        active = data.get('retrieval_version', 'overlap-v1')
        selector = Adw.ComboRow(title='Which past corrections should ARIES use?',
            subtitle='Choose the baseline or candidate. You can return to the baseline at any time.',
            model=Gtk.StringList.new(['Baseline · word overlap', 'Candidate · focused overlap']))
        selector.set_selected(versions.index(active) if active in versions else 0)
        def change(row, _):
            row.set_sensitive(False)
            desired = versions[row.get_selected()]
            def done(_):
                self.app.toast('Experience retrieval version saved')
                self.reload(quiet=True)
            def failed(_):
                self.app.toast('Could not change retrieval version; reloading the saved value')
                self.reload(quiet=True)
            self.client.call(lambda c:c.put('/api/aries/settings/workspace.review_retrieval', {'value':desired}),
                             on_ok=done, on_error=failed)
        selector.connect('notify::selected', change)
        group.add(selector)
        group.add(widgets.button('Compare learning versions', lambda:self.act(
            lambda c:c.post('/api/aries/workspace', {'capability':'learning_eval', 'args':{}}),
            on_ok=lambda r:self.app.open_goal(r['id'], temporary=True)), css='suggested-action'))
        if not data.get('reviews'):
            group.add(widgets.row('No task reviews yet', 'Open a completed task and choose Useful or Needs correction.'))
        return group

    # ── tell ARIES something ────────────────────────────────────────────────
    def _say(self) -> Gtk.Widget:
        group = widgets.section("Tell ARIES something",
                                "Write corrections here. Explicit rules guide future plans; supported settings apply immediately. This does not retrain model weights.")
        self._standing = Gtk.CheckButton(label="Remember for future tasks")
        group.add(self._standing)
        row = Adw.EntryRow(title='e.g. "always keep briefs shorter"')
        send = widgets.button("Send", lambda: self._submit(row), css="suggested-action pill")
        row.add_suffix(send)
        row.connect("entry-activated", lambda *_: self._submit(row))
        group.add(row)
        return group

    def _submit(self, entry):
        text = entry.get_text().strip()
        if not text:
            return
        scope = "global" if self._standing.get_active() else None

        def _after(result):
            entry.set_text("")
            if result.get("ambiguous"):
                self._ask(result)
            elif result.get("applied"):
                action = result.get("action") or {}
                self.app.toast(f"{action.get('setting')} = {action.get('value')} "
                               f"({result.get('layer')} layer)")
            else:
                self.app.toast("Saved for future plans" if result.get("scope") == "global" else "Feedback recorded")

        self.act(lambda c: c.post("/api/aries/learning/feedback", {"text": text, **({"scope":scope} if scope else {})}),
                 on_ok=_after)

    def _ask(self, feedback):
        """ARIES asks rather than overgeneralising — the dialog is that question."""
        dialog = Adw.AlertDialog(heading="How far does that go?",
                                 body=feedback.get("question") or "")
        dialog.add_response("once", "Just this once")
        dialog.add_response("global", "From now on")
        dialog.add_response("cancel", "Leave it")
        dialog.set_response_appearance("global", Adw.ResponseAppearance.SUGGESTED)

        def _response(_d, response):
            if response == "cancel":
                return
            scope = "current_result" if response == "once" else "global"
            self.act(lambda c: c.post(
                f"/api/aries/learning/feedback/{feedback['id']}/scope", {"scope": scope}),
                done="Noted")

        dialog.connect("response", _response)
        dialog.present(self.app.get_active_window() or self.app.window)

    # ── sections ────────────────────────────────────────────────────────────
    def _pending(self, pending) -> Gtk.Widget:
        group = widgets.section(
            "About to change its mind",
            "a reversal is applied only after it holds across several passes")
        for r in pending:
            exp = Adw.ExpanderRow(
                title=f"{r['target']} — {r['established']} would become "
                      f"{r.get('proposed') if r.get('proposed') is not None else 'lower'}",
                subtitle=f"{r['confirmations']} of {r['required_confirmations']} confirmations")
            exp.add_prefix(widgets.dot("warning"))
            exp.add_row(widgets.row("Why", r.get("reason", "")))
            interval = r.get("interval") or {}
            exp.add_row(widgets.row(
                "Evidence",
                f"{interval.get('successes', 0)} of {interval.get('trials', 0)} · "
                f"interval [{interval.get('lower')}, {interval.get('upper')}] over "
                f"{r.get('window_days')} days"))
            exp.add_row(widgets.row("Policy", r.get("policy_version", "")))
            group.add(exp)
        return group

    def _questions(self, unanswered) -> Gtk.Widget:
        group = widgets.section("ARIES is asking",
                                "it will not guess how far a correction reaches")
        for f in unanswered:
            prefix = "Implementation · " if f.get("classification") == "implementation_note" else "You · "
            r = widgets.row(prefix + f'"{f["text"]}"', f.get("question") or "")
            r.add_prefix(widgets.dot("notice"))
            r.add_suffix(widgets.button("Answer", lambda x=f: self._ask(x), css="pill"))
            group.add(r)
        return group

    def _contested(self, contested) -> Gtk.Widget:
        group = widgets.section("Contested",
                                "the evidence disagrees with what ARIES believes")
        for c in contested:
            exp = Adw.ExpanderRow(title=c["target"],
                                  subtitle=c["classification"].replace("_", " "))
            exp.add_prefix(widgets.dot(CLASSIFICATION_SEVERITY.get(c["classification"], "info")))
            if c.get("believed") is not None:
                exp.add_suffix(widgets.tag(f"{c['believed']:.2f}", "aries-learned"))
            exp.add_row(widgets.row("Why", c.get("reason", "")))
            exp.add_row(widgets.row("Confidence", f"{c.get('confidence', 0):.0%}"))
            group.add(exp)
        return group

    def _preferences(self, prefs) -> Gtk.Widget:
        settings = [s for s in (prefs.get("settings") or []) if not s["key"].startswith("shell.restore_")]
        topics = prefs.get("topics") or []
        group = widgets.section("What ARIES believes", prefs.get("means", ""))
        if not settings and not topics:
            group.add(widgets.row("Nothing decided yet",
                                  "every setting is still at its shipped default"))
            return group
        for s in settings:
            r = widgets.row(s["key"], s.get("rationale") or s["source_label"])
            r.add_prefix(widgets.dot("ok" if s["explicit"] else "notice"))
            r.add_suffix(widgets.tag(str(s["value"]), "aries-mono"))
            r.add_suffix(widgets.provenance_tag(
                design.EXPLICIT if s["explicit"] else design.LEARNED))
            r.set_activatable(True)
            r.connect("activated", lambda _w, k=s["key"]: self._explain(k))
            group.add(r)
        return group

    def _evidence(self, evidence) -> Gtk.Widget:
        topics = evidence.get("topics") or []
        group = widgets.section(
            "Evidence",
            f"a weight may move once a topic has {evidence.get('minimum_observations', 10)} "
            f"delivered items")
        if not topics:
            group.add(widgets.row("Nothing delivered yet",
                                  "ARIES learns from what you actually see"))
            return group
        for t in topics[:12]:
            # The evidence endpoint nests the aggregate under `overall` — it is
            # sliced by time and by source since reversal detection, and the flat
            # shape this page first assumed belonged to the older, simpler one.
            overall = t.get("overall") or {}
            rate = overall.get("rate")
            r = widgets.row(
                t["topic"],
                f"{overall.get('engaged', 0)} of {overall.get('shown', 0)} opened · "
                + (f"{rate:.0%}" if rate is not None else "rate unknown")
                + f" · interval [{overall.get('lower')}, {overall.get('upper')}]"
                + (f" · trend {t['trend']}" if t.get("trend") not in (None, "insufficient") else ""))
            r.add_prefix(widgets.dot("ok" if t.get("decisive") else "info"))
            if not t.get("decisive"):
                r.add_suffix(widgets.tag("not enough yet", "aries-quiet"))
            group.add(r)
        return group

    def _feedback_history(self, feedback) -> Gtk.Widget:
        group = widgets.section("Feedback and implementation lessons", "Your rules and recorded fixes keep separate provenance. Neither implies model-weight training.")
        if not feedback:
            group.add(widgets.row("Nothing yet",
                                  "corrections you make here take effect immediately"))
            return group
        for f in [r for r in feedback if r.get("classification") != "task_review"][:10]:
            if f.get('classification') == 'implementation_note':
                title = f['text'].splitlines()[0].removeprefix('Problem: ')[:110]
                item = Adw.ExpanderRow(title=title, subtitle='Implementation lesson · ' + widgets.when(f.get('at')))
                item.set_use_markup(False)
                item.add_row(widgets.row('Change, evidence and limitations', f['text']))
                if f.get('scope') == 'global':
                    item.add_action(widgets.button('Retire', lambda fid=f['id']: self.act(
                        lambda c:c.post(f'/api/aries/learning/feedback/{fid}/scope', {'scope':'current_result'}),
                        done='Lesson retired; history retained'), css='flat'))
                group.add(item)
                continue
            prefix = "Implementation · " if f.get("classification") == "implementation_note" else "You · "
            r = widgets.row(prefix + f'"{f["text"]}"',
                            f"{f['classification'].replace('_', ' ')} · {f['scope']} · "
                            f"{widgets.when(f.get('at'))}")
            if f.get("ambiguous"):
                r.add_prefix(widgets.dot("notice"))
            elif f.get("applied"):
                r.add_prefix(widgets.dot("ok"))
            else:
                r.add_prefix(widgets.dot("info"))
            if f.get('scope') == 'global' and not f.get('applied'):
                r.add_suffix(widgets.button('Retire rule', lambda fid=f['id']: self.act(
                    lambda c:c.post(f'/api/aries/learning/feedback/{fid}/scope', {'scope':'current_result'}),
                    done='Rule retired; feedback history retained'), css='flat'))
            if f.get("action"):
                r.add_suffix(widgets.tag(f"{f['action']['setting']}", "aries-mono"))
            group.add(r)
        return group

    def _applied(self, resolved) -> Gtk.Widget:
        group = widgets.section("Resolved reversals")
        if not resolved:
            group.add(widgets.row("None", "ARIES has not reversed anything"))
            return group
        for r in resolved[:8]:
            row = widgets.row(
                f"{r['target']} — {r['status']}",
                f"{r['established']} → {r.get('proposed') if r.get('proposed') is not None else '—'}"
                f" · {widgets.when(r.get('resolved_at'))}")
            row.add_prefix(widgets.dot("warning" if r["status"] == "applied" else "info"))
            group.add(row)
        return group

    def _explain(self, subject: str):
        ExplainDialog(self.app, subject).present(self.app.get_active_window() or self.app.window)

    def header_suffix(self):
        return widgets.button("Run learning pass", self._run, css="flat")

    def _run(self):
        self.act(lambda c: c.post("/api/aries/automations/aries.learning/run", {"force": True}),
                 done="Learning pass finished")
