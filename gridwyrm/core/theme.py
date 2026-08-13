"""Palettes, and the colour arithmetic the interface needs."""

import re


THEME_ROLES = (
    ("ink", "Window chassis"),
    ("panel", "Card surface"),
    ("field", "Input wells"),
    ("line", "Hairlines and borders"),
    ("mute", "Secondary text"),
    ("hilite", "Highlight"),
    ("text", "Primary text"),
)


ROLE_KEYS = tuple(key for key, _label in THEME_ROLES)


HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


STANDARD_PRESETS = ("#FFFFFF", "#B8C0CB", "#111111", "#E2483D", "#4A90E2")


SAFE_PRESETS = ("#FFFFFF", "#000000", "#E69F00", "#56B4E9", "#009E73")


THEMES = {
    "Dark": {
        "ink": "#171A21", "panel": "#1E222B", "field": "#272C37",
        "line": "#363D4A", "mute": "#788397", "hilite": "#A8B1C3",
        "text": "#DCE0E8", "presets": STANDARD_PRESETS,
    },
    "Light": {
        "ink": "#E7EBF1", "panel": "#F5F7FA", "field": "#FFFFFF",
        "line": "#C6CDD9", "mute": "#6C7686", "hilite": "#4A5566",
        "text": "#1E232B", "presets": STANDARD_PRESETS,
    },
    # Classic is not merely a light palette. `native` switches ttk back to the
    # operating system's own widget engine, so comboboxes, checkboxes and
    # scrollbars are drawn by Windows itself rather than restyled by us. That
    # is what produced the original look, and no palette can imitate it.
    "Classic": {
        "ink": "#F0F0F0", "panel": "#F0F0F0", "field": "#FFFFFF",
        "line": "#D0D0D0", "mute": "#6D6D6D", "hilite": "#0078D7",
        "text": "#000000", "onhilite": "#FFFFFF", "native": True,
        "presets": STANDARD_PRESETS,
    },
    "Colour-blind safe": {
        "ink": "#000000", "panel": "#0E1116", "field": "#191E26",
        "line": "#4C5666", "mute": "#9AA6B6", "hilite": "#FFFFFF",
        "text": "#FFFFFF", "presets": SAFE_PRESETS,
    },
}


THEME_ORDER = ("Dark", "Light", "Classic", "Colour-blind safe", "Custom")


THEME_NOTES = {
    "Dark": "One grey ramp. The highlight is a lighter step of the same ramp, "
            "never a separate colour.",
    "Light": "The same ramp inverted, with a darker highlight so it still "
             "stands out.",
    "Classic": "Windows draws the controls itself, exactly as it did before "
               "any restyling. Familiar, if plain.",
    "Colour-blind safe": "High contrast, and the grid presets switch to an "
                         "Okabe-Ito set that stays distinguishable under all "
                         "three common types of colour blindness. The "
                         "interface itself is greyscale already.",
    "Custom": "Seven colours, yours to set. Start from any theme above and "
              "change what you like.",
}


def luminance(colour):
    """Perceived brightness, 0.0 to 1.0."""
    try:
        c = colour.lstrip("#")
        r, g, b = (int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    except Exception:
        return 0.5


def resolve_theme(name, custom=None):
    if name == "Custom":
        merged = dict(THEMES["Dark"])
        merged.pop("native", None)
        for key, value in (custom or {}).items():
            if key in ROLE_KEYS and HEX_RE.match(str(value)):
                merged[key] = value
        merged["presets"] = STANDARD_PRESETS
        return merged
    return dict(THEMES.get(name, THEMES["Dark"]))


def apply_palette(colours):
    """Rebind the module-level colour names used throughout the interface.

    Themes must be switchable while running, and every reference lives inside
    a method, so rebinding here is enough for the next repaint to pick them up.
    """
    global INK, PANEL, FIELD, LINE, MUTE, HILITE, TEXT, ONHILITE
    global GRID_PRESETS, NATIVE_WIDGETS
    INK = colours["ink"]
    PANEL = colours["panel"]
    FIELD = colours["field"]
    LINE = colours["line"]
    MUTE = colours["mute"]
    HILITE = colours["hilite"]
    TEXT = colours["text"]
    # Whatever sits on top of the highlight has to stay readable by itself.
    ONHILITE = colours.get("onhilite") or (
        "#000000" if luminance(HILITE) > 0.5 else "#FFFFFF"
    )
    GRID_PRESETS = tuple(colours.get("presets") or STANDARD_PRESETS)
    NATIVE_WIDGETS = bool(colours.get("native"))


def hex_to_rgb(colour):
    """'#RRGGBB' to three floats in 0..1."""
    try:
        c = colour.lstrip("#")
        return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except Exception:
        return (1.0, 1.0, 1.0)


def rgb_to_hex(red, green, blue):
    """Three floats in 0..1 to '#RRGGBB'."""
    return "#%02X%02X%02X" % tuple(
        max(0, min(255, int(round(channel * 255))))
        for channel in (red, green, blue)
    )


def blend(colour, background, weight):
    """Mix `colour` toward `background`. weight 1.0 = pure colour."""
    try:
        c = colour.lstrip("#")
        b = background.lstrip("#")
        if len(c) != 6 or len(b) != 6:
            return colour
        out = []
        for i in (0, 2, 4):
            a_part = int(c[i:i + 2], 16)
            b_part = int(b[i:i + 2], 16)
            out.append(int(round(b_part + (a_part - b_part) * weight)))
        return "#%02x%02x%02x" % tuple(max(0, min(255, v)) for v in out)
    except Exception:
        return colour


def contrast_halo(colour):
    """An outline that will show against the colour it surrounds.

    Every band is drawn twice, a wider outline under a narrower fill, because
    the map beneath is unknown. A pale band needs a dark outline and a dark one
    needs a pale outline, or half the ring disappears into the terrain.
    """
    return "#FFFFFF" if luminance(colour) < 0.45 else "#000000"


KEY_COLOR = "#0b0c0d"


MEASURE_WASH = "#0B0F16"


MEASURE_ALPHA = 0.42


MIN_REVEAL_MS = 700                          # a tapped reveal still has to be seen


apply_palette(THEMES["Dark"])
