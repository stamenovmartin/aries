"""Bounded inspection, protected controls, and core/worker failure boundaries."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap("aries-accessibility")
from aries.operator.accessibility_bridge import inspect, activate
from aries.operator.accessibility import inspect_app


class Node:
    def __init__(self, name, role="application", children=()):
        self.name, self.role, self.children = name, role, children
    def get_name(self): return self.name
    def get_role_name(self): return self.role
    def get_child_count(self): return len(self.children)
    def get_child_at_index(self, index): return self.children[index]


def test_target_bounds_and_protection():
    protected = Node("secret", "password text", [Node("nested secret")])
    desktop = Node("desktop", children=[Node("code", children=[Node("Run", "push button"), protected]), Node("private app")])
    result = inspect(desktop, "VS Code")
    check("exact alias selects only requested application", result["matched"] == 1 and len(result["nodes"]) == 3)
    check("protected names and descendants never leave worker", "secret" not in str(result))
    check("inner controls are distinguished from window-only evidence", result["controls"] == 2)
    result = inspect(desktop, "cod")
    check("substring cannot silently select another application", result["matched"] == 0)
    result = inspect(desktop, "code", max_nodes=1)
    check("bounded traversal reports truncation", len(result["nodes"]) == 1 and result["truncated"])
    check("deadline reports incomplete observation", inspect(desktop, "code", seconds=0)["truncated"])


async def test_worker_timeout_and_bad_output():
    class Process:
        returncode = None
        killed = False
        async def communicate(self): raise asyncio.TimeoutError()
        def kill(self): self.killed = True
        async def wait(self): self.returncode = -9
    proc = Process()
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await inspect_app("code")
    check("timed out worker is killed and reaped", proc.killed and proc.returncode == -9)
    check("timeout is explicit unavailable evidence", not result["available"] and "timed out" in result["error"])
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"bad json", b""))
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        result = await inspect_app("code")
    check("invalid worker output is unavailable rather than successful", not result["available"])


def test_stale_control_is_never_activated():
    class Control(Node):
        called = False
        def get_process_id(self): return 42
        def get_action_iface(self): return self
        def get_n_actions(self): return 1
        def get_action_name(self, i): return 'click'
        def do_action(self, i): self.called = True; return True
    control = Control('Run', 'push button')
    desktop = Node('desktop', children=[control])
    expected = {'node':'0','pid':41,'name':'Run','role':'push button'}
    try:
        activate(desktop, expected, 'click')
    except ValueError:
        pass
    check('changed process prevents invocation', not control.called)
    expected['pid'] = 42
    expected['name'] = 'Old name'
    try:
        activate(desktop, expected, 'click')
    except ValueError:
        pass
    check('changed control name prevents invocation', not control.called)
    expected['name'] = 'Run'
    check('exact supported action invokes the selected control once', activate(desktop, expected, 'click')['invoked'] and control.called)


if __name__ == "__main__":
    sys.exit(run_module(sys.modules[__name__]))
