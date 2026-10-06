# Background operation and 24-hour evidence

Core and local-model user services are enabled. User lingering is enabled.
Background Mode holds a real logind `sleep` inhibitor, leaving normal screen
blanking available. It does not keep a powered-off machine running. Existing
resource policies remain in effect.

A temporary `aries-endurance.timer` samples every five minutes. The sampler reads
service state, restart counters, cgroup memory/CPU counters, automation state,
power state and ARIES-scoped inference statistics; it performs no model inference.
Artifacts are in `experiments/endurance/<UTC-start>/`. `var/endurance-active.json`
points to the current run. Samples persist across restarts. After 24 elapsed hours,
at least 280 samples, no gap over 15 minutes and all sampled core/local service and
automation API checks must be healthy for the sampled-availability verdict to pass.
Otherwise it fails. It then stops its timer. This does not prove availability
between samples or successful completion of every automation; raw automation results
remain inspectable. Other applications' the reviewing agent/Codex usage is outside its scope.

```bash
systemctl --user status aries-core aries-local-model aries-endurance.timer
cat var/endurance-active.json
# Inspect result.json, report.md and samples.jsonl in the indicated directory.
# Begin another bounded observation after this run finishes:
./scripts/aries-endurance --start
systemctl --user start aries-endurance.timer
```

Initial run started 2026-09-19 00:04:28 UTC (02:04:28 Europe/Skopje), expected to
complete at or after 2026-09-20 02:04:28 local time. It is RUNNING, not passed yet.

GNOME is answering but has an older cached extension build. Full product demo is
10/11; application window verification fails honestly rather than inferring success
from running processes. Isolated shell tests and section navigation pass. A normal
logout/login is needed to load the installed build; no forced logout is performed.
After saving work and signing in again, run `./scripts/aries-smoke` and
`./scripts/aries-demo` to establish the actual result. No 11/11 claim is made here.

## Backend updates independent of login

`./scripts/aries-update` restarts the existing core service, waits for a real API
response and reports desktop protocol capabilities. It defers if an automation
is running. `--local-model` also restarts the model gateway. It never restarts the
compositor, changes session settings or closes personal application windows.

`GET /api/aries/desktop/capabilities` distinguishes missing bridge methods from
source-version differences. Smoke checks actual Ping/Windows/FocusWindow support;
a different build alone is a warning, while a missing desktop capability still
fails honestly. This does not hot-reload GNOME modules: the installed GNOME 50.1
explicitly rejects ReloadExtension. Backend operation and upgrades are independent
of that limitation. Current bridge lacks FocusWindow, so full desktop capability
is not claimed, nor is a kernel modification proposed.

A subsequent live probe also identified a separate condition: ScreenSaver.GetActive
returned true. GNOME suspends this bridge while locked. A missing bus name in that
state is now diagnosed as `session_locked`, not assumed to be an old extension.
Unlocking a session and logging out/in are different actions. ARIES does not disable
screen locking or bypass authentication. Capability probing while locked cannot prove
which methods will be available after unlocking.

## Controlled update drain and screen policy (2026-09-19)

`aries-update` now acquires a four-minute maintenance lease before restarting.
New workspace dispatches and automation execution wait while existing work drains.
Both are checked before restart; force-running an automation does not bypass this
lease. A failed or abandoned updater releases/expires its lease. The lease is
process-local, consistent with the supported single-core deployment; direct
nonqueued API interactions are outside this drain scope. This is not a distributed
maintenance protocol. Queued work stays persisted and resumes after core restart.

At the user's explicit request, GNOME automatic screen locking and Ubuntu
lock-on-suspend were disabled (`lock-enabled=false`, `ubuntu-lock-on-suspend=false`).
Normal screen blanking is separate and remains available. Manual locking and
initial account authentication are not removed.
