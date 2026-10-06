"""Static map of the spoken (CATALOGUE) surface: who can verify, who records it.

The measurement in `probe.py` says which capabilities DID record a verification.
This says which ones COULD — read out of the source of `capabilities.execute()`
rather than from the docs, because the docs are what is in question.

Method, so the table is reproducible rather than asserted:
  * split `execute()` into top-level `if kind ...:` branch regions by indentation
  * a capability "returns verification" if its region contains the literal
    `"verification"` on a returning line, or it falls through to the `WRITES`
    tail (line ~983), which always attaches one
  * `verify()` branches are the independent re-read checks; listed separately,
    because a branch in `verify()` is only reached for `WRITES` kinds
  * DELEGATES records the one-level hand-off to a module whose own voice wrapper
    attaches verification (input_capabilities, keyboard) or to another engine
"""
from __future__ import annotations

import inspect
import json
import re
import sys

sys.path[:0] = ["/home/stamenovmartin/aries/vendor/agentic-core",
                "/home/stamenovmartin/aries/vendor", "/home/stamenovmartin/aries"]

from aries.workspace import capabilities as C            # noqa: E402
from aries.workspace.registry import registry            # noqa: E402

SRC = inspect.getsource(C.execute).splitlines()
VSRC = inspect.getsource(C.verify)

# Spoken name -> M14 registry capability that already verifies the same effect.
# Hand-built, one line of evidence each: the registry name and its verifier.
TWIN = {
    "read_file": "file.read", "list_folder": "file.list", "find_files": "file.search",
    "processes": "system.processes", "system": "system.status", "disk": "system.disk",
    "package_info": "system.packages", "services": "system.services",
    "service_control": "system.service_control", "network_status": "network.status",
    "wifi_list": "network.wifi_list", "wifi_connect": "network.wifi_connect",
    "brightness": "display.brightness", "set_brightness": "display.set_brightness",
    "read_screen": "screen.read", "screenshot": "screen.capture",
    "clipboard_read": "input.clipboard_read", "clipboard_write": "input.clipboard_write",
    "editable_fields": "input.editable_targets", "type_text": "input.type_text",
    "open_app": "desktop.launch", "browser_open": "browser.open",
    "browser_inspect": "browser.observe", "search_web": "browser.search",
    "open_url": "browser.open", "read_article": None, "inspect_app": None,
}

BRANCH = re.compile(r'^(\s+)(?:el)?if kind (==|in|\.startswith)\s*(.+?):\s*$')

# Branches that attach no `verification` literal themselves but hand the whole
# result dict back from a wrapper that does. Read from the wrapper's source, not
# assumed: input_capabilities.voice_clipboard_read/_write/voice_type_text each
# build 'verification' (lines 587, 592, 609, 645), editable_fields does not.
DELEGATES_VERIFY = {"clipboard_read", "clipboard_write", "type_text"}


def guards(expr):
    if "WRITES" in expr:
        return set(C.WRITES)
    return set(re.findall(r"""['\"]([a-z_.]+)['\"]""", expr))


def owners():
    """capability -> the `return` lines reachable under its own guard.

    Two rules, both needed by real branches in this file:
      * a guard opened at indent i owns every line until indentation drops to i
        or below, so a nested `if kind` guard splits a shared region;
      * once a nested guard for kind K has RETURNED, K cannot reach the rest of
        the enclosing region — which is exactly the shape of `abilities`/
        `can_you` and of the four `system_capabilities` kinds, where the tail's
        `verification` belongs to one kind only.
    """
    own, stack, escaped = {}, [], {}   # stack of (indent, kinds); escaped per region id
    for line in SRC:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        while stack and indent <= stack[-1][0]:
            gone = stack.pop()
            if stack and gone[2]:                 # nested guard returned
                escaped.setdefault(id(stack[-1][1]), set()).update(gone[1])
        m = BRANCH.match(line)
        if m:
            stack.append([len(m.group(1)), guards(m.group(3)), False])
            continue
        if not stack:
            continue
        if re.match(r'\s*return\b', line):
            stack[-1][2] = True
        out = stack[-1][1] - escaped.get(id(stack[-1][1]), set())
        for k in out:
            own.setdefault(k, []).append(line)
    return own


def main():
    probe = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else {}
    measured = probe.get("per_capability", {})
    shapes = probe.get("shape", {})

    own = owners()
    rows = []
    for name, title, _ex in C.CATALOGUE:
        mine = own.get(name, [])
        text = "\n".join(mine)
        returns_v = ('"verification"' in text or "'verification'" in text
                     or name in DELEGATES_VERIFY)
        # WRITES fall through to the tail at the end of the WRITES region, which
        # always attaches verification.
        if name in C.WRITES:
            returns_v = True
        has_verify_branch = bool(re.search(r'kind == ["\']%s["\']' % name, VSRC)) or \
            bool(re.search(r'kind in \{[^}]*["\']%s["\']' % name, VSRC))
        delegate = ""
        if "input_capabilities as text_input" in text:
            delegate = "input_capabilities.voice_*"
        elif "screen_capabilities as screen" in text:
            delegate = "screen_capabilities"
        elif "system_capabilities as sysadm" in text:
            delegate = "system_capabilities"
        elif "network_capabilities as net" in text:
            delegate = "network_capabilities"
        elif "operator import service as operator" in text:
            delegate = "operator.run (own Verification, not recorded as a step field)"
        elif name == "agent_task":
            delegate = "workspace.agent (M14, writes verification_status)"
        elif name == "research":
            delegate = "NONE — service.py handles it, execute() has no branch"
        b = measured.get(name, {})
        rows.append({
            "capability": name, "in_execute": bool(mine),
            "returns_verification": returns_v,
            "verify_branch": has_verify_branch,
            "m14_twin": TWIN.get(name) or "",
            "delegate": delegate,
            "steps": sum(b.values()), "buckets": b,
            "recorded_verification":
                shapes.get(name, {}).get("result.verification", 0),
            "recorded_verification_status":
                shapes.get(name, {}).get("key:verification_status", 0),
        })
    json.dump({"registry_capabilities": len(registry._items),
               "registry_without_verifier":
                   [n for n, c in registry._items.items() if c.verifier is None],
               "catalogue_size": len(C.CATALOGUE),
               "returns_verification":
                   sorted(r["capability"] for r in rows if r["returns_verification"]),
               "no_verification":
                   sorted(r["capability"] for r in rows if not r["returns_verification"]),
               "rows": rows}, sys.stdout, indent=1)


if __name__ == "__main__":
    main()
