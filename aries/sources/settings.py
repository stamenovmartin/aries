"""Settings that govern the Sources Registry.

Deliberately few. A source's own configuration — priority, trust, topics, poll
interval — belongs on the SOURCE, not in global settings: it varies per source,
and §24 lists those as fields of a source. What lives here is only what applies
to sources as a class.
"""
from __future__ import annotations

from aries.settings.schema import SettingDef, define

S = "sources"

define(SettingDef("sources.max_sources", int, 200, "Maximum sources",
                  "How many sources may be registered at once. A ceiling, not a target — "
                  "a registry nobody can read through is not useful.",
                  S, control="number", minimum=1, maximum=10000, unit="sources", advanced=True))

# user_only: whether ARIES may point at this machine or the local network is a
# security posture decision, never something a learning loop infers.
define(SettingDef("sources.allow_private_addresses", bool, False,
                  "Allow private and loopback addresses",
                  "Whether a source may point at this machine or a private network address. "
                  "Off by default: a source aimed at localhost is usually a mistake, and "
                  "occasionally an attempt to make ARIES fetch something it should not.",
                  S, control="toggle", user_only=True))

define(SettingDef("sources.require_existing_path", bool, True, "Folder must exist",
                  "Whether a local folder must exist and be readable when it is added. "
                  "Turning this off allows registering a folder that is not mounted yet.",
                  S, control="toggle", advanced=True))

define(SettingDef("sources.unproven_prior", float, 0.5, "Benefit of the doubt",
                  "How a source with no history is ranked against ones with a record, from 0 to 1. "
                  "0.5 puts a new source mid-pack so it gets a chance to prove itself; 0 would "
                  "bury every new source below every old one, permanently.",
                  S, control="slider", minimum=0.0, maximum=1.0, advanced=True))
