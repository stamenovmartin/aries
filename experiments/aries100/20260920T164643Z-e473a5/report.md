# ARIES computer-use validation

live API and configured model; no mocked acceptance

| Scenario | Result | State | Reason |
|---|---|---|---|
| desktop-windows | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| desktop-open | FAIL | partial | not done — 114 '' process(es) are running, but desktop session is locked; background tasks continue, desktop actions await unlock — so ARIES cannot tell whether it has a window on screen or is a background process |
| desktop-focus | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| browser-title | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| browser-elements | FAIL | partial | ValueError: 'www.python.org and list its visible navigation links.' could not be resolved: [Errno -2] Name or service not known |
| browser-result | FAIL | partial | ValueError: 'www.python.org, click downloads, and report the resulting page title.' could not be resolved: [Errno -2] Name or service not known |
| file-create-read | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| file-read | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| file-metadata | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| file-semantic | FAIL | partial | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| file-list | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| file-copy | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| system-storage | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| system-status | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| system-processes | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| cross-application | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| context-reference | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| recovery-missing-element | FAIL | partial | ValueError: label empty or too long |
| negative-missing | FAIL | failed | Planner decision retry/call budget exhausted; invalid attempts are recorded |
| negative-shell | PASS | failed |  |

Passed 1/20.
