"""The Control Centre's sections, in top navigation order."""
from __future__ import annotations

from aries_ui.pages.automations import AutomationsPage
from aries_ui.pages.analytics import AnalyticsPage
from aries_ui.pages.brief import BriefPage
from aries_ui.pages.connections import ConnectionsPage
from aries_ui.pages.data import DataPage
from aries_ui.pages.dashboard import DashboardPage
from aries_ui.pages.home import HomePage
from aries_ui.pages.monitor import MonitorPage
from aries_ui.pages.files import FilesPage
from aries_ui.pages.applications import ApplicationsPage
from aries_ui.pages.interests import InterestsPage
from aries_ui.pages.learning import LearningPage
from aries_ui.pages.news import NewsPage
from aries_ui.pages.operator import OperatorPage
from aries_ui.pages.settings import SettingsPage
from aries_ui.pages.system import SystemPage

SECTIONS = (
    ("home", HomePage),
    ("monitor", MonitorPage),
    ("analytics", AnalyticsPage),
    ("dashboard", DashboardPage),
    ("files", FilesPage),
    ("applications", ApplicationsPage),
    ("operator", OperatorPage),
    ("brief", BriefPage),
    ("news", NewsPage),
    ("interests", InterestsPage),
    ("learning", LearningPage),
    ("automations", AutomationsPage),
    ("system", SystemPage),
    ("connections", ConnectionsPage),
    ("data", DataPage),
    ("settings", SettingsPage),
)

__all__ = ["SECTIONS"]
