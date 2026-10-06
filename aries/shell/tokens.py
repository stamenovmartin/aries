"""The ARIES design language, in one place, in a form both surfaces can read.

WHY THIS FILE EXISTS
--------------------
ARIES now paints in two toolkits that share nothing: the Control Centre is GTK4
with libadwaita, and the shell is GNOME Shell's St widgets inside `gnome-shell`'s
own process. They cannot import each other — different languages, different
processes, different renderers — and the one thing worse than two design systems
is two design systems that were supposed to be one.

Entry 011 already learned this shape of problem: a boundary with no compiler
across it needs the expectation written down as data and tested. So the tokens
live here, and both stylesheets are GENERATED from them:

    tokens.py ──> aries_ui/design.py CSS      (GTK4, theme-relative)
              └─> shell/…/stylesheet.css      (St, literal values)

`generate()` writes the shell stylesheet; a test asserts the file on disk matches
what the tokens produce, so a token changed without regenerating fails in the
suite rather than as a drifting shade of grey nobody can place.

WHY THE TWO OUTPUTS DIFFER
--------------------------
GTK gets *theme-relative* colours — `@accent_color`, `@window_fg_color` — because
a control-centre window that ignored the user's accent colour and their
light/dark preference would look foreign on their own desktop.

St gets *literal* values, because GNOME Shell's CSS is a small subset: no
variables, no `alpha()`, no `calc()`. Everything must be resolved before it is
written. That constraint is the whole reason this file exists rather than a
stylesheet somebody keeps in sync by hand.

THE LANGUAGE
------------
Minimal, calm, premium; Apple-influenced in *interaction quality* — motion that
explains, focus you can always see, nothing that moves without a reason — and
deliberately not a macOS clone: no traffic lights, no dock magnification, no
glass, no skeuomorphism, no imitation of anyone's icon shapes.

Concretely, what the language is made of:

  TYPE       one family (the system's), five sizes, two weights. A shell that
             needs more than five text sizes is a shell with unclear hierarchy.
  SPACE      every gap is a multiple of 4. No exceptions, so rhythm is automatic.
  RADII      three, chosen so nesting looks right: a control inside a surface
             inside a panel.
  SURFACE    four elevations expressed as background + border, not as shadow
             piles. One shadow, used for things that genuinely float.
  MOTION     three durations and two curves. Nothing lasts longer than 250 ms,
             because a desktop that makes you wait for it is not premium, it is
             slow wearing a costume.
  FOCUS      one ring, 2 px, always visible, never suppressed. Keyboard-only
             navigation is a requirement, and it is unusable without this.
"""
from __future__ import annotations

import textwrap

# ── space ───────────────────────────────────────────────────────────────────
# Identical numbers to the Control Centre's, because the two surfaces sit side
# by side on one screen and a 12 px gap in one next to a 14 px gap in the other
# is the kind of difference nobody names and everybody feels.
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 18, "xl": 24, "xxl": 36}

# ── radii ───────────────────────────────────────────────────────────────────
RADIUS = {"sm": 6, "md": 12, "lg": 18, "pill": 999}

# ── type ────────────────────────────────────────────────────────────────────
# Sizes in points for St (GNOME Shell's CSS works in pt for font-size).
TYPE = {
    "caption": {"size": 8.5, "weight": 500},
    "body": {"size": 10, "weight": 400},
    "emphasis": {"size": 10, "weight": 600},
    "title": {"size": 12, "weight": 600},
    "display": {"size": 16, "weight": 600},
}
MONO = "monospace"

# ── motion ──────────────────────────────────────────────────────────────────
# Three durations. `instant` is for state that must feel like a switch,
# `quick` for things appearing, `settle` for something large moving into place.
MOTION = {"instant": 90, "quick": 160, "settle": 240}
EASE = {
    # A gentle deceleration for things arriving, and a symmetric curve for
    # things that move without arriving. Named for what they are for, so the
    # choice at each call site is a statement about meaning rather than taste.
    "arrive": "cubic-bezier(0.22, 0.68, 0.36, 1.0)",
    "move": "cubic-bezier(0.4, 0.0, 0.2, 1.0)",
}

