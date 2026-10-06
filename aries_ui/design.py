"""ARIES design tokens and native command-deck styling.

The user's September 2026 direction is a Jarvis-inspired dark desktop with cyan
instrument panels and distinct screens. Semantic severity and provenance remain
consistent. Metrics and activity indicators must come from actual observations.
"""
from __future__ import annotations

# ── spacing: everything is a multiple of 4 ──────────────────────────────────
XS, SM, MD, LG, XL, XXL = 4, 8, 12, 18, 24, 36

# ── corner radius ───────────────────────────────────────────────────────────
RADIUS_SM, RADIUS_MD, RADIUS_LG = 6, 12, 18

# ── severity, one vocabulary system-wide ────────────────────────────────────
# Mapped to Adwaita's semantic classes so they follow the user's theme and
# accent colour rather than hard-coding hues that break in dark mode.
SEVERITY_CLASS = {
    "ok": "aries-ok",
    # `info` is NEUTRAL, not good. Mapping it to the success colour made "Not
    # built yet" render with a green dot — the interface asserting that an
    # unimplemented integration was fine. Verified-good and simply-neutral must
    # not share a colour, or the colour stops meaning anything.
    "info": "aries-info",
    "notice": "aries-notice",
    "warning": "aries-warning",
    "critical": "aries-critical",
}
SEVERITY_ICON = {
    "ok": "emblem-ok-symbolic",
    "info": "radio-symbolic",
    "notice": "dialog-information-symbolic",
    "warning": "dialog-warning-symbolic",
    "critical": "dialog-error-symbolic",
}
SEVERITY_ORDER = {"ok": 0, "info": 0, "notice": 1, "warning": 2, "critical": 3}

# Source and automation health share the severity vocabulary.
HEALTH_SEVERITY = {
    "ok": "ok", "unused": "info", "disabled": "info",
    "stale": "notice", "degraded": "warning", "failing": "critical",
    "running": "ok", "not started": "notice", "crashed": "critical",
}

# ── provenance: the distinction that must never blur ────────────────────────
EXPLICIT, LEARNED, DEFAULT = "explicit", "learned", "default"
PROVENANCE_CLASS = {
    EXPLICIT: "aries-explicit",
    LEARNED: "aries-learned",
    DEFAULT: "aries-default",
}
PROVENANCE_LABEL = {
    EXPLICIT: "you set this",
    LEARNED: "ARIES inferred this",
    DEFAULT: "default",
}

# ── the stylesheet ──────────────────────────────────────────────────────────
# Small on purpose. Every rule here earns its place by expressing something
# Adwaita has no opinion about; anything Adwaita already does well is left alone.
CSS = """
/* Severity — colour follows the theme, never hard-coded hues. */
.aries-ok       { color: @success_color; }
.aries-info     { color: alpha(@window_fg_color, 0.40); }
.aries-notice   { color: @accent_color; }
.aries-warning  { color: @warning_color; }
.aries-critical { color: @error_color; }

/* Provenance. The difference is FORM, not only colour, so it survives
   greyscale and colour-blindness: explicit is solid, learned is dotted. */
.aries-explicit {
  border-left: 3px solid @accent_color;
  padding-left: 9px;
}
.aries-learned {
  border-left: 3px dotted @warning_color;
  padding-left: 9px;
}
.aries-default { padding-left: 12px; }

.aries-provenance-tag {
  font-size: 0.78rem;
  padding: 1px 7px;
  border-radius: 6px;
  background: alpha(currentColor, 0.10);
}

/* A weight bar: explicit and learned shown side by side, never merged. */
.aries-bar {
  min-height: 6px;
  border-radius: 3px;
  background: alpha(@window_fg_color, 0.10);
}
.aries-bar > progress { border-radius: 3px; min-height: 6px; }
.aries-bar.explicit > progress { background: @accent_color; }
.aries-bar.learned  > progress { background: alpha(@warning_color, 0.75); }

/* Quiet: present, healthy, nothing to say. A calm interface needs this most. */
.aries-quiet { color: alpha(@window_fg_color, 0.55); }

/* Numbers read as data, not as prose. */
.aries-numeric { font-feature-settings: "tnum"; }

/* Monospace where a value is an identifier rather than a sentence. */
.aries-mono {
  font-family: monospace;
  font-size: 0.88rem;
}

/* A status dot. 8px, aligned, no border, no shadow. */
.aries-dot {
  min-width: 8px; min-height: 8px;
  border-radius: 4px;
  background: currentColor;
}

/* Section heading above a group of rows. */
.aries-section-title {
  font-weight: 700;
  font-size: 0.82rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: alpha(@window_fg_color, 0.55);
}

/* The command palette. */
.aries-command-entry { font-size: 1.15rem; }
.aries-command-hint  { font-size: 0.85rem; color: alpha(@window_fg_color, 0.55); }
"""


