"""Grid line and hex maths, and screen region parsing."""

import math
import re
import tkinter as tk


def square_lines(w, h, size, off_x, off_y):
    if size < 2:
        return []
    lines = []
    x = off_x % size - size
    while x <= w + size:
        lines.append((x, 0, x, h))
        x += size
    y = off_y % size - size
    while y <= h + size:
        lines.append((0, y, w, y))
        y += size
    return lines


def hex_polys(w, h, size, off_x, off_y, pointy=True):
    """Hex outlines as flat coord lists. `size` is centre-to-vertex."""
    if size < 2:
        return []
    if pointy:
        col_step, row_step = math.sqrt(3) * size, 1.5 * size
        angles = [math.radians(60 * k + 90) for k in range(6)]
    else:
        col_step, row_step = 1.5 * size, math.sqrt(3) * size
        angles = [math.radians(60 * k) for k in range(6)]

    ox, oy = off_x % (2 * col_step), off_y % (2 * row_step)
    polys = []
    for row in range(-2, int(h / row_step) + 3):
        for col in range(-2, int(w / col_step) + 3):
            if pointy:
                cx = ox + col * col_step + (col_step / 2 if row % 2 else 0)
                cy = oy + row * row_step
            else:
                cx = ox + col * col_step
                cy = oy + row * row_step + (row_step / 2 if col % 2 else 0)
            pts = []
            for a in angles:
                pts.append(cx + size * math.cos(a))
                pts.append(cy + size * math.sin(a))
            polys.append(pts)
    return polys


GEOMETRY_RE = re.compile(r"^\s*(\d+)\s*[x×]\s*(\d+)\s*([+-]\d+)\s*([+-]\d+)\s*$")


PANEL_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


def parse_geometry(text):
    match = GEOMETRY_RE.match(text)
    if not match:
        return None
    w, h, x, y = (int(g) for g in match.groups())
    return (x, y, w, h)


def cell_footprint(kind, cell):
    """How wide one cell is, edge to edge.

    A square grid's cell size is the length of a side. A hex grid's is the
    centre-to-vertex radius, which makes the hex about 1.73 times wider than
    the number suggests. Sizing a marker against the raw figure therefore came
    out far too small on hexes. Measuring the short diameter instead makes both
    grids behave the same, so the default looks right either way.
    """
    if str(kind).startswith("Hex"):
        return math.sqrt(3.0) * float(cell)
    return float(cell)


def safe_float(variable, fallback=0.0):
    try:
        return float(variable.get())
    except (tk.TclError, ValueError):
        return fallback