# ── colour ──────────────────────────────────────────────────────────────────
# Two complete palettes, because St cannot compute one from the other. Written
# as full 8-digit hex where transparency matters, since St's `alpha()` support
# is not something to rely on.
#
# The greys are deliberately slightly blue rather than neutral: a pure grey
# panel over a colourful wallpaper reads as dirty, and a hint of blue reads as
# glass without any actual blur, which is expensive and distracting.
#
# `surface` is nearly opaque and `bg` is not. That asymmetry is the rule for
# legibility over an unknown wallpaper: a panel may borrow colour from what is
# behind it, but a surface carrying TEXT may not — the first capture of the
# launcher had a wallpaper showing through the gaps between application names,
# which looks like a design until you try to read it.
DARK = {
    "bg": "#14161acc",           # panel/dock ground, translucent over wallpaper
    "bg_solid": "#14161a",
    "surface": "#1b1f27fb",      # cards and menus sitting on the ground
    "surface_hi": "#262a32",     # hover
    "border": "#ffffff1f",
    "fg": "#f2f4f8",
    "fg_dim": "#f2f4f899",
    "fg_faint": "#f2f4f859",
    "accent": "#5b9dff",
    "accent_fg": "#0b1220",
    "ok": "#4cc38a",
    "notice": "#5b9dff",
    "warning": "#f0b429",
    "critical": "#ff6b6b",
    "shadow": "rgba(0, 0, 0, 0.45)",
}
LIGHT = {
    "bg": "#fbfcfeda",
    "bg_solid": "#fbfcfe",
    "surface": "#fdfefffb",
    "surface_hi": "#eef1f6",
    "border": "#0a0f1a1f",
    "fg": "#12151b",
    "fg_dim": "#12151b99",
    "fg_faint": "#12151b59",
    "accent": "#1f6feb",
    "accent_fg": "#ffffff",
    "ok": "#1a7f4b",
    "notice": "#1f6feb",
    "warning": "#a86b00",
    "critical": "#c62828",
    "shadow": "rgba(10, 15, 26, 0.18)",
}

# ── severity, the one vocabulary ────────────────────────────────────────────
# Identical to the Control Centre's, because a warning must be the same colour
# in the top bar as it is in the window the top bar opens.
SEVERITIES = ("ok", "info", "notice", "warning", "critical")

# ── sizes that are structure, not style ─────────────────────────────────────
PANEL_HEIGHT = 32
DOCK_ICON = 44
DOCK_ICON_SMALL = 34
FOCUS_RING = 2


def css_colour(value: str) -> str:
    """A colour St will actually parse.

    GNOME Shell's CSS parser does not understand 8-digit `#RRGGBBAA` hex. It
    does not warn either — it drops the declaration, so an element written with
    a translucent background simply has no background at all.

    That cost a milestone's worth of confusion: the dock had no panel behind its
    icons and ARIES Search was fully transparent with the window behind showing
    through its text, while the six-digit colours beside them (the selected row's
    blue) rendered perfectly. The tokens looked right, the stylesheet looked
    right, and half the surfaces were invisible.

    So every colour is emitted through here, and anything carrying alpha becomes
    `rgba()`, which St has always supported — the box-shadow rules were already
    written that way, which is exactly why the shadows worked when the fills
    did not.
    """
    if value.startswith("#") and len(value) == 9:
        r, g, b, a = (int(value[i:i + 2], 16) for i in (1, 3, 5, 7))
        return f"rgba({r}, {g}, {b}, {a / 255:.3f})"
    return value


def _type_rule(name: str) -> str:
    t = TYPE[name]
    return f"font-size: {t['size']}pt; font-weight: {t['weight']};"


