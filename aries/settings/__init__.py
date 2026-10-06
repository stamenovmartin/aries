"""ARIES Settings — the typed, layered, agent-accessible configuration service.

    from aries.settings import SettingsService, Layer

    s = SettingsService(db)
    await s.get("news.relevance_threshold")          # → 0.6 (default)
    await s.set("news.relevance_threshold", 0.5)     # the user decides
    await s.learn("news.relevance_threshold", 0.72,  # ARIES may only suggest
                  confidence=0.8, rationale="12 of 15 low scorers were ignored")
    await s.get("news.relevance_threshold")          # → 0.5, the user still wins
    await s.explain("news.relevance_threshold")      # → and here is why

Importing this package registers both the schema (`defaults`) and the table
(`store`), so any module that touches settings has them available.
"""
from __future__ import annotations

from aries.settings import defaults as _defaults  # noqa: F401  registers the schema
from aries.settings.layers import Layer, MACHINE_WRITABLE
from aries.settings.schema import SettingDef, SettingError, all_defs, define, get_def, in_section, sections
from aries.settings.service import SettingsService, for_request
from aries.settings.store import GLOBAL, AriesSetting

__all__ = ["SettingsService", "for_request", "Layer", "MACHINE_WRITABLE", "SettingDef",
           "SettingError", "AriesSetting", "GLOBAL", "define", "get_def", "all_defs",
           "in_section", "sections"]