def severity_of(value: str | None) -> str:
    """Normalise any status word ARIES uses into the severity vocabulary."""
    if not value:
        return "info"
    v = str(value).lower()
    if v in SEVERITY_CLASS:
        return v
    return HEALTH_SEVERITY.get(v, "info")

# September 2026: the requested Jarvis-inspired command deck.
CSS += """
@define-color window_bg_color #070f19;
@define-color window_fg_color #dceaf3;
@define-color view_bg_color #09131f;
@define-color view_fg_color #dceaf3;
@define-color headerbar_bg_color #09131f;
@define-color sidebar_bg_color #0a1623;
@define-color card_bg_color #102233;
@define-color popover_bg_color #122638;
@define-color dialog_bg_color #102233;
@define-color accent_bg_color #157e96;
@define-color accent_color #60def4;
@define-color accent_fg_color #ffffff;
.hud-hero { padding: 28px; border: 1px solid #245166; border-radius: 16px; background: linear-gradient(120deg, #102b3b, #0a1623); }
.hud-kicker { font-family: monospace; font-size: 11px; letter-spacing: 2px; color: #74cbdc; }
.hud-title { font-size: 30px; font-weight: 800; letter-spacing: -1px; }
.hud-value { font-family: monospace; font-size: 30px; font-weight: 700; color: #b8f2fc; }
.hud-muted { color: #9bb2c2; font-size: 12px; }
.hud-accent { color: #60def4; }
.hud-panel { padding: 20px; border: 1px solid #224459; border-radius: 12px; background: #0d1d2b; }
.hud-portal { padding: 22px; border: 1px solid #295268; border-radius: 12px; background: #102434; }
.hud-portal:hover { background: #183b4f; border-color: #62d8ee; }
.hud-story { padding: 22px; border-left: 3px solid #53d5ed; background: #102233; border-radius: 10px; }
.hud-story-title { font-size: 20px; font-weight: 700; }
.navigation-sidebar row:selected { background: #183c4e; color: #9aecfa; border-left: 2px solid #60def4; }
progressbar progress { background: #57d1e9; }
"""
CSS += """
window.background, .background { background-color: #070f19; color: #dceaf3; }
headerbar { background-color: #09131f; color: #dceaf3; }
.navigation-sidebar { background-color: #0a1623; }
list.boxed-list { background-color: #102233; color: #dceaf3; }
viewswitcherbar { background-color: #0a1623; }
"""
CSS += """
.reader-sheet { padding: 32px; background: #0c1c29; border: 1px solid #254b5f; border-radius: 14px; }
.reader-title { font-size: 32px; font-weight: 700; color: #d8f6fb; }
.reader-body { font-size: 18px; line-height: 1.55; color: #e0e9ee; }
.reader-point { font-size: 16px; line-height: 1.5; padding: 14px; background: #112b3b; border-left: 2px solid #65dbed; }
.aries-settings-search { background-color: #102233; color: #dceaf3; border: 1px solid #295268; }
.aries-settings-search text { color: #dceaf3; }
.aries-settings-section > button { background: #102233; color: #dceaf3; border: 1px solid #295268; }
.aries-settings-section > button:hover { background: #183b4f; }
"""