def shell_stylesheet() -> str:
    """The GNOME Shell stylesheet, fully resolved.

    Written as two complete blocks rather than as variables with overrides,
    because St has no variables and a half-overridden palette is how a widget
    ends up with light text on a light ground in exactly one state.
    """
    out = [textwrap.dedent(f"""\
        /* ARIES Shell — GENERATED from aries/shell/tokens.py. Do not edit.
         *
         * Regenerate with:  ./scripts/aries-shell generate
         * A test asserts this file matches the tokens, so an edit here is
         * reverted by the next generate and fails the suite in between.
         *
         * GNOME Shell's CSS is a subset: no variables, no calc(), no nesting.
         * Everything below is resolved from the tokens at generation time.
         */

        /* ── the panel ─────────────────────────────────────────────────── */
        .aries-panel-button {{
            -natural-hpadding: {SPACE['md']}px;
            -minimum-hpadding: {SPACE['sm']}px;
            border-radius: {RADIUS['sm']}px;
            transition-duration: {MOTION['instant']}ms;
        }}
        .aries-panel-label {{ {_type_rule('body')} }}
        .aries-panel-dim   {{ {_type_rule('caption')} }}
        .aries-panel-dot {{
            width: 8px; height: 8px; border-radius: {RADIUS['pill']}px;
            margin-right: {SPACE['sm']}px;
        }}
        .aries-workspace-pill {{
            width: 7px; height: 7px; border-radius: {RADIUS['pill']}px;
            margin: 0 3px;
            transition-duration: {MOTION['quick']}ms;
        }}
        .aries-workspace-pill-active {{ width: 18px; }}

        /* Compact application icons beside the ARIES mark. */
.aries-top-apps {{ spacing: 2px; margin: 0 6px; }}
.aries-top-app {{ padding: 2px 5px; border-radius: 5px; }}
.aries-top-app:hover, .aries-top-app:focus {{ background-color: rgba(128,128,128,0.22); }}

/* ── the dock ──────────────────────────────────────────────────── */
        .aries-dock {{
            padding: {SPACE['sm']}px;
            border-radius: {RADIUS['lg']}px;
            border-width: 1px;
            spacing: {SPACE['xs']}px;
        }}
        .aries-dock-item {{
            padding: {SPACE['xs']}px;
            border-radius: {RADIUS['md']}px;
            transition-duration: {MOTION['instant']}ms;
        }}
        .aries-dock-running {{
            width: 5px; height: 5px; border-radius: {RADIUS['pill']}px;
            margin-top: 3px;
        }}
        .aries-dock-running-wide {{ width: 14px; }}

        /* ── command bar and launcher ──────────────────────────────────── */
        .aries-command {{
            width: 680px;
            border-radius: {RADIUS['lg']}px;
            border-width: 1px;
            padding: {SPACE['sm']}px;
        }}
        .aries-command-entry {{
            {_type_rule('title')}
            padding: {SPACE['md']}px {SPACE['lg']}px;
            border-radius: {RADIUS['md']}px;
            border-width: 0;
        }}
        .aries-command-entry StLabel.hint {{ {_type_rule('title')} }}
        .aries-command-list {{ padding: {SPACE['xs']}px; }}
        .aries-command-row {{
            padding: {SPACE['sm']}px {SPACE['md']}px;
            border-radius: {RADIUS['md']}px;
            spacing: {SPACE['md']}px;
            transition-duration: {MOTION['instant']}ms;
        }}
        .aries-command-title {{ {_type_rule('emphasis')} }}
        .aries-command-detail {{ {_type_rule('caption')} }}
        .aries-command-kind {{
            {_type_rule('caption')}
            padding: 1px {SPACE['sm']}px;
            border-radius: {RADIUS['pill']}px;
        }}
        .aries-command-footer {{
            {_type_rule('caption')}
            padding: {SPACE['sm']}px {SPACE['md']}px;
        }}

        /* ── panels shared by the notification centre and quick settings ── */
        .aries-card {{
            border-radius: {RADIUS['md']}px;
            border-width: 1px;
            padding: {SPACE['md']}px;
            spacing: {SPACE['sm']}px;
        }}
        .aries-card-title {{ {_type_rule('emphasis')} }}
        .aries-card-body  {{ {_type_rule('body')} }}
        .aries-card-meta  {{ {_type_rule('caption')} }}
        .aries-empty      {{ {_type_rule('body')} padding: {SPACE['xl']}px; }}

        /* ── focus: one ring, always visible ───────────────────────────── */
        .aries-focusable:focus {{
            border-width: {FOCUS_RING}px;
            border-radius: {RADIUS['md']}px;
        }}
        """)]

    for scheme, raw_palette in (("dark", DARK), ("light", LIGHT)):
        palette = {name: css_colour(value) for name, value in raw_palette.items()}
        prefix = "" if scheme == "dark" else ".aries-light "
        out.append(textwrap.dedent(f"""\

            /* ── {scheme} ──────────────────────────────────────────────────── */
            {prefix}.aries-surface        {{ background-color: {palette['bg']};
                                      border-color: {palette['border']};
                                      color: {palette['fg']}; }}
            {prefix}.aries-raised         {{ background-color: {palette['surface']};
                                      border-color: {palette['border']};
                                      color: {palette['fg']};
                                      box-shadow: 0 8px 24px {palette['shadow']}; }}
            {prefix}.aries-panel-button:hover,
            {prefix}.aries-dock-item:hover,
            {prefix}.aries-command-row:hover {{ background-color: {palette['surface_hi']}; }}
            {prefix}.aries-command-row:selected {{ background-color: {palette['accent']};
                                            color: {palette['accent_fg']}; }}
            {prefix}.aries-command-row:selected .aries-command-detail {{
                                            color: {palette['accent_fg']}; }}
            {prefix}.aries-command-entry   {{ background-color: {palette['surface_hi']};
                                      color: {palette['fg']}; }}
            {prefix}.aries-command-kind    {{ background-color: {palette['surface_hi']};
                                      color: {palette['fg_dim']}; }}
            {prefix}.aries-dim             {{ color: {palette['fg_dim']}; }}
            {prefix}.aries-faint           {{ color: {palette['fg_faint']}; }}
            {prefix}.aries-command-detail,
            {prefix}.aries-command-footer,
            {prefix}.aries-card-meta,
            {prefix}.aries-panel-dim,
            {prefix}.aries-empty           {{ color: {palette['fg_dim']}; }}
            {prefix}.aries-focusable:focus {{ border-color: {palette['accent']}; }}
            {prefix}.aries-workspace-pill  {{ background-color: {palette['fg_faint']}; }}
            {prefix}.aries-workspace-pill-active {{ background-color: {palette['accent']}; }}
            {prefix}.aries-dock-running    {{ background-color: {palette['fg_dim']}; }}
            {prefix}.aries-dock-running-wide {{ background-color: {palette['accent']}; }}
            {prefix}.aries-sev-ok        {{ background-color: {palette['ok']}; }}
            {prefix}.aries-sev-info      {{ background-color: {palette['fg_faint']}; }}
            {prefix}.aries-sev-notice    {{ background-color: {palette['notice']}; }}
            {prefix}.aries-sev-warning   {{ background-color: {palette['warning']}; }}
            {prefix}.aries-sev-critical  {{ background-color: {palette['critical']}; }}
            {prefix}.aries-text-ok       {{ color: {palette['ok']}; }}
            {prefix}.aries-text-notice   {{ color: {palette['notice']}; }}
            {prefix}.aries-text-warning  {{ color: {palette['warning']}; }}
            {prefix}.aries-text-critical {{ color: {palette['critical']}; }}
            """))
    out.append(session_theme())
    return "".join(out)


