"""Turning pixels into squares, and squares into distance."""

import math


DIAGONAL_RULES = ("Diagonal counts as one square", "True distance")


UNIT_CHOICES = ("ft", "m", "squares")


def snap_to_axis(x1, y1, x2, y2, tolerance=8.0):
    """Straighten a span that is nearly horizontal or nearly vertical.

    Held back behind the Shift key rather than applied automatically. It earns
    its place when calibrating, where a couple of degrees of hand wobble gets
    baked into the cell size as a permanent error, but snapping every line by
    default fights you the rest of the time.

    Returns (x, y, snapped).
    """
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return x2, y2, False
    angle = math.degrees(math.atan2(abs(dy), abs(dx)))
    if angle <= tolerance:
        return x2, y1, True
    if angle >= 90.0 - tolerance:
        return x1, y2, True
    return x2, y2, False


def grid_distance(dx, dy, cell, rule):
    """Distance in squares between two points, under the chosen diagonal rule.

    Most tables play the first rule: moving diagonally costs the same as moving
    straight, so a span three squares across and three down is three squares,
    not four and a bit. The second measures the true line, for tables that
    prefer the honest figure.
    """
    if cell <= 0:
        return 0.0
    across, down = abs(dx) / float(cell), abs(dy) / float(cell)
    if rule == DIAGONAL_RULES[1]:
        return math.hypot(across, down)
    return max(across, down)


def tidy_number(value, places=1):
    """Trim pointless zeros: 6.0 becomes 6, and 7.50 becomes 7.5.

    The check for a decimal point matters. Stripping zeros unconditionally would
    turn a whole number like 20 into 2 when places is nought.
    """
    text = ("%." + str(places) + "f") % round(float(value), places)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_measurement(dx, dy, cell, rule, per_square, unit):
    """The readout shown while and after measuring."""
    pixels = math.hypot(dx, dy)
    squares = grid_distance(dx, dy, cell, rule)
    parts = ["%d px" % round(pixels), "%s squares" % tidy_number(squares)]
    if unit != "squares":
        parts.append("%s %s" % (tidy_number(squares * per_square, 0), unit))
    return "   \u00b7   ".join(parts)


def cell_size_from_span(dx, dy, squares):
    """Work backwards: this span was N squares, so a square is this wide.

    Returns None when the answer would be meaningless, which keeps a stray
    click or an empty box from destroying an alignment that already worked.
    """
    try:
        count = float(squares)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    length = math.hypot(dx, dy)
    if length < 4:
        return None
    size = length / count
    if size < 8 or size > 400:
        return None
    return round(size, 2)
