"""Bounded read-only AT-SPI worker, executed with system Python, not core Python.

Uses libatspi introspection as recommended by GNOME. Application labels are
untrusted observations, never instructions. No text/value or action invocation.
"""
import json
import sys
import time
from collections import deque


def inspect(desktop, target, *, max_nodes=100, max_depth=18, seconds=4):
    aliases = {"vscode": "code", "vs code": "code", "visual studio code": "code",
               "files": "org.gnome.nautilus", "nautilus": "org.gnome.nautilus"}
    target = aliases.get(target.casefold(), target.casefold())
    deadline = time.monotonic() + seconds
    apps, nodes, errors = [], [], 0
    truncated = False
    for i in range(min(desktop.get_child_count(), 100)):
        if time.monotonic() >= deadline:
            truncated = True
            break
        try:
            app = desktop.get_child_at_index(i)
            if app and app.get_name().casefold() == target:
                apps.append((app, i))
        except Exception:
            errors += 1
    queue = deque((app, 0, [i], getattr(app, 'get_process_id', lambda: 0)()) for app, i in apps)
    while queue and len(nodes) < max_nodes and time.monotonic() < deadline:
        node, depth, path, pid = queue.popleft()
        try:
            role = node.get_role_name()
            # Do not expose labels or descendants of protected controls.
            protected = "password" in role.casefold()
            iface = None if protected else getattr(node, 'get_action_iface', lambda: None)()
            actions = [iface.get_action_name(i) for i in range(min(iface.get_n_actions(), 8))] if iface else []
            nodes.append({"role": role[:80], "name": "[protected]" if protected else node.get_name()[:160],
                          "depth": depth, "node": '/'.join(map(str,path)), "pid": pid, "actions": actions})
            count = 0 if protected else node.get_child_count()
            if depth >= max_depth:
                truncated |= count > 0
                continue
            remaining = max_nodes - len(nodes) - len(queue)
            truncated |= count > max(0, remaining)
            for i in range(min(count, max(0, remaining))):
                child = node.get_child_at_index(i)
                if child:
                    queue.append((child, depth + 1, path + [i], pid))
        except Exception:
            errors += 1
    controls = sum(n["role"] not in {"application", "frame", "window", "desktop frame"} for n in nodes)
    return {"available": True, "matched": len(apps), "target": target, "controls": controls,
            "nodes": nodes, "truncated": truncated or bool(queue), "errors": errors}


def activate(desktop, expected, action):
    path = [int(i) for i in expected['node'].split('/')]
    if not path or len(path) > 20 or any(i < 0 or i > 10000 for i in path):
        raise ValueError('Invalid control path')
    node = desktop.get_child_at_index(path[0])
    if node.get_process_id() != expected['pid']:
        raise ValueError('Application process changed after review')
    for index in path[1:]:
        node = node.get_child_at_index(index)
    if node.get_name() != expected['name'] or node.get_role_name() != expected['role'] or 'password' in expected['role'].lower():
        raise ValueError('The control changed after review')
    iface = node.get_action_iface()
    names = [iface.get_action_name(i) for i in range(iface.get_n_actions())] if iface else []
    if names.count(action) != 1:
        raise ValueError('The requested action is not uniquely supported')
    return {'invoked': bool(iface.do_action(names.index(action)))}


def main():
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        Atspi.set_timeout(300, 500)
        if len(sys.argv) > 2 and sys.argv[2] == 'activate':
            payload = json.loads(sys.stdin.read(12000))
            result = activate(Atspi.get_desktop(0), payload['target'], payload['action'])
        else:
            result = inspect(Atspi.get_desktop(0), sys.argv[1])
    except Exception as exc:
        result = {"available": False, "nodes": [], "error": type(exc).__name__}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