def session_theme() -> str:
    """ARIES over the session's own theme — the part that makes the desktop
    stop looking like stock Ubuntu.

    WHY THIS EXISTS SEPARATELY
    --------------------------
    Everything above styles widgets ARIES creates. This styles widgets GNOME
    creates: the top bar, its buttons, its menus, the notification list, the
    overview dash. Without it the ARIES shell is an indicator added to somebody
    else's panel, which is exactly the "Linux feature with an ARIES add-on"
    shape `PRODUCT_IDENTITY.md` rules out — and precisely the criticism this
    section was written to answer.

    WHY `!important` IS HERE AND NOWHERE ELSE
    -----------------------------------------
    Yaru's dark stylesheet sets `#panel { background-color: #131313 !important }`.
    An equally-specific rule without `!important` loses to it no matter what
    order the sheets load in, so overriding a theme that shouts requires
    shouting back. It is confined to this function, and a test asserts it appears
    nowhere else — `!important` in ARIES's own widgets would mean a specificity
    problem we should have fixed instead.

    WHAT IT DELIBERATELY DOES NOT DO
    --------------------------------
    No gradients, no blur, no shadows beyond one, no recoloured application
    windows, no icon theme. The brief asks for obvious, not decorative. The
    visible differences are: the panel's ground and its accent underline, square
    -ish corners where Yaru uses pills, normal weight where Yaru uses bold, and
    one radius everywhere a menu or a notification is drawn.
    """
    d = {name: css_colour(value) for name, value in DARK.items()}
    return textwrap.dedent(f"""\

        /* ══ ARIES over the session theme ═════════════════════════════════
         * Styles widgets GNOME creates, not ones ARIES creates. `!important`
         * is required here and only here: Yaru's own panel rules use it.
         */

        /* ── the top bar ───────────────────────────────────────────────── */
        #panel {{
            background-color: {d['bg_solid']} !important;
            height: {PANEL_HEIGHT}px !important;
            font-weight: 400 !important;
            box-shadow: inset 0 -1px 0 0 {d['border']} !important;
        }}
        #panel:overview {{
            background-color: transparent !important;
            box-shadow: none !important;
        }}
        #panel .panel-button {{
            border-radius: {RADIUS['sm']}px !important;
            border: 0 !important;
            padding: 0 {SPACE['sm']}px !important;
            color: {d['fg_dim']} !important;
            font-weight: 400 !important;
            transition-duration: {MOTION['instant']}ms !important;
        }}
        #panel .panel-button:hover {{
            background-color: {d['surface_hi']} !important;
            color: {d['fg']} !important;
        }}
        #panel .panel-button:active,
        #panel .panel-button:checked,
        #panel .panel-button:focus {{
            background-color: {d['accent']} !important;
            color: {d['accent_fg']} !important;
        }}
        /* The clock is the one thing on the bar everyone looks at. */
        #panel .clock-display,
        #panel .clock {{
            font-weight: 500 !important;
            color: {d['fg']} !important;
        }}
        /* ── the ARIES mark ────────────────────────────────────────────
         * The one thing on the bar that says whose desktop this is, so it is
         * the one thing allowed to use the accent colour at rest. Everything
         * else on the panel is foreground-dim until you touch it.
         */
        #panel .aries-mark-button {{
            padding: 0 {SPACE['md']}px !important;
        }}
        #panel .aries-mark-icon {{
            color: {d['accent']};
            margin-right: {SPACE['sm']}px;
        }}
        #panel .aries-mark {{
            font-weight: 600;
            font-size: {TYPE['body']['size']}pt;
            letter-spacing: 1.4px;
            color: {d['accent']};
        }}
        /* Pressed state you can actually see — the complaint that prompted it
         * was "I can't tell when I've clicked it". */
        #panel .aries-mark-button:hover {{
            background-color: {d['surface_hi']} !important;
        }}
        #panel .aries-mark-button:active,
        #panel .aries-mark-button:checked {{
            background-color: {d['accent']} !important;
        }}
        #panel .aries-mark-button:active .aries-mark,
        #panel .aries-mark-button:active .aries-mark-icon,
        #panel .aries-mark-button:checked .aries-mark,
        #panel .aries-mark-button:checked .aries-mark-icon {{
            color: {d['accent_fg']};
        }}
        /* GNOME 50 already draws workspace dots inside Activities. ARIES styles
         * those rather than adding a second set beside them. */
        #panel #panelActivities .workspace-indicator {{
            background-color: {d['fg_faint']};
            border-radius: {RADIUS['pill']}px;
        }}
        #panel #panelActivities .workspace-indicator:active {{
            background-color: {d['accent']};
        }}

        /* ── menus, popovers, quick settings ───────────────────────────── */
        .popup-menu-boxpointer,
        .quick-settings {{
            -arrow-border-radius: {RADIUS['lg']}px;
        }}
        .popup-menu .popup-menu-content,
        .quick-settings {{
            background-color: {d['surface']} !important;
            border: 1px solid {d['border']} !important;
            border-radius: {RADIUS['lg']}px !important;
            padding: {SPACE['sm']}px !important;
        }}
        .popup-menu-item {{
            border-radius: {RADIUS['sm']}px !important;
            padding: {SPACE['sm']}px {SPACE['md']}px !important;
        }}
        .popup-menu-item:focus,
        .popup-menu-item:hover {{
            background-color: {d['surface_hi']} !important;
            color: {d['fg']} !important;
        }}
        .quick-toggle, .quick-menu-toggle, .quick-slider {{
            border-radius: {RADIUS['md']}px !important;
        }}

        /* ── notifications ─────────────────────────────────────────────── */
        .message {{
            border-radius: {RADIUS['md']}px !important;
            background-color: {d['surface']} !important;
            border: 1px solid {d['border']} !important;
        }}
        .message:hover {{ background-color: {d['surface_hi']} !important; }}
        .message-list-placeholder {{ color: {d['fg_faint']} !important; }}
        .notification-banner {{
            border-radius: {RADIUS['md']}px !important;
            background-color: {d['surface']} !important;
            border: 1px solid {d['border']} !important;
        }}

        /* ── the overview ──────────────────────────────────────────────── */
        #overview {{ spacing: {SPACE['lg']}px; }}
        .search-entry {{
            border-radius: {RADIUS['pill']}px !important;
            background-color: {d['surface']} !important;
            border: 1px solid {d['border']} !important;
            color: {d['fg']} !important;
        }}
        .search-entry:focus {{ border: 2px solid {d['accent']} !important; }}
        .search-section-content,
        .dash-background {{
            background-color: {d['bg']} !important;
            border-radius: {RADIUS['lg']}px !important;
        }}
        .workspace-thumbnail-indicator {{
            border: 2px solid {d['accent']} !important;
            border-radius: {RADIUS['sm']}px !important;
        }}

        /* ── modal dialogs and the OSD ─────────────────────────────────── */
        .modal-dialog {{
            border-radius: {RADIUS['lg']}px !important;
            background-color: {d['surface']} !important;
            border: 1px solid {d['border']} !important;
        }}
        .osd-window {{
            border-radius: {RADIUS['lg']}px !important;
            background-color: {d['surface']} !important;
        }}
        """)


def as_dict() -> dict:
    """The tokens as data, served over the API so nothing has to guess them."""
    return {"space": SPACE, "radius": RADIUS, "type": TYPE, "motion": MOTION,
            "ease": EASE, "dark": DARK, "light": LIGHT, "severities": list(SEVERITIES),
            "panel_height": PANEL_HEIGHT, "dock_icon": DOCK_ICON,
            "dock_icon_small": DOCK_ICON_SMALL, "focus_ring": FOCUS_RING}
