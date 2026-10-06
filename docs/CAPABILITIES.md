# M14 capability registry

The authority is `aries/workspace/registry.py`. Every entry declares its input
model, description, risk, approval rule, timeout, executor, verifier and effect.
`GET /api/aries/workspace/capabilities` exposes the same metadata. The planner
cannot execute an unregistered name, and unknown arguments are rejected.

The table below is generated from the registry by `./scripts/aries-capability-docs`, because the hand-written one went stale: on
2026-09-30 it listed about twenty of fifty-eight capabilities. The prose around it
is written by hand, because its reasoning is not derivable from the code.

<!-- generated: ./scripts/aries-capability-docs -->
| Capability | Input | Effect | Approval | Description |
|---|---|---|---|---|
| `browser.back` | session | `open` | — | Task-owned public browser back; observe again after action. No credentials or POST. |
| `browser.click` | session, element_id, expected_url | `open` | — | Task-owned public browser click; observe again after action. No credentials or POST. |
| `browser.download` | session, url, path | `file_mutation` | **yes** | Download an observed public link into a NEW reviewed local path; pinned GET, 20 MB maximum |
| `browser.elements` | session | `read` | — | Task-owned public browser elements; observe again after action. No credentials or POST. |
| `browser.forward` | session | `open` | — | Task-owned public browser forward; observe again after action. No credentials or POST. |
| `browser.navigate` | session, url | `open` | — | Task-owned public browser navigate; observe again after action. No credentials or POST. |
| `browser.observe` | session | `read` | — | Task-owned public browser observe; observe again after action. No credentials or POST. |
| `browser.open` | url | `open` | — | Open a public URL in a task-owned browser and observe navigation |
| `browser.read` | session | `read` | — | Read a task-owned browser session using its observed session ID |
| `browser.scroll` | session, pixels | `open` | — | Task-owned public browser scroll; observe again after action. No credentials or POST. |
| `browser.search` | query, site | `open` | — | Open public web or YouTube search for a literal query |
| `browser.tabs` | none | `read` | — | List only browser tabs owned by this task |
| `browser.type` | session, element_id, value | `open` | — | Task-owned public browser type; observe again after action. No credentials or POST. |
| `browser.wait` | session, milliseconds | `read` | — | Task-owned public browser wait; observe again after action. No credentials or POST. |
| `desktop.close` | window_id, app_id | `desktop` | **yes** | Operate on an exact observed window ID and application identity |
| `desktop.focus` | app, window_id | `open` | — | Focus an already observed installed app; never launch a replacement |
| `desktop.launch` | app | `open` | — | Open an installed application by name; verify visible focused window |
| `desktop.maximize` | window_id, app_id | `desktop` | — | Operate on an exact observed window ID and application identity |
| `desktop.minimize` | window_id, app_id | `desktop` | — | Operate on an exact observed window ID and application identity |
| `desktop.move` | window_id, app_id, x, y | `desktop` | — | Operate on an exact observed window ID and application identity |
| `desktop.observe` | none | `read` | — | Observe authoritative GNOME windows; unavailable is an error |
| `desktop.resize` | window_id, app_id, width, height | `desktop` | — | Operate on an exact observed window ID and application identity |
| `desktop.tile` | window_id, app_id, side | `desktop` | — | Operate on an exact observed window ID and application identity. The rectangle is computed by the shell from the monitor work area and verified against the monitor scale factor, so a tile on a fractionally scaled display is not reported unconfirmed (ARIES_TILE_HIDPI) |
| `desktop.unmaximize` | window_id, app_id | `desktop` | — | Operate on an exact observed window ID and application identity |
| `desktop.windows` | none | `read` | — | Observe authoritative GNOME windows; unavailable is an error |
| `display.brightness` | none | `read` | — | Read the screen brightness; reports every mechanism it probed and why none is available when this machine has no brightness control |
| `display.set_brightness` | level | `display` | **yes** | Set the screen brightness to a percentage and re-read it; refuses with evidence when the hardware exposes no backlight |
| `file.copy` | path, destination, expected_sha256 | `file_mutation` | **yes** | Copy a reviewed source hash to a NEW destination; no overwrite |
| `file.edit` | path, expected_sha256, old_text, new_text | `file_mutation` | **yes** | Replace exactly one text fragment after review of source SHA-256; advisory writer lock |
| `file.exists` | path | `read` | — | Check existence only when asked about existence. For read goals use file.read directly, which reports missing-path errors. |
| `file.list` | path | `read` | — | List at most 200 allowed directory entries |
| `file.metadata` | path | `read` | — | Inspect regular file size, timestamp and SHA-256 up to 20 MB |
| `file.move` | path, destination, expected_sha256 | `file_mutation` | **yes** | Reviewed same-filesystem atomic move to a NEW path; existing destinations refused |
| `file.read` | path | `read` | — | Read a regular UTF-8 text file up to 100 KB |
| `file.rename` | path, destination, expected_sha256 | `file_mutation` | **yes** | Reviewed same-filesystem atomic move to a NEW path; existing destinations refused |
| `file.search` | path, query, modified_after, modified_before | `read` | — | Search filenames under a directory, optionally within an ISO modification-time range |
| `file.semantic_search` | path, query, extension, modified_after, modified_before | `read` | — | Bounded local filename/PDF/text relevance with metadata filters and explanations |
| `file.write` | path, content | `create` | — | Create a NEW nonempty text file; never overwrite. Parent must exist. |
| `input.clipboard_read` | none | `read` | — | Read the current clipboard as text, bounded to 100 KB. Use it only when the user asks what is on the clipboard: it returns whatever they last copied, which may be a password, so never call it for context. |
| `input.clipboard_write` | text | `input` | **yes** | Replace the clipboard with text and verify it by reading it back from a fresh session. The previous clipboard is destroyed and cannot be restored, so approval is required. |
| `input.editable_targets` | app | `read` | — | List one running application's editable text controls with the node identity input.type_text needs. Password fields are never listed. Call this first; a node path alone is not a target. |
| `input.type_text` | app, node, pid, role, name, text, mode | `input` | **yes** | Insert text into ONE control previously reported by input.editable_targets, re-verifying its identity first. Refused unless it is still editable, enabled, focused, in the active window, free of a selection and not a password field. Terminals do not support this and are refused, not approximated. Any text that would arrive incomplete is refused with the reason and the observed character counts, never reported as a success (ARIES_TYPE_STRICT). |
| `network.status` | none | `read` | — | Observe connectivity: link, addresses, gateway, DNS, and separately whether the internet is actually reachable |
| `network.wifi_connect` | name | `network` | **yes** | Bring up an ALREADY-SAVED connection by name; ARIES never accepts a wifi password |
| `network.wifi_list` | none | `read` | — | List visible wifi networks with signal strength and which are already saved; no rescan is forced |
| `notification.send` | title, body | `notify` | **yes** | Create a policy-controlled notification record; approval required |
| `screen.capture` | window_id | `read` | — | See the screen: capture the whole screen, or the area one observed window ID occupies, to an ARIES-owned PNG. A blanked screen or a uniform frame is an error, never a result. |
| `screen.read` | window_id, language | `read` | — | Read what is on the screen: capture it and recover its text with local OCR in Macedonian and English. Use this to answer questions about what is displayed; refuses with instructions if OCR data is missing. |
| `screen.screenshot` | window_id | `read` | — | See the screen: capture the whole screen, or the area one observed window ID occupies, to an ARIES-owned PNG. A blanked screen or a uniform frame is an error, never a result. |
| `system.disk` | none | `read` | — | Measure filesystem usage with statvfs and the largest directories under your home folder. Bounded by depth, entry count and time; a truncated walk says so. |
| `system.packages` | package | `read` | — | Check whether a package is installed and at what version, through dpkg and snap. Never installs anything. |
| `system.processes` | none | `read` | — | Observe bounded process names and IDs; no command lines |
| `system.service` | unit, scope | `read` | — | Inspect ONE systemd unit by name. A name systemd does not know is an error, never an inactive unit. |
| `system.service_control` | unit, scope, action | `service` | **yes** | Start, stop or restart ONE allowlisted user unit. System units are refused: they need an interactive administrator password. Verified by re-reading the unit; a new InvocationID is the proof, not an accepted job. |
| `system.services` | scope, kind, pattern, state | `read` | — | List systemd units with their real ActiveState/SubState and activation time, from the user and system managers. Read-only; a manager that cannot answer is named, not hidden. |
| `system.status` | none | `read` | — | Observe current CPU, memory and disk probes |
| `system.storage` | none | `read` | — | Measure filesystem usage; highest is computed from measured percentages |
| `task.inspect` | task_id | `read` | — | Inspect a persisted task by ID |

58 capabilities: 29 observe only, 29 change something, 12 require approval.
<!-- end generated -->

Default capability timeout is 30 seconds; browser navigation/search allow 100,
desktop launch 60. Execution and verification each have a declared timeout, while
the existing workspace supervisor also imposes a task deadline. Browser pages
retain their own transport/resource limits and deny arbitrary outbound mutation.

`requires_approval` is static metadata; actual policy may additionally require
approval because `operator.confirm_model_plans` is enabled or an inferred write
cannot be bound to an exact supported user contract. Existing-file overwrite is
never enabled by approval.

## Extending the registry

Add a strict Pydantic input model and async executor/verifier, then register one
`Capability`. Do not change the planner loop to introduce a tool. A test adds a
new probe dynamically and verifies its complete lifecycle without changing core
planning code. If the new capability should establish a new type of completed
goal, also supply an independent goal predicate in `contracts.py`; merely adding
a tool must not create an automatic success claim.

There is deliberately no shell, install, delete, kill, credentials, unrestricted
network-write or desktop-click capability in this M14 registry. Existing guarded
legacy features retain their established interfaces and are not model-accessible
through this registry.
