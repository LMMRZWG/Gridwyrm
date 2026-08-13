"""Named range bands and the rings they become."""

from .rows import validate_rows

from .measuring import tidy_number


DEFAULT_BANDS = (
    ("Melee", 5.0),
    ("Close", 10.0),
    ("Near", 15.0),
    ("Far", 25.0),
)


RANGE_MODES = ("Off", "DM only", "Show players")


MAX_BANDS = 8


def parse_bands(text):
    """Read 'Name = distance' lines. Returns (bands, error message).

    One band per line keeps this editable without a row of widgets per band,
    and lets someone with a ten-band system just type it.
    """
    bands = []
    for number, line in enumerate(str(text).splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            return None, "Line %d needs a name, then =, then a distance" % number
        name, _, value = line.partition("=")
        name = name.strip()
        if not name:
            return None, "Line %d has no name" % number
        try:
            distance = float(value.strip().replace(",", "."))
        except ValueError:
            return None, "Line %d: %s is not a number" % (number, value.strip())
        if distance <= 0:
            return None, "Line %d: the distance has to be above zero" % number
        bands.append((name, distance))
    if not bands:
        return None, "Give at least one band"
    if len(bands) > MAX_BANDS:
        return None, "%d bands is as many as stays readable" % MAX_BANDS
    bands.sort(key=lambda pair: pair[1])
    return bands, ""


def _distance(text):
    value = float(text.replace(",", "."))        # a comma decimal is fine
    if value <= 0:
        raise ValueError("the distance has to be above zero")
    return value


def validate_bands(rows):
    """Check name and distance pairs from the editor.

    Separate from parse_bands, which reads the text kept in the settings file.
    Returns (bands, error message), sorted by distance so the order they were
    typed in does not matter.
    """
    bands, error = validate_rows(rows, _distance, MAX_BANDS, "distance", "bands")
    if not bands:
        return None, error
    bands.sort(key=lambda pair: pair[1])
    return bands, ""


def format_bands(bands):
    return "\n".join("%s = %s" % (name, tidy_number(distance, 2))
                     for name, distance in bands)


def band_radii(bands, cell, per_square):
    """Turn each band into a ring radius in pixels.

    Distances are given in whatever unit the panel is set to, so they go
    through squares to reach pixels: a 30ft band with 5ft squares and 64px
    cells lands at six squares, which is 384 pixels.
    """
    if cell <= 0 or per_square <= 0:
        return []
    return [(name, (distance / float(per_square)) * float(cell))
            for name, distance in bands]


def visible_rings(rings, width, height):
    """Split bands into the ones worth drawing and the ones that will not fit.

    A ring wider than the screen is not a range indicator, it is an off-screen
    arc, and at a large cell size the outer bands go that way quickly. Keeping
    the radius inside half the shorter edge means a centred ring is fully
    visible and an off-centre one still mostly is. The rest are named in the
    panel instead, so their absence is stated rather than mysterious.
    """
    if width <= 1 or height <= 1:
        return list(rings), []
    limit = min(width, height) / 2.0
    fits = [(name, radius) for name, radius in rings if radius <= limit]
    too_big = [name for name, radius in rings if radius > limit]
    return fits, too_big


RING_WEIGHT_PRIVATE = 1


RING_WEIGHT_REVEALED = 3
