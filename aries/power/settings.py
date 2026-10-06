"""Background Mode's settings.

`power.background_mode` is `user_only`: whether the machine is prevented from
sleeping is a decision about the user's hardware and electricity bill, and is
never something ARIES may infer for itself.
"""
from __future__ import annotations

from aries.settings.schema import SettingDef, define

S = "power"

define(SettingDef("power.background_mode", bool, False, "ARIES Background Mode",
                  "Keep working while the display is off. The screen still powers down "
                  "normally; only the machine suspending is held back, with a scoped "
                  "inhibitor that is released the instant ARIES stops.",
                  S, control="toggle", user_only=True))

define(SettingDef("power.display_off_after_minutes", int, 10, "Display off after",
                  "How long before the screen powers down while Background Mode is on. "
                  "0 keeps the display on. This is the one setting ARIES writes outside "
                  "itself — the previous value is recorded and restored when Background "
                  "Mode is switched off.",
                  S, control="number", minimum=0, maximum=180, unit="minutes"))

define(SettingDef("power.allow_suspend", bool, False, "Allow normal suspend",
                  "Leave the machine free to suspend even in Background Mode. Everything "
                  "ARIES was doing stops until it wakes.",
                  S, control="toggle", user_only=True))

define(SettingDef("power.allow_gpu_jobs", bool, False, "Allow heavy GPU jobs while the display is off",
                  "Sustained GPU work — local model inference or training — is refused while the "
                  "display is off unless this is on. Nothing in ARIES declares GPU work today, so "
                  "nothing is being refused yet; the gate is real and tested, and the first "
                  "automation that declares `heavy_gpu` meets it.",
                  S, control="toggle", user_only=True))

define(SettingDef("power.allow_heavy_cpu", bool, False, "Allow sustained high-CPU jobs while the display is off",
                  "Work that will hold several cores busy for minutes is refused while the display "
                  "is off unless this is on. When it is on, such a job is still budgeted and still "
                  "gives way to the temperature limit.",
                  S, control="toggle", user_only=True))

# ── the thresholds the policy is measured against ───────────────────────────
# Defaults chosen to be *reachable in both directions*: a limit nothing ever
# crosses is decoration, and one that is crossed constantly is an off switch
# wearing a number. 80 °C is below where consumer silicon begins to throttle
# itself, so ARIES gives way before the hardware has to.

define(SettingDef("power.temperature_limit_celsius", int, 80, "Temperature limit",
                  "Heavy work is deferred while the hottest sensor is at or above this. Light "
                  "work — health checks, news, memory maintenance — is never deferred: they cost "
                  "nothing, and the health check is how you find out the machine is hot.",
                  S, control="number", minimum=40, maximum=105, unit="°C"))

define(SettingDef("power.cpu_limit_pct", int, 70, "CPU limit for heavy work",
                  "A sustained high-CPU job is not started while the processor is already at or "
                  "above this, averaged since the last check.",
                  S, control="number", minimum=10, maximum=100, unit="%"))

define(SettingDef("power.gpu_limit_pct", int, 70, "GPU limit for heavy work",
                  "A sustained GPU job is not started while the GPU is already at or above this.",
                  S, control="number", minimum=10, maximum=100, unit="%"))

define(SettingDef("power.heavy_job_max_minutes", int, 20, "Maximum heavy-job duration",
                  "How long a single heavy job may run before ARIES asks it to stop at its next "
                  "checkpoint. Work that would lose data if interrupted is never stopped — it is "
                  "recorded as over budget and its next run waits.",
                  S, control="number", minimum=1, maximum=720, unit="minutes"))

define(SettingDef("power.thermal_resume_margin_celsius", int, 5, "Cool-down margin",
                  "How far below the temperature limit the machine must come back before "
                  "deferred heavy work resumes. Without a margin the first reading under the "
                  "limit restarts the job that caused the heat.",
                  S, control="number", minimum=0, maximum=30, unit="°C", advanced=True))

define(SettingDef("power.thermal_clear_checks", int, 2, "Cool readings before resuming",
                  "How many consecutive checks must be below the margin before deferred work is "
                  "released. One reading can be a sensor blinking; two in a row is a trend.",
                  S, control="number", minimum=1, maximum=20, advanced=True))

# Written by ARIES, not by the user: what `idle-delay` was before Background Mode
# changed it. -1 means "nothing has been changed, nothing to restore".
define(SettingDef("power.restore_idle_delay", int, -1, "Previous display timeout",
                  "Internal: the display timeout ARIES found before it changed anything, so "
                  "switching Background Mode off can put it back exactly.",
                  S, control="number", minimum=-1, maximum=100000, unit="seconds",
                  advanced=True))
