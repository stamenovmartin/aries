"""Live goal dashboards, driven only by the ARIES HTTP contract."""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, GLib
from aries_ui import widgets, design, hud
from aries_ui.page import Page

class DashboardPage(Page):
    title = "Dashboards"
    icon = "view-grid-symbolic"
    subtitle = "Ask, follow the work, inspect the result"

    def __init__(self, app, goal_id=None):
        super().__init__(app)
        self._timer = 0
        self._draft = ""
        self._entry = None
        self._active = False
        self._selected = goal_id
        self._pinned = goal_id is not None
        self._signature = None
        self._review_draft = ""
        self.connect("map", self._mapped)
        self.connect("unmap", self._unmapped)

    def _mapped(self, *_):
        if not self._timer:
            self._timer = GLib.timeout_add_seconds(2, self._poll)

    def _unmapped(self, *_):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _poll(self):
        root = self.get_root()
        focus = root.get_focus() if root and hasattr(root, "get_focus") else None
        editing = focus and any(e and (focus == e or focus.is_ancestor(e))
                                for e in (self._entry, getattr(self, "_review_entry", None)))
        if not editing:
            self.reload(quiet=True)
        return GLib.SOURCE_CONTINUE

    def _on_ok(self, data):
        import json
        goal = next((g for g in data.get('goals', []) if g['id'] == self._selected), None)
        self.goal_state = goal['state'] if goal else None
        root = self.get_root()
        if root and hasattr(root, 'lifecycle') and not data.get('auto_close_results', True):
            root.keep.set_active(True)
        focus = root.get_focus() if root and hasattr(root, "get_focus") else None
        entry = getattr(self, "_review_entry", None)
        if focus and entry and (focus == entry or focus.is_ancestor(entry)):
            return
        signature = json.dumps(data, sort_keys=True)
        if signature == self._signature:
            return
        self._signature = signature
        super()._on_ok(data)

    def _on_error(self, exc):
        self._signature = None
        super()._on_error(exc)

    def fetch(self, client):
        return client.get("/api/aries/workspace", **({"goal_id":self._selected} if self._pinned else {}))

    def submit(self, request):
        self._draft = ""
        def done(result):
            self.app.open_goal(result["id"], temporary=True)
        self.act(lambda c: c.post("/api/aries/workspace", {"request": request}), on_ok=done)

    def _open(self, card):
        if card.get("url"):
            body = {"capability": "read_article" if not card.get("ai_generated") else "open_url", "args": {"url": card["url"]}}
        else:
            body = {"capability": "open_path", "args": {"path": card["path"]}}
        self.act(lambda c: c.post("/api/aries/workspace", body), on_ok=lambda r: self.app.open_goal(r["id"], temporary=True))

    def _browser(self, card, kind):
        args = {"session": card["browser_session"]}
        if kind == "browser_follow":
            args["label"] = card["browser_link"]
        self.act(lambda c: c.post("/api/aries/workspace", {"capability": kind, "args": args}),
                 on_ok=lambda r: self.app.open_goal(r["id"], temporary=True))

    def render(self, data):
        self._active = any(g["state"] in {"queued", "running"} for g in data["goals"])
        box = widgets.page_box()
        if not self._pinned:
            box.append(hud.hero("ARIES / RESEARCH & EXECUTION", "Command workspace", "Ask. Act. Inspect the evidence. Each goal keeps its own results.", self.icon))
            portals = hud.grid(4)
            for title, detail, icon, section in [("News radar", "Articles & sources", "application-rss+xml-symbolic", "news"), ("System", "Machine readings", "computer-symbolic", "system"), ("Files", "Locations & activity", "folder-symbolic", "files"), ("Monitoring", "Jobs & measurements", "utilities-system-monitor-symbolic", "monitor")]:
                portals.append(hud.portal(title, detail, icon, lambda s=section: self.app.go(s)))
            box.append(portals)
            group = widgets.section("What would you like done?", "Type a request. ARIES opens a separate response window and keeps its results.")
            entry = Adw.EntryRow(title="Your request")
            entry.set_text(self._draft)
            entry.set_show_apply_button(True)
            entry.connect("changed", lambda e: setattr(self, "_draft", e.get_text()))
            def send(e, *_):
                if e.get_text().strip():
                    self.submit(e.get_text().strip())
            entry.connect("apply", send)
            entry.connect("entry-activated", send)
            self._entry = entry
            group.add(entry)
            box.append(group)
            if not data.get("web_search"):
                row = widgets.row("Public news search is off", "Enable Workspace → Search public news in Settings to fetch fresh results.", activatable=True)
                row.connect("activated", lambda *_: self.app.go("settings"))
                group.add(row)

        goals = data["goals"]
        if goals:
            chosen = next((g for g in goals if g["id"] == self._selected), None if self._pinned else goals[0])
            if chosen is None:
                box.append(widgets.empty('Task unavailable', 'This saved task may have expired under the retention policy.'))
                return widgets.scrolled(box)
            self._selected = chosen["id"]
            root = self.get_root()
            if self._pinned and root and hasattr(root, 'heading'):
                heading = next((c['title'] for c in chosen.get('cards',[]) if c.get('ai_generated')), chosen['request'])
                root.set_title('ARIES · ' + heading[:80])
                root.heading.set_subtitle(chosen['state'].title())
            if hasattr(self, '_tab_key') and self._pinned:
                tab = self.app.window._tabs.get(self._tab_key)
                if tab:
                    tab.set_title(chosen['request'][:48])
                    tab.set_loading(chosen['state'] in {'queued','running'})
                    tab.set_tooltip(chosen['request'] + ' · ' + chosen['state'])
            if hasattr(self.app, "note_goal") and self.get_mapped():
                self.app.note_goal(chosen["id"])
            history = widgets.section("Your tasks")
            for goal in goals[:15]:
                row = widgets.row(goal["request"][:140], f"{goal['state'].replace('_',' ').title()} · {widgets.when(goal['created_at'])}", activatable=True)
                row.connect("activated", lambda _, gid=goal["id"]: self._select(gid))
                history.add(row)
            box.append(self._dashboard(chosen))
            if chosen["state"] not in {"queued", "running", "proposed"}:
                box.append(self._review(chosen))
            if not self._pinned:
                box.append(history)
        else:
            box.append(widgets.empty("Your first dashboard", "Ask for research, open an application, or choose an example below."))

        if self._pinned:
            return widgets.scrolled(box)

        examples = widgets.section("What ARIES can do", "File examples use a demo folder. Install, move and Trash requests show exact targets before execution.")
        for capability in data.get("capabilities", []):
            row = widgets.row(capability["title"], capability["example"], activatable=True)
            row.connect("activated", lambda _, text=capability["example"]: self._fill(text))
            examples.add(row)
        box.append(examples)

        proposals = data.get('memory_replacements') or []
        if proposals:
            review = widgets.section('Review memory changes', 'Your statements stay available. Choose whether the proposed fact replaces the previous interpretation.')
            for item in proposals:
                row = widgets.row(item['old'], 'Proposed: ' + item['proposed'])
                for label, approved in [('Keep previous', False), ('Confirm replacement', True)]:
                    button = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
                    button.connect('clicked', lambda _, pid=item['id'], tid=item['target_id'], approved=approved:
                                   self.act(lambda c: c.post('/api/aries/workspace/memory-replacements/'+pid+'/review',
                                                            {'target_id': tid, 'approved': approved})))
                    row.add_suffix(button)
                review.add(row)
            box.append(review)

        memory = widgets.section("What you asked ARIES to remember", "Explicit facts, stored locally. Delete a fact to stop using it as context.")
        for item in data["memories"][:25]:
            row = widgets.row(item["text"], f"Source: {item['source']} · {widgets.when(item['created_at'])}")
            button = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            button.set_tooltip_text("Forget this fact")
            button.connect("clicked", lambda _, mid=item["id"]: self.act(lambda c: c.delete("/api/aries/workspace/memories/"+mid)))
            row.add_suffix(button)
            memory.add(row)
        if not data["memories"]:
            memory.add(widgets.row("No saved facts", "Try: remember My project is ARIES"))
        box.append(memory)
        return widgets.scrolled(box)

    def header_suffix(self):
        if not self._pinned:
            return None
        button = Gtk.Button(icon_name='dialog-information-symbolic', tooltip_text='Review this task')
        button.set_sensitive(False)
        self._review_button = button
        def focus_review(*_):
            root = self.get_root()
            if root and hasattr(root, 'keep'):
                root.keep.set_active(True)
            entry = getattr(self, '_review_entry', None)
            if entry:
                entry.grab_focus()
                def reveal_actions():
                    scrolled = self._slot.get_first_child()
                    if isinstance(scrolled, Gtk.ScrolledWindow):
                        adjustment = scrolled.get_vadjustment()
                        adjustment.set_value(max(0, adjustment.get_upper() - adjustment.get_page_size()))
                    return GLib.SOURCE_REMOVE
                GLib.idle_add(reveal_actions)
        button.connect('clicked', focus_review)
        return button

    def _review(self, goal):
        if hasattr(self, '_review_button'):
            self._review_button.set_sensitive(True)
        group = widgets.section('Did this task meet your goal?',
                                'Your review stays with the task evidence and helps with similar future tasks.')
        saved = goal.get('review')
        if saved:
            group.add(widgets.row('Your latest review: ' + saved['rating'].replace('_', ' '), saved.get('comment', '')))
        entry = Adw.EntryRow(title='What should ARIES change?')
        self._review_entry = entry
        entry.set_text(self._review_draft)
        def changed(e):
            self._review_draft = e.get_text()
            root = self.get_root()
            if self._review_draft and root and hasattr(root, 'keep'):
                root.keep.set_active(True)
        entry.connect('changed', changed)
        group.add(entry)
        actions = Gtk.Box(spacing=8)
        for label, rating in [('Useful', 'useful'), ('Needs correction', 'needs_work')]:
            button = Gtk.Button(label=label)
            def submit(_, rating=rating):
                comment = entry.get_text().strip()
                if rating == 'needs_work' and not comment:
                    self.app.toast('Describe what needs correcting first')
                    entry.grab_focus()
                    return
                def saved_review(_):
                    self._review_draft = ''
                    root = self.get_root()
                    if root:
                        root.set_focus(None)
                    self._signature = None
                    self.app.toast('Review saved in Learning with this task’s evidence')
                self.act(lambda c:c.post('/api/aries/learning/task-reviews/' + goal['id'],
                                        {'rating':rating, 'comment':comment}), on_ok=saved_review)
            button.connect('clicked', submit)
            actions.append(button)
        group.add(actions)
        return group

    def _fill(self, text):
        self._draft = text
        if self._entry:
            self._entry.set_text(text)
            self._entry.grab_focus()

    def _select(self, goal_id):
        self.app.open_goal(goal_id)

    def _dashboard(self, goal):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=design.MD)
        summary = widgets.section(goal["request"], f"{goal['state'].title()} · {widgets.when(goal['created_at'])}")
        if goal["state"] in {"queued", "running"}:
            row = widgets.row("Work in progress", "You can leave this page; ARIES keeps the task running.")
            cancel = Gtk.Button(label="Cancel", valign=Gtk.Align.CENTER)
            cancel.connect("clicked", lambda *_: self.act(lambda c: c.post(f"/api/aries/workspace/{goal['id']}/cancel", {})))
            row.add_suffix(cancel)
            summary.add(row)
        if goal.get('recovery'):
            origin = goal['recovery']
            previous = widgets.row('Continued from a previous attempt', 'Completed changes are rechecked, never executed again.')
            previous.add_suffix(widgets.button('Original attempt', lambda:self.app.open_goal(origin['parent_id']), css='flat'))
            summary.add(previous)
        if goal['state'] in {'partial','failed','interrupted','unconfirmed','held','empty'}:
            row = widgets.row('Continue safely', 'Recheck saved changes and retry supported reads. Uncertain changes are not repeated.')
            row.add_suffix(widgets.button('Open continuation' if goal.get('recovery_child_id') else 'Check and continue', lambda:self.act(
                lambda c:c.post('/api/aries/workspace/'+goal['id']+'/recover', {}),
                on_ok=lambda r:self.app.open_goal(r['id'], temporary=True)), css='pill'))
            summary.add(row)
        for step in goal.get("steps", []):
            result = step.get("result", {})
            summary.add(widgets.row(step["request"], f"{'Rechecked · not repeated' if step.get('inherited') else step.get('state','Waiting').title()} · {result.get('summary','')}"))
            if step.get('step_id'):
                import json
                summary.add(widgets.row('Planner → ' + step['capability'], json.dumps(step.get('args',{}),ensure_ascii=False)[:1600]))
                summary.add(widgets.row('Execution / Verification', step.get('execution_status','') + ' / ' + step.get('verification_status','')))
                summary.add(widgets.row('Observation', json.dumps(step.get('observation'),ensure_ascii=False)[:1800]))
                summary.add(widgets.row('Evidence', ', '.join(step.get('evidence_refs',[])) or step.get('observation_ref','Pending')))
            if step.get("state") == "proposed":
                # Show exactly the frozen inputs the approval will execute.
                import json
                detail = step.get("args") if step.get("kind") == "capability" else step.get("operator_plan", {})
                summary.add(widgets.row("Proposed change", json.dumps(detail, ensure_ascii=False, indent=2)))
        if goal.get('final_evidence_refs'):
            summary.add(widgets.row('Final verified evidence', ', '.join(goal['final_evidence_refs'])))
        if goal["state"] == "proposed":
            row = widgets.row("Review the target above", "Approve this exact change, or cancel it.")
            approve = Gtk.Button(label="Approve change", valign=Gtk.Align.CENTER)
            approve.add_css_class("suggested-action")
            approve.connect("clicked", lambda *_: self.act(lambda c: c.post(f"/api/aries/workspace/{goal['id']}/approve", {})))
            row.add_suffix(approve)
            cancel = Gtk.Button(label="Cancel", valign=Gtk.Align.CENTER)
            cancel.connect("clicked", lambda *_: self.act(lambda c: c.post(f"/api/aries/workspace/{goal['id']}/cancel", {})))
            row.add_suffix(cancel)
            summary.add(row)
        for gap in goal.get("gaps", []):
            summary.add(widgets.row("Not completed", gap))
        kinds = {s.get('capability') for s in goal.get('steps', [])}
        if goal.get('agent'):
            title, icon = 'Goal execution', 'system-run-symbolic'
        elif 'build_python' in kinds:
            title, icon = 'Development workspace', 'applications-development-symbolic'
        elif any(k and k.startswith('browser_') for k in kinds):
            title, icon = 'Browser workspace', 'web-browser-symbolic'
        elif 'install_app' in kinds:
            title, icon = 'Application installation', 'system-software-install-symbolic'
        elif kinds & {'list_folder','read_file','find_files','create_file','move_file','trash_file'}:
            title, icon = 'File workspace', 'folder-symbolic'
        elif any(s.get('kind') == 'research' for s in goal.get('steps', [])):
            title, icon = 'Research intelligence', 'system-search-symbolic'
        else:
            title, icon = 'Task execution', 'system-run-symbolic'
        cards = goal.get("cards", [])
        generated = [c for c in cards if c.get('ai_generated')]
        if generated:
            for card in generated:
                box.append(hud.reading(card, lambda c=card:self._open(c), lambda url:self._open({"url":url})))
            details = Adw.ExpanderRow(title='Execution details', subtitle=goal['state'].title())
            for step in goal.get('steps',[]):
                details.add_row(widgets.row(step['request'], step.get('state','waiting')))
            group = widgets.section('')
            group.add(details)
            box.append(group)
            for gap in goal.get('gaps',[]):
                box.append(hud.label(gap, 'hud-muted'))
            return box
        box.append(hud.hero('ARIES / ' + goal['state'].upper(), title, goal['request'], icon))
        box.append(summary)
        if goal.get('progress') and goal['state'] == 'running':
            box.append(hud.metric('Current action', goal['progress'], 'Reported by the executing capability'))
        if cards:
            grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                               min_children_per_line=1, max_children_per_line=2,
                               column_spacing=design.MD, row_spacing=design.MD)
            for card in cards[:60]:
                content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=design.SM)
                for margin in ("top", "bottom", "start", "end"):
                    getattr(content, "set_margin_"+margin)(design.MD)
                title = Gtk.Label(label=card.get("title", "Result"), xalign=0, wrap=True, selectable=True)
                title.set_max_width_chars(42)
                title.add_css_class("heading")
                content.append(title)
                body = Gtk.Label(label=card.get("text", ""), xalign=0, wrap=True, selectable=True)
                body.set_max_width_chars(48)
                content.append(body)
                evidence = Gtk.Label(label=card.get("evidence", ""), xalign=0, wrap=True)
                evidence.set_max_width_chars(48)
                evidence.add_css_class("dim-label")
                content.append(evidence)
                control = card.get("ui_control", {})
                if control.get("actions") and control.get("node"):
                    expected = Gtk.Entry(placeholder_text="Name of the element expected after this action")
                    content.append(expected)
                    for action in control["actions"][:3]:
                        button = Gtk.Button(label="Review action: " + action)
                        def activate(_, c=control, a=action, entry=expected):
                            if not entry.get_text().strip():
                                entry.grab_focus()
                                return
                            args = {"app": c["app"], "node": c["node"], "action": a, "expected": entry.get_text().strip()}
                            self.act(lambda client: client.post("/api/aries/workspace", {"capability": "ui_action", "args": args}), on_ok=lambda r:self.app.open_goal(r["id"], temporary=True))
                        button.connect("clicked", activate)
                        content.append(button)
                if card.get("browser_session") and not card.get("browser_closed"):
                    if card.get('browser_field'):
                        entry = Gtk.Entry(placeholder_text='Value to enter in this field')
                        content.append(entry)
                        fill = Gtk.Button(label='Review field entry')
                        def fill_field(_, c=card, e=entry):
                            args = {'session':c['browser_session'], 'label':c['browser_field'], 'value':e.get_text()}
                            self.act(lambda client:client.post('/api/aries/workspace', {'capability':'browser_fill','args':args}), on_ok=lambda r:self.app.open_goal(r['id'], temporary=True))
                        fill.connect('clicked', fill_field)
                        content.append(fill)
                    kind = "browser_follow" if card.get("browser_link") else "browser_inspect"
                    button = Gtk.Button(label="Follow link" if card.get("browser_link") else "Refresh page evidence")
                    button.connect("clicked", lambda _, c=card, k=kind: self._browser(c, k))
                    content.append(button)
                    content.append(hud.label("Session: " + card["browser_session"], "hud-muted"))
                    if not card.get("browser_link"):
                        close = Gtk.Button(label="Close this browser session")
                        close.connect("clicked", lambda _, c=card: self._browser(c, "browser_close"))
                        content.append(close)
                if card.get("source") or card.get("published"):
                    source = Gtk.Label(label=" · ".join(str(card[k]) for k in ("source", "published") if card.get(k)), xalign=0, wrap=True)
                    source.set_max_width_chars(48)
                    source.add_css_class("caption")
                    content.append(source)
                if card.get("url") or card.get("path"):
                    button = Gtk.Button(label="Open source" if card.get("url") else "Open")
                    button.connect("clicked", lambda _, c=card: self._open(c))
                    content.append(button)
                frame = Gtk.Frame(child=content)
                frame.add_css_class("hud-story")
                grid.append(frame)
            box.append(grid)
        if goal.get("context"):
            context = widgets.section("Related personal context", "These facts remain local and are not sent to public search.")
            for memory in goal["context"]:
                context.add(widgets.row(memory["text"], "Source: " + memory["source"]))
            box.append(context)
        if goal.get("related"):
            related = widgets.section("Related past work")
            for item in goal["related"]:
                row = widgets.row(item["request"], activatable=True)
                row.connect("activated", lambda _, gid=item["id"]: self._select(gid))
                related.add(row)
            box.append(related)
        return box
