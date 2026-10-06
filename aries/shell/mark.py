"""The ARIES mark, as data — drawn twice, defined once.

Aries is the ram, and the zodiac glyph ♈ is a pair of horns meeting at a brow,
so the mark is the name drawn rather than a metaphor added to it.

WHY THE GEOMETRY LIVES HERE AND NOT IN A FILE
---------------------------------------------
The mark is rendered in two places that cannot share code: the panel, by Cairo
inside `gnome-shell` in JavaScript, and the application icon, by Cairo here in
Python. The obvious answer — ship one SVG and point both at it — was the first
answer, and it failed twice for the same reason: **this machine has
`libpixbufloader_svg.so` on disk but not registered in the gdk-pixbuf loader
cache**, so nothing that goes through GdkPixbuf can rasterise an SVG. The panel
mark drew nothing; the dock icon drew nothing; the icon theme resolved the name
happily and produced an empty texture. Both times the failure was silent.

So the geometry is data, here, and everything is generated from it: the PNGs the
icon theme actually uses, and the SVG kept for systems that *can* render it. The
JavaScript draws the same coordinates, and a test asserts the two agree — the
same discipline as `tokens.py` generating both stylesheets, for the same reason.

The coordinates are on a 24×24 grid, which is the convention for symbolic icons
and keeps the numbers readable.
"""
from __future__ import annotations

# ("move" | "line", x, y) or ("curve", x1, y1, x2, y2, x3, y3)
PATH: tuple[tuple, ...] = (
    # the brow — the line both horns spring from
    ("move", 12.0, 20.0),
    ("line", 12.0, 8.0),
    # the right horn: out, over, and curling back in
    ("move", 12.0, 8.0),
    ("curve", 12.0, 5.2, 13.6, 3.4, 15.8, 3.4),
    ("curve", 18.6, 3.4, 20.6, 5.8, 20.6, 9.0),
    ("curve", 20.6, 11.9, 19.1, 13.8, 17.2, 13.8),
    ("curve", 15.8, 13.8, 14.9, 12.8, 14.9, 11.5),
    ("curve", 14.9, 10.4, 15.6, 9.6, 16.5, 9.6),
    # the left horn: the mirror
    ("move", 12.0, 8.0),
    ("curve", 12.0, 5.2, 10.4, 3.4, 8.2, 3.4),
    ("curve", 5.4, 3.4, 3.4, 5.8, 3.4, 9.0),
    ("curve", 3.4, 11.9, 4.9, 13.8, 6.8, 13.8),
    ("curve", 8.2, 13.8, 9.1, 12.8, 9.1, 11.5),
    ("curve", 9.1, 10.4, 8.4, 9.6, 7.5, 9.6),
)

GRID = 24.0
STROKE = 1.9                      # on the 24-grid, scaled with everything else
# Icon theme sizes. 16 is the smallest the horns stay legible at; below that the
# curls merge and it reads as a blob, which is why there is no 8.
SIZES = (16, 24, 32, 48, 64, 128, 256)
ACCENT = (0.357, 0.616, 1.0)      # tokens.DARK["accent"], #5b9dff


def trace(cr, size: float) -> None:
    """Lay the path onto a Cairo context scaled to `size`."""
    s = size / GRID
    cr.set_line_width(STROKE * s)
    cr.set_line_cap(1)            # ROUND
    cr.set_line_join(1)           # ROUND
    for segment in PATH:
        kind = segment[0]
        if kind == "move":
            cr.move_to(segment[1] * s, segment[2] * s)
        elif kind == "line":
            cr.line_to(segment[1] * s, segment[2] * s)
        else:
            cr.curve_to(*[v * s for v in segment[1:]])


def png(path: str, size: int, colour: tuple[float, float, float] = ACCENT) -> None:
    """Write one PNG. Transparent ground, so it works on any panel or dock."""
    import cairo

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    cr.set_source_rgba(*colour, 1.0)
    trace(cr, size)
    cr.stroke()
    surface.write_to_png(path)


def svg() -> str:
    """The same path as SVG, for systems whose icon loader can read one."""
    commands = []
    for segment in PATH:
        kind = segment[0]
        if kind == "move":
            commands.append(f"M {segment[1]} {segment[2]}")
        elif kind == "line":
            commands.append(f"L {segment[1]} {segment[2]}")
        else:
            commands.append("C " + " ".join(str(v) for v in segment[1:]))
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!-- GENERATED from aries/shell/mark.py. Do not edit; regenerate with
     ./scripts/aries-shell icons. The PNGs beside it are what actually renders
     on machines whose gdk-pixbuf has no SVG loader — which includes this one. -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <path d="{' '.join(commands)}" fill="none" stroke="currentColor"
        stroke-width="{STROKE}" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
'''
