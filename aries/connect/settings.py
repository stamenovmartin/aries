"""The Integrations switches — every one off or local by default.

Reading a person's mail is the largest thing ARIES has ever been able to do, so
it arrives off, like every automation (§11). `understand_locally` is not a
performance preference: it decides whether the contents of your inbox are
allowed to leave this machine, and the honest default for that is no.
"""
from __future__ import annotations

from aries.settings.schema import SettingDef, define

S = "connect"

define(SettingDef("connect.enabled", bool, False, "Let ARIES read connected sources",
                  "Whether ARIES may read the folders and mailboxes you have connected. "
                  "Off means a source can be registered and checked, and nothing is read.",
                  S, control="toggle", user_only=True))

define(SettingDef("connect.understand_locally", bool, True,
                  "Understand content only on this machine",
                  "Summarising and classifying what ARIES read happens on the local model "
                  "and nowhere else. Turning this off would allow the contents of your "
                  "files and mail to be sent to whichever model provider is configured.",
                  S, control="toggle", user_only=True))

define(SettingDef("connect.max_items_per_read", int, 40, "How much to take at once",
                  "A cap on items per read, so one enormous folder or a busy inbox cannot "
                  "become one enormous working set.",
                  S, control="number", minimum=1, maximum=500, unit="items"))

define(SettingDef("connect.mail_days", int, 3, "How far back to read mail",
                  "Messages older than this are not fetched on a routine read. ARIES is "
                  "answering 'what needs me now', not archiving your mailbox.",
                  S, control="number", minimum=1, maximum=90, unit="days"))

define(SettingDef("connect.report_injection_attempts", bool, True,
                  "Tell me when content tries to give ARIES orders",
                  "Content that contains instructions aimed at the assistant is reported "
                  "next to its summary. ARIES never follows them — this is so you can see "
                  "that someone tried.",
                  S, control="toggle"))
