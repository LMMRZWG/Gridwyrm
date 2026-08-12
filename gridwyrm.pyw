#!/usr/bin/env python3
"""
Gridwyrm - a transparent grid overlay for tabletop maps.

Pick a screen, and a square or hex grid is drawn over everything on it. A
control panel on your other screen tunes cell size, offset, colour, line weight
and opacity live, so you can line the grid up against a map.

Double-click this file to run it. The .pyw extension makes Windows use
pythonw.exe, so no console window appears.

To watch for errors instead, run it from a terminal you already have open:

    python gridwyrm.pyw

The console stays in that case, because it belongs to the terminal rather than
to Gridwyrm, and errors print there as well as to the log files.

Stdlib only: Python 3.8+ with tkinter.
  Windows 10/11 - invisible background, real click-through, dark window frame.
  Linux/macOS   - runs, but the background shows as a faint tint and clicks
                  cannot pass through.

Settings, and three log files, live in the Gridwyrm folder inside %APPDATA%.
"""

import base64
import colorsys
import faulthandler
import json
import math
import os
import re
import struct
import sys
import tempfile
import threading
import time
import traceback
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, ttk

# Optional. When present, images are resized smoothly and JPEG works too;
# without it Tk still handles PNG and GIF on its own.
try:
    from PIL import Image, ImageTk
    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

IS_WINDOWS = sys.platform.startswith("win")

# Rendered fully see-through, and click-through, on Windows.
KEY_COLOR = "#0b0c0d"

# Used while measuring, when the overlay has to catch the mouse. See
# Overlay.set_measure_surface for why the background cannot stay invisible.
SHIFT_HELD = 0x0001                          # the Shift bit in a Tk event state
MIN_REVEAL_MS = 700                          # a tapped reveal still has to be seen
MEASURE_WASH = "#0B0F16"
MEASURE_ALPHA = 0.42

# --- themes ---------------------------------------------------------------
# A theme is seven colour roles, ordered darkest surface to brightest text
# (or the reverse, in a light theme). Everything else is derived from these,
# which is what makes a hand-rolled custom theme practical: seven decisions,
# not fifty. The highlight is never a separate hue - in each built-in theme it
# is simply a step of the same ramp that stands out against its neighbours.

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

# Grid line colours. These are content - what actually gets drawn on the map.
STANDARD_PRESETS = ("#FFFFFF", "#B8C0CB", "#111111", "#E2483D", "#4A90E2")
# Okabe-Ito: chosen to stay distinguishable under deuteranopia, protanopia
# and tritanopia, which is the part of this app that colour vision affects.
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


# Sample-map colours for the preview. These are deliberately fixed rather than
# themed: the point is to judge a grid colour against the tones it will really
# sit on - grass, stone, timber, tile - and those do not change with the
# interface theme.
MAP_GRASS = "#4E6B37"
MAP_GRASS_DARK = "#425C2E"
MAP_TREE = "#2C4321"
MAP_TREE_LIT = "#3A5A2B"
MAP_PATH = "#8B8679"
MAP_PATH_DARK = "#6E695E"
MAP_WALL = "#B7B1A2"
MAP_WOOD = "#6E4A2C"
MAP_WOOD_DARK = "#57391F"
MAP_TILE = "#C6C0B1"
MAP_CARPET = "#7C2F2A"
MAP_DARK = "#241C16"
# Representative mid tone, used to fade the grid when opacity is below full.
MAP_MID = "#6A6353"


def deterministic_noise(seed):
    """Repeatable pseudo-random value in 0..1.

    The sample map must look identical on every repaint - a texture that
    shimmered while dragging a slider would be worse than no texture at all.
    """
    value = (int(seed) * 1103515245 + 12345) & 0x7FFFFFFF
    value = (value ^ (value >> 13)) & 0x7FFFFFFF
    return value / float(0x7FFFFFFF)


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


apply_palette(THEMES["Dark"])

if IS_WINDOWS:
    import ctypes
    import winreg
    from ctypes import wintypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor v2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# --- window icon ----------------------------------------------------------
# The Gridwyrm mark, embedded as base64 PNG at three sizes.
#
# PyInstaller's --icon option sets the icon on the .exe file, which is what
# Explorer and the taskbar shortcut show. It does nothing for the Tk window
# itself, which keeps its default feather until told otherwise. Embedding the
# images rather than reading icon.ico from disk means this works identically
# when run from source and when run from a packaged one-file build, where
# there is no icon.ico sitting next to the program.

ICON_PNG_64 = """\
    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
"""

ICON_PNG_32 = """\
    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
    gH7E/4f1N4+S+gm29SgFAAAAAElFTkSuQmCC
"""

ICON_PNG_16 = """\
    iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAC00lEQVR42j2T3WpcZRhG1/ez
    9549M81MptPQ2EzaRCUYsUVQEIQeeCKCV+Gxd+OFqOBxL0KKEJBGLZ00zF8yf3v29+3vfT1I
    9LmCBc9aJu8OzsOuetnr96Xb3TNYR4yRzFkAUgIQ/p+zNHWl08nc5mXrlbG+/LH/6PCnTm9A
    bBpCiHTaJXVdo6p470EVMGBAVXHWEusti+vxD743GITywX6azuepU+Tu0cN9FrMpT45GjK/e
    M5/PcM5jAMVgrCHFKHt7PXs4Oo223d03VbV1FnXr1a0zcec+f/Hc7da37uuvvnSfnn3s6u3G
    qYhzRp0RdRZ1u2rjsqJtbJKISoM0DWB4N75iMpnw9Okz5rMZ55+c8d2339ApCzbbLdY5VAVV
    JcoOLwk0CTHUtFs5/f6Avy8vsQhPjk8o2x2GwyEnJyf88utvXF9PcM6ikiAlLCI0qaHIM07P
    zlntAsHl3Cw3jMdjYoxcvh2zWO948fwzQqgRSYgKISVca6//RQjx+8xZDU2ym9WSXv8hMQSW
    ixmb9Ya8KNisNxwcPOb09JjZdKLL1dp0ys7PXpKAQlKwPqNotXDGsH/wmDcXv3P19i+KdpfD
    o2Pm0wkfHI3uXhUhieCRBCqklNiubql3WyQJo9GILG+BLwgx8u6fS1IS/rz4g+VmTZaXSEj4
    BIgqRoSi7IAxqBoWizmjZx8SQmRbVQgweT+mjhHr/b2WCUsSUCXFSNxtqdYrUtjx5uI1t8sl
    o9OPGA6HGGOoU8JnOQaDqpCIeJEExtCkhlgHfFaQlW2apuH6akyn3abzoIeqsri5AXPn5D0A
    Pta1mqxIxvu0Xs7xzqOpoQk1xljm02uqaktRdsizjDrUGIxYZzTGoD6mkHtjXO4zp86jkmjq
    Hc4YrLWYoiTFSC0rUMU7hzHWqQhVXWUm7w7OmxheOhCfFeYuXoF0z4gD91/XDussIo3GEKwv
    O6/+Bbx6nkQil0xlAAAAAElFTkSuQmCC
"""


# The same mark again, this time as a complete .ico with classic BMP entries.
#
# Two icons are embedded because two mechanisms need feeding and they accept
# different things. The title bar takes images from memory through iconphoto,
# which is happy with PNG. The taskbar button needs iconbitmap, and Tk reads
# that file itself rather than handing it to Windows - its reader only
# understands classic DIB entries, so a modern PNG-compressed .ico is loaded
# without complaint and silently ignored. Hence a second, DIB-format copy at
# three sizes, which costs about twenty kilobytes.

ICON_ICO = """\
    AAABAAMAEBAAAAEAIABoBAAANgAAACAgAAABACAAqBAAAJ4EAAAwMAAAAQAgAKglAABGFQAA
    KAAAABAAAAAgAAAAAQAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABIMBioMBwJoDAcFZhMM
    CWcTDAlnEQwHZxEJB2cOCQdnEQkHZxEMB2cOCQdnEQkHZxMMCWcPCgdmCQQCaBQNBiYLBwJs
    EgsG/xYOCP8VDQf/EgsG/xMLB/8UDAj/Fw4K/xQMB/8TCwf/Fg4K/xUNCf8TDAb/FQ0H/xQM
    B/8NBwJhEQoHZhgPCPwRCgL5DQcC/BEKBvwbEgv8EwsF/BUMBvwLBQH8GBAK/CMZEfwXDwn8
    EAkC/BEJA/oWDgj8GBALXBgRDGcYDwf/DQYB/B8VDv8fFQz/KR4S/xoRCf8YDwj/IhkT/zEm
    Hv8iGhT/EgoD/xQMBf8SCwT9FQ0G/x4VEF0bEw5nFw4H/xEJBfwlHBP/GBAI/x4VDf8SDAf/
    Migf/zwyKP8jGxX/EAkE/w8IAf8TCwX/EgoE/RUNBv8eGBBdHRYOZxgPB/8WDgj8LyQY/yUc
    Ef8mGxD/PjMp/0A2Lv8YEAv/DwcB/w8IA/8SCwj/DQYB/xEKA/0XDgf/IxgTXR0WEWcZEAn/
    GBEJ/CQbEf8aEwr/IhgP/1BEOv8dFhH/CwQA/wsFAf8NCAX/LCMd/xoTEP8OCAL9Fw4H/yYY
    E10gGBFnGxEJ/x0UDPwzKBv/JBsR/zMnHf9DNy7/FRAM/wQAAP8QCgf/LiYg/0Q6NP9hVk7/
    Jh4Y/RMKA/8pHhVdIhsTZxsSCf8dFQ/8LiQZ/xwTCv8yJhr/KyEa/yQdGf8+NjH/V05G/1lO
    Rv9xZl//X1hR/yYfGf0VDAP/KyAYXSUbFmcfFQz/GxIL/EY7MP8mHBH/IxkN/zEpJP9DOzX/
    b2dg/2NZT/9xZ1z/WlJM/xEHAP8XDgf9HBMK/ysjGF0nHRZnIxgQ/xYMBPwcFA7/LCQe/x0W
    E/88NzT/XVVP/3RsZf99dnD/eXNt/y0kHf8YDQb/GhAJ/R4UDP8uJh5dJyAYZyUbEf8dEgn8
    GhAI/xgRDf8+NzL/U0xI/0xFQP9pYlz/WFJM/yYcFf8XDAL/JRgO/xsRCf0hFg3/MSkeXSwi
    G2cpHRL/IRYL/BkQCP8xKyj/U0xH/zMtKf9fWFL/Qjky/xYLA/8fEwr/IRYN/yIVDP8dEgr9
    IhcO/zkrI10bFhFmMyYb/CIWCfkoHRT8OTAn/CUdFvxCOTH8KiAX/B0SB/whFQr8IRUL/CIV
    CvwjFwv8HhII+i0gFvwvJB5cCQQCbCIZEv80KB3/MCQY/yseEv80KB3/LSEW/ywgFf8wJBn/
    LyMZ/zAjGf8wJBn/LyMY/zElG/8nHhb/DQcFYRIMBioJBABoGRQPZicgG2cqIhtnJR0WZycg
    G2cnIBtnJx0YZyUdGGclHRhnJR0YZycgGGceGRRmDAQAaBQNBiYAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAKAAAACAA
    AABAAAAAAQAgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAA8JA4gQCQS7CwUBuAYEAboPCAW6EQwIuhMMCboRDAm6EQoJuhEKCLoUCgm6EQwIuhMM
    CboQDAi6EwoIuhAKCLoRCgi6EwoJuhEMCLoTCgm6EQwIuhEMCLoTCgm6EAwIuhMKCLoPCga6
    CgQCugYEALcQCQS7EAoEewAAAAAAAAAAEAoDxQwHAv8NBwT/GRIM/xwRDP8YEQn/GRAK/xcQ
    Cf8ZDwr/Fg8I/xcMCP8RDAf/FQsJ/xMOCf8WDAn/FQ0J/xQNCf8VDAr/EgwI/xUMCf8TDAn/
    EwwJ/xcNCf8XEAj/GQ4J/xcRCf8cEQz/EQoH/w0HAv8RCgSyAAAAAAAAAAANCAK4DggF/B4S
    DfkTDAT8EQkD/A8JAvwPCAP8DgkC/AwEAfwJBQH8EAgF/BEMB/wVCwj8FxAJ/BwQC/wRCwb8
    EwwG/A8IBPwTDQn8GBAL/BYOCvwYEQr8EwoH/A4IAfwQCQP8DwgC/BAJA/wcEg34FA4J/AwE
    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
    C/8YEAj/DAQA/wsHBf+Bd3D/e3Rs/xgWFP8AAAD/UEhA/2teVf+KhX//NSwn/xIIAf8YDwb/
    HREI/x4UC/8dEwr/HhML/yAVC/8eEgv/HRMK/x4TC/8aEAj7IxcO/zsvJ6gAAAAAAAAAACkg
    Gro1Jxv/HxQJ/CQYDf8iFwz/IBUM/xILA/8aFhT/eXFu/2RfWf8HAAD/DQkH/2tgW/9rZl7/
    e3Ry/zcwKf8UBwD/IBUN/x8UC/8hFQv/HxQK/x4TCv8gFAv/IhcM/yATC/8fFQv/HxML/xsR
    CPslGRD/PjAoqAAAAAAAAAAAHhcRuj0wI/8gFAn8JhoO/yQYDv8gFAn/NCsm/2djX/9GPDb/
    DgYA/xwTD/97dm//T0U//x8YEP82LSj/Gg8D/yYaDv8hFQv/IhYM/yMXDP8iFgz/IRUM/yQW
    Df8qHA7/IxYN/yAWC/8iFQ3/GxEH+y4hFv8+LSeoAAAAAAAAAAAKBQG6PzIp/zEjFvwfFAj/
    JhkO/yUZDf8rHxX/HxUK/x0QBf8bEAf/U01J/0A5Mf8WCgD/IhcM/x8TCf8kGQ7/JRgN/yMY
    Df8kGA3/JBgN/yQYDv8kGA3/JhkO/ycbD/8kFw7/IhcN/yEUC/8bEgf7QTQp/xwSD6gAAAAA
    AAAAAA0IArgWDwv8STwx+TQnGvwkFwv8IRcK/CEUCPwiFwv8IhcL/CEWCvwkGxD8GxAE/CIX
    DPwfFQr8IhYM/B8VCvwgFAr8HhQJ/B8UCvwfFAn8IRUK/CAWCvwhFQv8HxYK/CAUCvwdFAn8
    KBoR/Ec6L/gnIRr8DAQBpgAAAAAAAAAAEgsGxREKBP8VDgr/OjAn/0U2K/9CNin/RDUp/0M0
    KP9BNSj/RDQp/0A0J/9DNSn/QTQo/0A0KP9DNCn/QDUo/0IyKP9ANSj/QjQp/0E1Kf9DNCn/
    PzQo/0IzKP8/NCf/QjIp/z81Kf9DNi7/IxsW/w4JAv8UDAeyAAAAAAAAAAAQCwWIEwwGuw8J
    ArgIBAC6FA8JuhwXEboeFRG6HhURuhwXEboeFxO6HBcTuhwVEbocFRG6HBcRuh4XE7oeFxG6
    HBURuhsXEboeFRG6GxURuhwVEbocFxG6HhURuhwXEbofFxO6GhQPugwGAroLBQC3FA0GuxIK
    BnsAAAAAAAAAAAAAAAAAAAAAAAAAAAEBAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACgAAAAwAAAA
    YAAAAAEAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAABhMNBicNBgYnDQYAJw0GBicNDQYnBgYAJwAAACcAAAAnAAAAJwAA
    ACcAAAAnAAAAJwAAACcAAAAnAAAAJwAAACcAAAAnAAAAJwAAACcAAAAnAAAAJwAAACcAAAAn
    AAAAJwAAACcAAAAnAAAAJwAAACcAAAAnAAAAJwAAACcAAAAnAAAAJwAAACcAAAAnAAAAJwAA
    ACcAAAAnBgAAJxMGBicNBgAnDQYAJwwGBigNDQYlAAAAAwAAAAAAAAAADQ0GJxAKBP8OCAP/
    DgkD/w0HA/8GAgD/BwUC/w8IBv8SCwj/EQ4J/xUMC/8TDAr/EA4J/xULCv8SDAn/EQ0I/xYL
    C/8RDQn/Eg0J/xYMC/8SDgn/Eg4J/xUMCv8TDQn/Eg0I/xMMCf8VDAr/Eg0J/xINCf8VDAv/
    Eg0J/xQNCv8UDQr/EQ0J/xYLCv8RDQj/EQwI/xULCv8PCwf/CwcD/wgCAf8HBQH/DQgC/hEI
    BP8QCgTvDAwAFAAAAAAAAAAAEw0GJxAJBP8NCAP/CgUC/gcCAf8UDgr/HxcQ/yIUD/8cEw3/
    GhUM/x8SDv8cEw3/GRQL/x8QDf8ZEgv/GRIL/yAQDf8YEwv/GBAL/xsODP8VDwr/FQ4J/xgM
    C/8WDQr/FA4J/xYNCv8YDAv/Fg8K/xYOCf8ZDQv/FQ4K/xcNCv8XDgv/FA8J/x0PDP8aEwv/
    GRIL/x4QDf8bFQz/HRcO/x8SD/8LBwT/BgQA/xAIBP8QCQPuDAwAFAAAAAAAAAAAEw0GJxAJ
    BP4LBgL+CAMB/SAUD/4eFQ3+EgsE/hIJA/4PCQL+DQkB/g8HA/4NCAH+DAgB/hAGA/4LCAH+
    CgUA/goBAP4FAwD+CAMB/g8GBf4NCgb+EgwH/hMJB/4RCgf+DgsF/g8JBf4RCAX+BwUB/gwH
    Bf4QCAb+CwgF/g4HBv4NCAX+DgoG/g8FA/4NCAH+DAkB/hEHA/4OCAL+DQoC/hgMCP4kFxL+
    EQwI/QoFAf8RCQTuDAwAFAAAAAAAAAAAEw0GJw8JA/8HAwH/IBUR/hwQC/8NCAD/EQoE/xQK
    Bf8RCwT/EQoE/xIJBf8PCQP/EAkE/w8FA/8HBAD/DAcE/xYLCf8XEgv/HBIN/x8PDf8VDwf/
    KBwR/xwPC/8VDAf/Ew4G/xUMBv8WCwb/DAgE/yAVEP8eEw3/GhQN/x4SDf8dFA3/HRcO/xMI
    Bv8SCgP/EAwD/xMKBf8SCQT/DwsC/w8IAv8TCQX/IhsT/hAKB/8MBQLuGQwMFAAAAAAAAAAA
    Ew0GJwsFAf8VDgr/IBUP/g4HAf8SDAP/EgsE/xMKBP8QCwP/EQkE/xAIA/8NCQP/CAMA/w0G
    BP8UEAr/KBwT/yoaFP8NCQP/DwgC/xIHA/8MBwL/HBIJ/xIHBP8MBgH/DAcB/w4GAv8IAgD/
    Ew0J/yEVD/8aEgz/GRMM/x0RDf8dFQ3/FxIL/w8GA/8TCwP/DwsC/xEJBP8TCQT/DwoC/xIL
    BP8UCAX/EQwF/iEaEf8NBQTuDAwAFAAAAAAAAAAADQYGJwwGA/8hGBH/FAsF/hMLA/8RCwP/
    EwoE/xIKBP8QCgP/EAgD/w4HAv8FAgD/FA0K/yMXEv8SDAb/HxQM/yQYEP8LBgH/EQoD/xQJ
    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
    fv9eWVX/XVlY/ysoJP8jHxv/OzQu/1JHP/+moZr/My8q/2pkYf9UTEn/EQQA/yAVC/8gEwr/
    IRQL/yIUCv8/KRX/LRwO/yMUC/8gFQv/HxML/yQUDP8fFAr/GBAI/iETC/89MSfuAAwAFAAA
    AAABAQEAAAAAJywiHP84LCD/GhAI/iEVDP8gFQv/IBUL/x8UC/8dEwv/GxEK/xYPB/8WDgb/
    FQoG/wgHA/8EAgL/XVJP/5eShf+blIv/bmdl/yopKP8BAAH/KyAb/zwvJv83Lib/hXpx/4qC
    fv9KRkH/BwAA/zcyLf8eEw3/HhMH/xsSCf8eEgr/HhMK/x0SCv8oGw7/IRUM/x8SCv8cEwr/
    HBMK/yASC/8cEgr/GBEI/iASC/8/MinuAAwAFAAAAAABAQEAAAAAJysiHP85LB//GxEI/iIX
    DP8hFgv/IRUL/x8VDP8eEwv/GxAK/xYOBf8TCwT/EQgG/wAAAP9VTkj/pJKM/35+dv80MS7/
    CAEA/wAAAP8wKyb/dGRb/0k9Nf+TjIT/hIF7/xsSDf8UCQP/HRQJ/xYMA/8fEQr/HxQK/xwS
    Cv8eEwv/HRML/x0SC/8jFgv/HhQL/x8SC/8dEwr/HBQK/yASC/8cEQn/GRII/iATDP9AMyru
    AAwAFAAAAAABAQEAAAAAJywjHP87LSD/HRII/iMYDP8iFwz/IxcM/yEXDP8eFAv/GxAK/xUO
    Bv8OCAT/AAAA/0Q+Of+emI7/b2Vh/xMOCv8CAAD/AwAA/y0nI/+Bem//a2Jb/4B4c/+KiIP/
    Fw8J/xwOBv8fFAz/GxIJ/x4TC/8gEwr/IBUL/x0TCv8eEwr/HhQL/yAUC/8lGAz/HxUL/yAT
    C/8eEwv/HRQK/yASC/8dEgr/GhMI/iEUDP9AMyruAAAAFAAAAAABAQEAAAAAJyohGv89MCL/
    HhIJ/iQZDf8jGAz/JBcN/yIXDP8gFgv/HxML/xAJAf8FAgD/WVBO/6Kalv9ZWFP/EwgE/xAI
    BP8KCQX/SD05/46DfP9wbmb/RD46/5eQjv8eFhD/GhAG/yEUDP8eEgr/HRQK/x8UC/8hFAv/
    IBYL/x4TCv8eEwr/HxUL/yEUC/8jFwz/HxUL/yITDP8fFAv/HRQK/yATDP8eEwr/GhMI/iMW
    Df9DNS7uAAAAFAAAAAAAAAAAAAAAJx8YE/9HOiz/HxQJ/iYaDv8kGA3/JBgN/yQYDP8iGQz/
    IRQK/zUvK/97e3f/g315/zsyLf8PCQD/GxAK/wgAAP9lYlr/mJCK/0lAPP8QCwX/RT46/z00
    MP8UCgH/JRoN/yIVC/8hFAz/IBYM/yIWDP8jFgz/IhcL/yEUC/8gFAv/IBYL/yIUDP8pHA3/
    IxgM/yMTDP8gFgv/HxUK/yIUDP8gFAv/GRIH/i0fFf9GNi/uAAAAFAEBAQAAAAAAEw0GJw0I
    A/9OQDX/LB0S/iMXDP8lGQ3/JRkN/yQYDf8kGQ3/JBgO/0Q7Nv85Mir/FwwE/xsOBf8iGA7/
    DQUA/1BHRP+Oi4X/KCIa/xkLA/8gFgv/HxYM/x0RCP8iFwz/JhkN/yUYDP8jFgz/IhgM/yMX
    Df8kFw3/JBoN/yQXDf8jFw3/IxgN/ycXDv8wIRD/JxsO/yUVDf8iFwz/IRcM/yMVDP8jFw3/
    FA4D/kU0KP8wIhzuAAAAFAEBAQAAAAAAGhMNJwsFAP8qIRz/V0U3/h4SBv8mGw7/JxoO/yUZ
    Df8kGg3/JhkO/x4RBv8dEwX/JRkO/yUYDv8gFAn/IRoT/3Nta/8kHBP/GxEF/ycYD/8iFwz/
    IhYM/yQXDf8iFwz/IhcM/yMWDf8iFw3/IhcM/yMXDP8jFw3/IhcM/yQXDf8jFwz/IxgM/yUX
    Df8iGQ3/IhcN/yMVDf8gFgv/IRcM/yYXD/8aDwb/KCAT/lBANv8PBgTuGRkMFAAAAAAAAAAA
    Ew0GJxINBf8HAgD/QzYw/lFDM/8gFQn/IhUJ/yUZDf8kGg3/JhoN/ygaD/8mGg//JBoN/yUZ
    Dv8kFgv/KSAV/ycdFP8hFQr/JRsP/yUYDf8jGQ3/JRkO/yUZD/8kGg3/JBkN/yQYDf8kGA3/
    IxgN/yUXDv8kFw3/IxgN/yYYDv8kGQ7/JRoO/ycYD/8kGg7/JRgN/yUXDv8hGAz/HxUL/xsN
    Bv8tIBb/WU9B/hsUEP8QBwTuJhkMFAAAAAAAAAAAEw0GJxALBf4SCwb+CgMC/T0zLP5XSTv+
    PC0g/iodEP4kGQz+IxkM/iUYDP4kGA3+IRkM/iIXC/4kFw3+HxYJ/iEVCv4kGA3+IBcL/iIW
    DP4gFwz+IhcM/iMXDf4hFwv+IBYL/iIWDP4fFgv+IBYL/iIWDP4gFgv+IRcM/iQYDf4gGAv+
    IhcM/iQWDP4hGAv+IRcM/iMWDf4gGAv+KSAU/ks5L/5bS0D+HBkT/QsHAv8VDAfuDAwAFAAA
    AAAAAAAAEw0GJxELBf8RCwb/FAwG/gkEAP8eGRT/Rjox/1FDOP9TRTj/U0Y4/1VEOP9VQTf/
    UEU3/1NFN/9XQzn/UUc4/1NEOP9TQjb/UEU3/1RCOP9RQzf/UEM2/1VCOf9QRTf/UUM3/1NC
    N/9QRTf/UkU5/1RCN/9QRTj/U0Y5/1ZCOP9OQzb/UUI2/1RBN/9ORDX/UEE2/1RBOP9ORDb/
    TkM4/zovKf8QCgf/CwcC/xQNB/8SCgXuGQwAFAAAAAAAAAAADQ0GJxELBf8SCwX/EgsF/xMN
    Bv8NCAL/CQQA/w8KBv8WEAz/FhEN/xcRDf8ZEA3/FRIM/xcSDf8aEQ7/FRMN/xcRDv8XEA3/
    FhEM/xgQDf8WEQ3/FhIN/xkRDv8XEw3/FxEN/xcQDP8VEQz/FxEN/xcQDf8VEQz/FxEN/xcQ
    Df8WEg3/GBEO/xgRDf8WEgz/GBEN/xkSDv8TEAr/DQcD/wkEAP8QCwX/EgwF/hILBf8SCgXv
    DAwAFAAAAAAAAAAAAAAABhMNBicTDQYnEw0GJw0NBicTDQYnGhMNJxMNBicGAAAnAAAAJwYA
    ACcGAAAnAAAAJwYAACcGBgAnAAYAJwYGACcGAAAnBgAAJwYAACcGAAAnBgAAJwYAACcGBgAn
    BgAAJwYAACcAAAAnAAAAJwAAACcGAAAnBgAAJwAAACcGAAAnBgAAJwYAACcGAAAnBgYAJwYG
    ACcGBgAnExMGJxoTDScTDQYnEw0GJxMMBigUDQYlAAAAAwAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
    AAAAAAAAAAAAAAAAAAAAAAAAAAA=
"""


def claim_taskbar_identity():
    """Tell Windows this program is its own application.

    Without an explicit identity, a Python program can be grouped under the
    interpreter or the toolkit, and the taskbar shows their icon instead of
    ours. This has to run before any window exists.
    """
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "LMMRZWG.Gridwyrm")
    except Exception:
        pass


# ==========================================================================
# Silent launch
# ==========================================================================

def hide_own_console():
    """Hide the console window, but only if this process owns it.

    Double-clicking the .pyw means no console exists and this does nothing at
    all. It matters if the file is ever renamed to .py and double-clicked,
    where python.exe opens a console of its own.

    The ownership check is the important part: a terminal you opened yourself
    belongs to that terminal, not to Gridwyrm, so it is left alone. That is
    what makes "python gridwyrm.pyw" a usable way to watch for errors.
    """
    if not IS_WINDOWS:
        return
    try:
        kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
        console = kernel32.GetConsoleWindow()
        if not console:
            return
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(console, ctypes.byref(owner))
        if owner.value == kernel32.GetCurrentProcessId():
            user32.ShowWindow(console, 0)        # SW_HIDE
    except Exception:
        pass


# ==========================================================================
# Windows window plumbing
# ==========================================================================

def hwnd_of(window):
    handle = ctypes.windll.user32.GetParent(window.winfo_id())
    return handle or window.winfo_id()


def set_frame_mode(window, dark=None):
    """Match a window's native title bar to the current theme.

    Applies to every window we open, not just the main panel - a light title
    bar over a dark dialog is the most obvious way for a Tk program to look
    unfinished. The repaint is forced through SetWindowPos rather than by
    hiding and reshowing the window, which would blink and, for the main
    window, briefly take the overlay down with it.
    """
    if not IS_WINDOWS:
        return
    if dark is None:
        dark = luminance(INK) < 0.5
    try:
        window.update_idletasks()
        hwnd = hwnd_of(window)
        flag = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):               # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(flag), ctypes.sizeof(flag)
            )
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_FRAMECHANGED = 1, 2, 4, 0x20
        ctypes.windll.user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )
    except Exception:
        pass


def screen_dpi(window):
    if IS_WINDOWS:
        try:
            return float(ctypes.windll.user32.GetDpiForWindow(hwnd_of(window)))
        except Exception:
            pass
    try:
        return float(window.winfo_fpixels("1i"))
    except Exception:
        return 96.0


def list_monitors():
    """[(x, y, w, h), ...] per display, in virtual-desktop coordinates."""
    if not IS_WINDOWS:
        return []
    rects = []
    enum_proc = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(wintypes.RECT), ctypes.c_void_p,
    )

    def callback(_mon, _dc, lprect, _data):
        r = lprect.contents
        rects.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return 1

    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, enum_proc(callback), None)
    except Exception:
        return []
    return rects


GEOMETRY_RE = re.compile(r"^\s*(\d+)\s*[x×]\s*(\d+)\s*([+-]\d+)\s*([+-]\d+)\s*$")
PANEL_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


def parse_geometry(text):
    match = GEOMETRY_RE.match(text)
    if not match:
        return None
    w, h, x, y = (int(g) for g in match.groups())
    return (x, y, w, h)


# ==========================================================================
# Global hotkeys
# ==========================================================================
# A registered hotkey is taken from *every* application system-wide, so the
# defaults deliberately avoid combos that ordinary programs rely on. Ctrl+H,
# for instance, would be a bad choice - it is find-and-replace almost
# everywhere. Two and three modifier combos are used instead.

HOTKEY_OFF = "(off)"

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 1, 2, 4, 8, 0x4000

MODIFIER_CHOICES = {
    "Ctrl + Alt": MOD_CONTROL | MOD_ALT,
    "Ctrl + Shift": MOD_CONTROL | MOD_SHIFT,
    "Alt + Shift": MOD_ALT | MOD_SHIFT,
    "Ctrl + Alt + Shift": MOD_CONTROL | MOD_ALT | MOD_SHIFT,
    "Ctrl + Win": MOD_CONTROL | MOD_WIN,
    "Win + Alt": MOD_WIN | MOD_ALT,
    "Win + Shift": MOD_WIN | MOD_SHIFT,
}
MODIFIER_ORDER = [HOTKEY_OFF] + list(MODIFIER_CHOICES)


def _build_vk_map():
    keys = {}
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        keys[letter] = ord(letter)
    for digit in "0123456789":
        keys[digit] = ord(digit)
    for n in range(1, 13):
        keys["F%d" % n] = 0x70 + n - 1
    keys.update({
        "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
        "Space": 0x20, "Insert": 0x2D, "Home": 0x24, "End": 0x23,
        "Page Up": 0x21, "Page Down": 0x22,
        "Comma": 0xBC, "Period": 0xBE, "Minus": 0xBD, "Equals": 0xBB,
        "[": 0xDB, "]": 0xDD, "Semicolon": 0xBA, "Slash": 0xBF,
        "Numpad +": 0x6B, "Numpad -": 0x6D, "Numpad *": 0x6A, "Numpad /": 0x6F,
    })
    return keys


VK_MAP = _build_vk_map()
KEY_ORDER = (
    [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [str(d) for d in range(10)]
    + ["F%d" % n for n in range(1, 13)]
    + ["Left", "Right", "Up", "Down", "Space", "Insert", "Home", "End",
       "Page Up", "Page Down", "Comma", "Period", "Minus", "Equals",
       "[", "]", "Semicolon", "Slash",
       "Numpad +", "Numpad -", "Numpad *", "Numpad /"]
)

# (action id, label shown in settings, may auto-repeat while held)
ACTIONS = (
    ("toggle", "Show / hide the overlay", False),
    ("nudge_left", "Nudge grid left", True),
    ("nudge_right", "Nudge grid right", True),
    ("nudge_up", "Nudge grid up", True),
    ("nudge_down", "Nudge grid down", True),
    ("cell_down", "Cell size smaller", True),
    ("cell_up", "Cell size larger", True),
    ("cycle_shape", "Next grid shape", False),
    ("focus_panel", "Bring this panel to the front", False),
    ("reveal_ranges", "Hold to show range bands to players", False),
)

# Every default uses three modifiers. Two is not enough in practice: Ctrl+Alt+G
# belongs to Google Drive, and plenty of other background utilities quietly
# claim Ctrl+Alt combinations for themselves. Arrows in particular avoid
# Ctrl+Alt because on some Intel graphics setups that rotates the whole screen.
DEFAULT_HOTKEYS = {
    "toggle": ["Ctrl + Alt + Shift", "G"],
    "nudge_left": ["Ctrl + Alt + Shift", "Left"],
    "nudge_right": ["Ctrl + Alt + Shift", "Right"],
    "nudge_up": ["Ctrl + Alt + Shift", "Up"],
    "nudge_down": ["Ctrl + Alt + Shift", "Down"],
    "cell_down": ["Ctrl + Alt + Shift", "J"],
    "cell_up": ["Ctrl + Alt + Shift", "K"],
    "cycle_shape": ["Ctrl + Alt + Shift", "B"],
    "focus_panel": ["Ctrl + Alt + Shift", "P"],
    "reveal_ranges": ["Ctrl + Alt + Shift", "R"],
}

# Saved settings normally take precedence over defaults, which is right for
# anything the user actually chose. But a binding that merely matches an old
# default was never a choice - it was inherited - so bumping this version lets
# those be upgraded while leaving genuine customisations untouched.
HOTKEY_DEFAULTS_VERSION = 2
SUPERSEDED_DEFAULTS = {
    "toggle": [["Ctrl + Alt", "G"]],          # Ctrl+Alt+G belongs to Google Drive
    "cell_down": [["Ctrl + Alt", "J"]],
    "cell_up": [["Ctrl + Alt", "K"]],
    "cycle_shape": [["Ctrl + Alt", "B"]],
    "focus_panel": [["Ctrl + Alt", "P"]],
}


def normalise_hotkeys(saved, version=0):
    """Take whatever is in the settings file and return a usable mapping.

    `version` is the defaults generation the file was written against. When it
    lags behind, any binding still sitting on a superseded default is moved to
    the current one; anything else the user set is kept exactly as it is.
    """
    result = {}
    outdated = version < HOTKEY_DEFAULTS_VERSION
    for action, _label, _repeat in ACTIONS:
        pair = saved.get(action) if isinstance(saved, dict) else None
        if (isinstance(pair, (list, tuple)) and len(pair) == 2
                and pair[0] in MODIFIER_ORDER
                and (pair[0] == HOTKEY_OFF or pair[1] in VK_MAP)):
            if outdated and list(pair) in SUPERSEDED_DEFAULTS.get(action, []):
                result[action] = list(DEFAULT_HOTKEYS[action])
            else:
                result[action] = [pair[0], pair[1]]
        else:
            result[action] = list(DEFAULT_HOTKEYS[action])
    return result


def hotkey_text(pair):
    if not pair or pair[0] == HOTKEY_OFF:
        return "not set"
    return "%s + %s" % (pair[0], pair[1])


if IS_WINDOWS:
    LRESULT = ctypes.c_ssize_t
    WPARAM_T = ctypes.c_size_t
    LPARAM_T = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 WPARAM_T, LPARAM_T)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    def _prepare_win32():
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32

        # Every call below returns or accepts a pointer-sized handle. Left
        # undeclared, ctypes assumes a 32-bit int, which silently truncates
        # handles on 64-bit Windows - the kind of fault that takes the process
        # down with no Python traceback to show for it.
        k32.GetModuleHandleW.restype = wintypes.HMODULE
        k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k32.GetConsoleWindow.restype = wintypes.HWND
        k32.GetConsoleWindow.argtypes = []
        k32.GetCurrentProcessId.restype = wintypes.DWORD
        k32.GetCurrentProcessId.argtypes = []

        u32.GetParent.restype = wintypes.HWND
        u32.GetParent.argtypes = [wintypes.HWND]
        u32.GetWindowThreadProcessId.restype = wintypes.DWORD
        u32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u32.ShowWindow.restype = wintypes.BOOL
        u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.SetWindowPos.restype = wintypes.BOOL
        u32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u32.EnumDisplayMonitors.restype = wintypes.BOOL
        # A registered hotkey reports its press but never its release, so
        # hold-to-reveal has to watch the key directly.
        u32.GetAsyncKeyState.restype = ctypes.c_short
        u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        if hasattr(u32, "GetDpiForWindow"):
            u32.GetDpiForWindow.restype = wintypes.UINT
            u32.GetDpiForWindow.argtypes = [wintypes.HWND]

        try:
            dwm = ctypes.windll.dwmapi
            dwm.DwmSetWindowAttribute.restype = ctypes.c_long   # HRESULT
            dwm.DwmSetWindowAttribute.argtypes = [
                wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        except Exception:
            pass

        u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        u32.RegisterClassW.restype = wintypes.WORD
        u32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        u32.CreateWindowExW.restype = wintypes.HWND
        u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       WPARAM_T, LPARAM_T]
        u32.DefWindowProcW.restype = LRESULT
        u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                       wintypes.UINT, wintypes.UINT]
        u32.RegisterHotKey.restype = wintypes.BOOL
        u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.UnregisterHotKey.restype = wintypes.BOOL
        u32.DestroyWindow.argtypes = [wintypes.HWND]
        # Without explicit types these default to a 32-bit int return, which
        # truncates a window's extended style on 64-bit Windows.
        for name in ("GetWindowLongPtrW", "SetWindowLongPtrW"):
            function = getattr(u32, name, None)
            if function is not None:
                function.restype = LRESULT
                function.argtypes = ([wintypes.HWND, ctypes.c_int]
                                     + ([LPARAM_T] if "Set" in name else []))
        u32.GetWindowLongW.restype = wintypes.LONG
        u32.SetWindowLongW.restype = wintypes.LONG

    try:
        _prepare_win32()
    except Exception:
        pass


class HotkeyManager:
    """System-wide hotkeys, delivered through a hidden native window.

    Windows posts WM_HOTKEY to a window, not to tkinter. Rather than fight
    tkinter's event loop, this creates its own tiny never-shown window with a
    real window procedure. Tk's loop pumps the thread's messages either way,
    and dispatch routes WM_HOTKEY to that procedure, which then hands the work
    back to the Tk thread through after_idle.
    """

    WM_HOTKEY = 0x0312
    CLASS_NAME = "GridwyrmHotkeyHost"
    POLL_MS = 40
    MAX_PENDING = 40

    def __init__(self, root):
        self.root = root
        self.hwnd = None
        self.available = False
        self._proc = None
        self._handlers = {}
        self._ids = []
        self._next_id = 1
        self._pending = []
        self._polling = False
        if IS_WINDOWS:
            self._create_host()

    def _create_host(self):
        try:
            u32 = ctypes.windll.user32
            self._proc = WNDPROC(self._on_message)
            spec = WNDCLASSW()
            spec.lpfnWndProc = self._proc
            spec.lpszClassName = self.CLASS_NAME
            spec.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
            # A second instance finds the class already registered, which is
            # harmless, so the return value is deliberately not checked.
            u32.RegisterClassW(ctypes.byref(spec))
            self.hwnd = u32.CreateWindowExW(
                0, self.CLASS_NAME, "Gridwyrm", 0, 0, 0, 0, 0,
                None, None, spec.hInstance, None,
            )
            self.available = bool(self.hwnd)
        except Exception:
            self.hwnd = None
            self.available = False

    def _on_message(self, hwnd, msg, wparam, lparam):
        """The window procedure. Does no Tk work at all, on purpose.

        This runs inside Tcl's own message dispatch, so calling back into the
        interpreter from here - even something as small as after_idle - re-enters
        Tcl while it is already mid-dispatch. Tkinter is not re-entrant, and the
        result is a process that dies with no Python exception and no fault
        trace. The hotkey id is queued instead, and a timer running on the Tk
        thread picks it up a moment later.
        """
        if msg == self.WM_HOTKEY:
            try:
                if len(self._pending) < self.MAX_PENDING:
                    self._pending.append(int(wparam))
            except Exception:
                pass
            return 0
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def start_polling(self):
        """Begin draining queued hotkeys on the Tk thread."""
        if self._polling:
            return
        self._polling = True
        self._poll()

    def _poll(self):
        while self._pending:
            hk_id = self._pending.pop(0)
            handler = self._handlers.get(hk_id)
            if handler:
                handler()                        # already wrapped by App._guard
        try:
            self.root.after(self.POLL_MS, self._poll)
        except tk.TclError:
            self._polling = False

    def clear(self):
        if not (IS_WINDOWS and self.hwnd):
            self._handlers, self._ids = {}, []
            return
        u32 = ctypes.windll.user32
        for hk_id in self._ids:
            try:
                u32.UnregisterHotKey(self.hwnd, hk_id)
            except Exception:
                pass
        self._handlers, self._ids = {}, []

    def apply(self, bindings, handlers):
        """Register the given bindings. Returns {action: reason} for failures."""
        self.clear()
        wanted = {
            action: bindings.get(action, [HOTKEY_OFF, ""])
            for action, _label, _repeat in ACTIONS
        }
        if not self.available:
            return {a: "needs Windows" for a, pair in wanted.items()
                    if pair[0] != HOTKEY_OFF}

        u32 = ctypes.windll.user32
        failures = {}
        for action, _label, repeat in ACTIONS:
            mods_label, key_label = wanted[action]
            if mods_label == HOTKEY_OFF:
                continue
            mods = MODIFIER_CHOICES.get(mods_label)
            vk = VK_MAP.get(key_label)
            if mods is None or vk is None:
                failures[action] = "unknown key"
                continue
            flags = mods if repeat else mods | MOD_NOREPEAT
            hk_id = self._next_id
            self._next_id += 1
            try:
                ok = u32.RegisterHotKey(self.hwnd, hk_id, flags, vk)
            except Exception:
                ok = False
            if ok:
                self._ids.append(hk_id)
                self._handlers[hk_id] = handlers[action]
            else:
                failures[action] = "already taken"
        return failures

    def destroy(self):
        self._polling = False
        self._pending = []
        self.clear()
        if IS_WINDOWS and self.hwnd:
            try:
                ctypes.windll.user32.DestroyWindow(self.hwnd)
            except Exception:
                pass
        self.hwnd = None


# ==========================================================================
# Start with Windows
# ==========================================================================
# The per-user Run key needs no administrator rights and no shortcut files,
# which makes it the right mechanism for a tool someone drops on a dedicated
# gaming machine. The registry is treated as the source of truth rather than
# the settings file, so a change made outside the app is respected.

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "Gridwyrm"


def autostart_command():
    """The command line that relaunches this program."""
    if getattr(sys, "frozen", False):
        return '"%s"' % os.path.abspath(sys.executable)
    # __file__ is the real module path; argv[0] can be a stub or empty
    # depending on how the interpreter was invoked.
    script = None
    try:
        script = os.path.abspath(__file__)
    except NameError:
        pass
    if not script or not os.path.exists(script):
        candidate = sys.argv[0] if sys.argv else ""
        script = os.path.abspath(candidate) if candidate else ""
    launcher = sys.executable
    # pythonw.exe keeps the console from flashing up at every login.
    windowless = os.path.join(os.path.dirname(launcher), "pythonw.exe")
    if os.path.exists(windowless):
        launcher = windowless
    return '"%s" "%s"' % (launcher, script)


def autostart_state():
    """Returns (enabled, command currently recorded in the registry)."""
    if not IS_WINDOWS:
        return False, ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            value, _kind = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return True, str(value)
    except OSError:
        return False, ""


def set_autostart(enabled):
    """Returns (ok, message)."""
    if not IS_WINDOWS:
        return False, "needs Windows"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ,
                                  autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True, ""
    except OSError as error:
        return False, str(error)


def refresh_autostart_path():
    """Repair the recorded command if the program has since been moved."""
    enabled, recorded = autostart_state()
    if enabled and recorded != autostart_command():
        set_autostart(True)


# ==========================================================================
# Update check
# ==========================================================================
# Asks GitHub whether a newer release exists, and says so. It does not download
# or install anything.
#
# That is deliberate. Windows will not let a running executable overwrite
# itself, so self-updating means spawning a helper that waits for the process to
# die, swaps the file and starts it again. It is fiddly, it is a well-known way
# to leave someone with no working copy, and a self-replacing unsigned binary is
# exactly the behaviour that turns an antivirus warning into a quarantine.
# Opening the download page costs one click and cannot break anything.
#
# The request carries no information about the user beyond what any HTTPS
# request carries. It can be switched off, and it runs at most once a day.

# Stamped from the release tag when the exe is built, so a packaged copy can
# never disagree with the release it came from. This value is what a copy run
# from source reports.
VERSION = "2.1"
UPDATE_API = "https://api.github.com/repos/LMMRZWG/Gridwyrm/releases/latest"
RELEASES_PAGE = "https://github.com/LMMRZWG/Gridwyrm/releases/latest"
UPDATE_INTERVAL_HOURS = 20


def parse_version(text):
    """'v2.1.3' becomes (2, 1, 3). None when it cannot be read.

    Tolerates a leading v, a trailing suffix such as -beta, and any number of
    parts, because a tag is typed by hand and will not always be tidy.
    """
    if not text:
        return None
    cleaned = str(text).strip().lstrip("vV").split("+")[0].split("-")[0]
    parts = cleaned.split(".")
    numbers = []
    for part in parts:
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            return None
        numbers.append(int(digits))
    return tuple(numbers) if numbers else None


def is_newer(candidate, current):
    """True when candidate names a later version than current.

    Missing parts count as zero, so 2.1 beats 2.0.9 and matches 2.1.0. An
    unreadable version is never treated as newer: better to miss an update than
    to nag about one that does not exist.
    """
    left, right = parse_version(candidate), parse_version(current)
    if left is None or right is None:
        return False
    length = max(len(left), len(right))
    left += (0,) * (length - len(left))
    right += (0,) * (length - len(right))
    return left > right


# Only these hosts are ever downloaded from. A reply that pointed the installer
# anywhere else, whether through a compromised account or a hijacked connection,
# is refused rather than followed.
TRUSTED_DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com",
                          "release-assets.githubusercontent.com")


def download_is_trusted(url):
    """Whether a URL is somewhere we are willing to fetch a program from."""
    try:
        parts = urllib.parse.urlsplit(str(url))
    except Exception:
        return False
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    return (host in TRUSTED_DOWNLOAD_HOSTS
            or host.endswith(".githubusercontent.com"))


def read_latest_release(url=UPDATE_API, timeout=6.0):
    """Ask GitHub for the newest release.

    Returns a dict with the tag, the page, and the .exe asset if the release has
    one. Raises on any failure, which the caller swallows: an update check that
    complains when the network is down is worse than no update check.
    """
    request = urllib.request.Request(url, headers={
        # GitHub refuses requests without one of these.
        "User-Agent": "Gridwyrm/%s" % VERSION,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))

    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("no tag_name in the reply")

    asset = None
    for item in payload.get("assets") or []:
        name = str(item.get("name") or "")
        link = str(item.get("browser_download_url") or "")
        if name.lower().endswith(".exe") and download_is_trusted(link):
            asset = {"name": name, "url": link,
                     "size": int(item.get("size") or 0)}
            break

    return {"tag": tag,
            "page": str(payload.get("html_url") or RELEASES_PAGE),
            "asset": asset}


def download_release_asset(url, destination, expected_size=0, timeout=120.0):
    """Fetch the new program to a file beside the current one.

    The declared size is checked afterwards, because a download cut short by a
    dropped connection would otherwise be installed as though it were whole.
    """
    if not download_is_trusted(url):
        raise ValueError("refusing to download from %s" % url)
    request = urllib.request.Request(
        url, headers={"User-Agent": "Gridwyrm/%s" % VERSION})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with open(destination, "wb") as handle:
            shutil.copyfileobj(response, handle, 128 * 1024)
    size = os.path.getsize(destination)
    if expected_size and size != expected_size:
        os.remove(destination)
        raise ValueError("got %d bytes, expected %d" % (size, expected_size))
    if size < 1024:
        os.remove(destination)
        raise ValueError("the download was empty")
    return size


def swap_script(current, incoming, backup, pid):
    """A batch file that replaces the program once this copy has exited.

    Windows will not let a running executable overwrite itself, so the swap has
    to outlive the process doing it. The old copy is kept as a backup and put
    straight back if the replacement fails, so a bad moment cannot leave someone
    with nothing that runs.
    """
    return "\r\n".join([
        "@echo off",
        "rem Written by Gridwyrm to finish an update. Safe to delete.",
        ":wait",
        'tasklist /fi "PID eq %d" 2>nul | find "%d" >nul' % (pid, pid),
        "if not errorlevel 1 (",
        "  ping -n 2 127.0.0.1 >nul",
        "  goto wait",
        ")",
        'if exist "%s" del /q "%s"' % (backup, backup),
        'move /y "%s" "%s" >nul' % (current, backup),
        'move /y "%s" "%s" >nul' % (incoming, current),
        'if not exist "%s" move /y "%s" "%s" >nul' % (current, backup, current),
        'start "" "%s"' % current,
        'del /q "%~f0"',
        "",
    ])


def update_check_due(last_checked, now=None, hours=UPDATE_INTERVAL_HOURS):
    """Whether enough time has passed. Also guards against a clock that moved."""
    now = time.time() if now is None else now
    try:
        last = float(last_checked)
    except (TypeError, ValueError):
        return True
    if last > now:
        return True                              # clock changed, so check again
    return (now - last) >= hours * 3600


# ==========================================================================
# Diagnostics
# ==========================================================================
# Two separate logs, because there are two very different ways this can fail.
# A Python exception is caught and written to errors.log. A fault inside a
# native call - the ctypes work for click-through, hotkeys and window frames -
# kills the process outright with no Python traceback at all, so faulthandler
# is pointed at crash.log to catch those. session.log records the breadcrumbs
# that tell the two apart, above all whether the app was asked to close or
# simply died.

def log_path(name):
    return os.path.join(os.path.dirname(settings_path()), name)


def log_event(message):
    try:
        path = log_path("session.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "a"
        try:
            if os.path.getsize(path) > 256 * 1024:
                mode = "w"                       # keep it from growing forever
        except OSError:
            pass
        with open(path, mode, encoding="utf-8") as handle:
            handle.write("%s  %s\n" % (time.strftime("%H:%M:%S"), message))
    except Exception:
        pass


def enable_fault_log():
    """Catch hard faults, which never reach Python's exception handling."""
    try:
        path = log_path("crash.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handle = open(path, "a", encoding="utf-8", buffering=1)
        handle.write("\n=== session started %s ===\n"
                     % time.strftime("%Y-%m-%d %H:%M:%S"))
        faulthandler.enable(file=handle)
        return handle          # must outlive the process, so it is returned
    except Exception:
        return None


# ==========================================================================
# Saved settings
# ==========================================================================

def settings_path():
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Gridwyrm", "settings.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "gridwyrm", "settings.json")


def load_settings():
    try:
        with open(settings_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data):
    try:
        path = settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except Exception:
        pass                                     # never block shutdown


# ==========================================================================
# Grid geometry
# ==========================================================================

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


# ==========================================================================
# Measuring
# ==========================================================================
# Gridwyrm knows a cell is so many pixels wide. On its own that says nothing
# about the map: a square could be five feet or five miles. Declaring how much
# ground one square covers is what turns pixels into distance, and it is the
# piece everything else here depends on.

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


# ==========================================================================
# Range bands
# ==========================================================================
# Named distances instead of numbers. The point is that a player can be told
# they are "Near" without anyone saying thirty feet out loud, so the band name
# is the answer rather than a label on a figure.
#
# The defaults are invented rather than taken from a system, but the distances
# behind them are real 5e ones: reach of a weapon, a round of walking, the
# limit of darkvision, the reach of a longbow.

# Kept deliberately tight. Bands are absolute distances turned into pixels by
# the cell size, so a generous set becomes enormous the moment someone works at
# a 100px cell. Five squares out is 500 pixels there, which is already most of
# a laptop screen. Anything larger is better set by hand, for a table that
# knows its own screen.
DEFAULT_BANDS = (
    ("Melee", 5.0),
    ("Close", 10.0),
    ("Near", 15.0),
    ("Far", 25.0),
)

RANGE_MODES = ("Off", "DM only", "Show players")
MAX_BANDS = 8

# ==========================================================================
# Conditions
# ==========================================================================
# A marker dropped on a creature to say what is happening to it: poisoned,
# burning, blessed. Unlike range bands these are not about distance, so they do
# not scale with anything except the cell size, and they are always visible.
# There is no reason to hide from the table that something is on fire.
#
# Colour carries the meaning, which is why each condition owns one. Names are
# there for the DM and for anyone who cannot rely on colour alone.

# The official conditions, coloured after the plastic rings people slip over a
# miniature's base. Two habits are borrowed from those: the name is printed on
# the band rather than beside it, and it is printed twice, on opposite sides, so
# it reads from any seat at the table. Several of these are near-white in the
# physical set, where the printing tells them apart; here they are nudged apart
# a little as well.
DEFAULT_CONDITIONS = (
    ("Blind", "#E8B923"),
    ("Charmed", "#E88AA0"),
    ("Deaf", "#5A2E1E"),
    ("Exhausted", "#8B1A1A"),
    ("Frightened", "#FFFFFF"),
    ("Grappled", "#D32027"),
    ("Incapacitated", "#1F3A93"),
    ("Invisible", "#D8E8F0"),
    ("Paralyzed", "#5B2D8E"),
    ("Petrified", "#B8BCC0"),
    ("Poisoned", "#1E7A34"),
    ("Prone", "#2FA8E0"),
    ("Restrained", "#F07818"),
    ("Stunned", "#F0D000"),
    ("Unconscious", "#8C9196"),
)
MAX_CONDITIONS = 20

# Saved settings beat defaults, which is right for anything chosen deliberately
# and wrong for a list that was only ever inherited. Gridwyrm shipped with five
# invented conditions before the full set existed; a saved list that still
# matches those exactly was never a choice, so it is replaced.
CONDITION_DEFAULTS_VERSION = 2
SUPERSEDED_CONDITIONS = (
    (("Poisoned", "#4CAF50"), ("Burning", "#E2483D"), ("Frozen", "#4A90E2"),
     ("Blessed", "#F5C542"), ("Cursed", "#9B59B6")),
)


def normalise_conditions(text, version=0):
    """Read the saved conditions, upgrading a list that was never chosen."""
    conditions, _error = parse_conditions(text)
    if not conditions:
        return [list(pair) for pair in DEFAULT_CONDITIONS]
    if version < CONDITION_DEFAULTS_VERSION:
        current = tuple(tuple(pair) for pair in conditions)
        for superseded in SUPERSEDED_CONDITIONS:
            if current == superseded:
                return [list(pair) for pair in DEFAULT_CONDITIONS]
    return [list(pair) for pair in conditions]


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


def validate_conditions(rows):
    """Check name and colour pairs from the editor.

    Returns (conditions, error message).
    """
    conditions = []
    for index, (name, colour) in enumerate(rows, start=1):
        name = str(name).strip()
        colour = str(colour).strip()
        if not name and not colour:
            continue                             # an untouched row
        if not name:
            return None, "Row %d has no name" % index
        if "=" in name:
            return None, "Row %d: a name cannot contain an equals sign" % index
        if not HEX_RE.match(colour):
            return None, "Row %d: %s is not a six-digit colour" % (
                index, colour if colour else "the colour is blank")
        conditions.append((name, colour.upper()))

    if not conditions:
        return None, "Give at least one condition"
    if len(conditions) > MAX_CONDITIONS:
        return None, "%d conditions is as many as fits" % MAX_CONDITIONS
    seen = {}
    for name, _colour in conditions:
        key = name.lower()
        if key in seen:
            return None, "Two conditions are both called %s" % seen[key]
        seen[key] = name
    return conditions, ""


def format_conditions(conditions):
    return "\n".join("%s = %s" % (name, colour) for name, colour in conditions)


def parse_conditions(text):
    """Read the 'Name = #RRGGBB' lines kept in the settings file."""
    rows = []
    for line in str(text).splitlines():
        line = line.strip()
        if not line or line.startswith("#") and "=" not in line:
            continue
        name, _, colour = line.partition("=")
        rows.append((name, colour))
    if not rows:
        return None, "nothing to read"
    return validate_conditions(rows)


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


def validate_bands(rows):
    """Check name and distance pairs from the editor.

    Separate from parse_bands, which reads the text kept in the settings file.
    Working from pairs means a name can contain anything except an equals sign,
    and it catches two things the text form could not: a row left completely
    blank, which is simply skipped rather than treated as an error, and two
    bands sharing a name, which would put two identical labels on the map.

    Returns (bands, error message).
    """
    bands = []
    for index, (name, value) in enumerate(rows, start=1):
        name = str(name).strip()
        value = str(value).strip().replace(",", ".")
        if not name and not value:
            continue                             # an untouched row
        if not name:
            return None, "Row %d has no name" % index
        if "=" in name:
            return None, "Row %d: a name cannot contain an equals sign" % index
        if not value:
            return None, "Row %d has no distance" % index
        try:
            distance = float(value)
        except ValueError:
            return None, "Row %d: %s is not a number" % (index, value)
        if distance <= 0:
            return None, "Row %d: the distance has to be above zero" % index
        bands.append((name, distance))

    if not bands:
        return None, "Give at least one band"
    if len(bands) > MAX_BANDS:
        return None, "%d bands is as many as stays readable" % MAX_BANDS
    seen = {}
    for name, _distance in bands:
        key = name.lower()
        if key in seen:
            return None, "Two bands are both called %s" % seen[key]
        seen[key] = name
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


def contrast_halo(colour):
    """An outline that will show against the colour it surrounds.

    Every band is drawn twice, a wider outline under a narrower fill, because
    the map beneath is unknown. A pale band needs a dark outline and a dark one
    needs a pale outline, or half the ring disappears into the terrain.
    """
    return "#FFFFFF" if luminance(colour) < 0.45 else "#000000"


# Bands are always drawn as circles. Under a "diagonal counts as one" rule the
# reachable area is strictly a square, and an earlier version drew it that way
# for consistency. On a square grid that was unreadable: a square ring is
# indistinguishable from the grid it sits on. The diagonal rule still governs
# the measuring readout, where counting squares is the whole point, but a range
# indicator has to look nothing like the grid underneath it.

# Bands are never filled. Tk has no alpha channel, so an earlier version faked
# transparency with a stipple bitmap, and even the sparsest one Tk offers
# covered the map. Revealing a band means putting its name on the ring, not
# shading everything inside it.
RING_WEIGHT_PRIVATE = 1
RING_WEIGHT_REVEALED = 3


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


# ==========================================================================
# Small helpers
# ==========================================================================

def safe_float(variable, fallback=0.0):
    try:
        return float(variable.get())
    except (tk.TclError, ValueError):
        return fallback


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


# ==========================================================================
# Overlay surface
# ==========================================================================

class Overlay:
    def __init__(self, master):
        self.win = tk.Toplevel(master)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=KEY_COLOR)
        self.canvas = tk.Canvas(self.win, bg=KEY_COLOR, highlightthickness=0,
                                bd=0, takefocus=0)
        self.canvas.pack(fill="both", expand=True)
        self.win.update_idletasks()
        if IS_WINDOWS:
            self.win.attributes("-transparentcolor", KEY_COLOR)
        self.width = self.height = 0
        self._click_through = False
        self.can_rotate_text = self._probe_rotated_text()

    def _probe_rotated_text(self):
        """Rotated canvas text needs Tk 8.6. Ask once, off-screen.

        Checked up front rather than while drawing, because recovering from a
        failure halfway through would mean clearing marks already placed.
        """
        try:
            item = self.canvas.create_text(-999, -999, text="x", angle=45)
            self.canvas.delete(item)
            return True
        except tk.TclError:
            return False

    def place_on(self, x, y, w, h):
        self.width, self.height = w, h
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        self.canvas.configure(width=w, height=h)

    def set_opacity(self, percent):
        self.win.attributes("-alpha", max(5, min(100, percent)) / 100.0)

    def set_click_through(self, enabled):
        if not IS_WINDOWS or enabled == self._click_through:
            return
        GWL_EXSTYLE, LAYERED, TRANSPARENT = -20, 0x00080000, 0x00000020
        u32 = ctypes.windll.user32
        get_style = getattr(u32, "GetWindowLongPtrW", u32.GetWindowLongW)
        set_style = getattr(u32, "SetWindowLongPtrW", u32.SetWindowLongW)
        hwnd = hwnd_of(self.win)
        style = get_style(hwnd, GWL_EXSTYLE)
        style = (style | LAYERED | TRANSPARENT) if enabled else (style & ~TRANSPARENT)
        set_style(hwnd, GWL_EXSTYLE, style)
        self._click_through = enabled

    def show(self):
        self.win.deiconify()
        self.win.attributes("-topmost", True)

    def hide(self):
        self.win.withdraw()

    def raise_above(self):
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass

    # -- measuring ---------------------------------------------------------

    def set_measure_surface(self, active):
        """Make the whole overlay catch the mouse, or return it to see-through.

        This is the part that is easy to get wrong. Tk's transparent colour key
        does more than hide those pixels: Windows also leaves them out of hit
        testing, so the background passes clicks through even with
        WS_EX_TRANSPARENT removed. Only the grid lines themselves were
        clickable, which made measuring impossible.

        So the colour key has to go for the duration, and the background
        becomes a real surface. Reduced opacity keeps the map readable
        underneath, and the wash doubles as an unmistakable signal that the
        overlay is holding the mouse.
        """
        if active:
            if IS_WINDOWS:
                try:
                    self.win.attributes("-transparentcolor", "")
                except tk.TclError:
                    # Some builds refuse an empty value; a colour that will
                    # never appear on screen has the same effect.
                    self.win.attributes("-transparentcolor", "#FE01FE")
            self.canvas.configure(bg=MEASURE_WASH)
            self.win.attributes("-alpha", MEASURE_ALPHA)
        else:
            self.canvas.configure(bg=KEY_COLOR)
            if IS_WINDOWS:
                try:
                    self.win.attributes("-transparentcolor", KEY_COLOR)
                except tk.TclError:
                    pass
            # The caller restores the user's own opacity setting.

    def show_measure_hint(self, text, font):
        """A note on the overlay itself, since that is where you are looking."""
        c = self.canvas
        c.delete("hint")
        if not text or self.width <= 1:
            return
        pad = 10
        probe = c.create_text(0, -200, text=text, anchor="nw", font=font,
                              tags="hint")
        bounds = c.bbox(probe)
        c.delete(probe)
        text_w = (bounds[2] - bounds[0]) if bounds else 260
        text_h = (bounds[3] - bounds[1]) if bounds else 16
        x = (self.width - text_w) / 2 - pad
        y = 24
        c.create_rectangle(x, y, x + text_w + pad * 2, y + text_h + pad * 2,
                           fill="#000000", outline="#FFFFFF", tags="hint")
        c.create_text(x + pad, y + pad, text=text, anchor="nw", fill="#FFFFFF",
                      font=font, tags="hint")

    def begin_measure(self, on_click, on_move, on_cancel):
        """Take clicks on the overlay so a span can be dragged out.

        Click-through has to come off for this, since an overlay that ignores
        the mouse cannot be measured on. That is the one genuinely dangerous
        state in this program: a full-screen invisible sheet swallowing every
        click. So the caller is responsible for restoring click-through no
        matter how measuring ends, and there are several ways out - a second
        click, a right-click, Escape, the panel button, or a timeout.
        """
        c = self.canvas
        c.configure(cursor="crosshair")
        # The modifier state travels with the position: Shift constrains the
        # line, as it does in any drawing tool.
        c.bind("<Button-1>", lambda e: on_click(e.x, e.y))
        c.bind("<Motion>", lambda e: on_move(e.x, e.y, e.state))
        c.bind("<Button-3>", lambda e: on_cancel())
        c.bind("<Escape>", lambda e: on_cancel())
        try:
            c.focus_set()
        except tk.TclError:
            pass

    def end_measure(self):
        c = self.canvas
        for sequence in ("<Button-1>", "<Motion>", "<Button-3>", "<Escape>"):
            try:
                c.unbind(sequence)
            except tk.TclError:
                pass
        c.configure(cursor="")
        c.delete("measure")
        c.delete("hint")

    def draw_measure(self, x1, y1, x2, y2, label, font):
        """A span and its readout, drawn to be legible over any map.

        Every mark gets a dark outline under a light fill, because the map
        underneath is unknown: a plain white line vanishes on snow and a plain
        black one vanishes in a dungeon.
        """
        c = self.canvas
        c.delete("measure")
        dark, light = "#000000", "#FFFFFF"

        c.create_line(x1, y1, x2, y2, fill=dark, width=5, tags="measure")
        c.create_line(x1, y1, x2, y2, fill=light, width=2, tags="measure")

        for x, y in ((x1, y1), (x2, y2)):
            c.create_oval(x - 6, y - 6, x + 6, y + 6, fill=dark,
                          outline=light, width=2, tags="measure")

        if not label:
            return

        # Sit the readout beside the moving end, flipped inward near an edge so
        # it never runs off the screen being measured.
        pad = 7
        probe = c.create_text(0, -200, text=label, anchor="nw", font=font,
                              tags="measure")
        bounds = c.bbox(probe)
        c.delete(probe)
        text_w = (bounds[2] - bounds[0]) if bounds else 120
        text_h = (bounds[3] - bounds[1]) if bounds else 16

        tx = x2 + 16
        ty = y2 - text_h - 16
        if tx + text_w + pad * 2 > self.width:
            tx = x2 - text_w - pad * 2 - 16
        if ty < 0:
            ty = y2 + 16
        c.create_rectangle(tx, ty, tx + text_w + pad * 2, ty + text_h + pad * 2,
                           fill=dark, outline=light, tags="measure")
        c.create_text(tx + pad, ty + pad, text=label, anchor="nw", fill=light,
                      font=font, tags="measure")

    # -- range bands -------------------------------------------------------

    def draw_ranges(self, origin, rings, revealed, font, colour="#F5C542"):
        """Translucent discs around a point, one per band.

        Circles, filled with a stipple so the map still shows through, which is
        what stops them reading as grid lines. Drawn outermost first so the
        inner bands stay on top.

        While private the bands carry no text at all: the distances belong in
        the panel, where only the person running the game is looking. Revealing
        is what puts a name on the ring, bold enough to read across a table, so
        a player learns they are Near without anyone saying thirty feet.
        """
        c = self.canvas
        c.delete("ranges")
        if origin is None or not rings:
            return

        ox, oy = origin
        if not HEX_RE.match(str(colour)):
            colour = "#F5C542"
        halo = contrast_halo(colour)
        line = colour if revealed else blend(colour, halo, 0.62)
        weight = RING_WEIGHT_REVEALED if revealed else RING_WEIGHT_PRIVATE

        for name, radius in sorted(rings, key=lambda pair: -pair[1]):
            if radius < 5:
                continue
            box = (ox - radius, oy - radius, ox + radius, oy + radius)
            c.create_oval(*box, outline=halo, width=weight + 2, tags="ranges")
            c.create_oval(*box, outline=line, width=weight, tags="ranges")

        if revealed:
            for name, radius in rings:
                if radius < 5:
                    continue
                # On the up-right diagonal, so successive bands do not stack
                # their names on top of one another.
                lx = min(max(ox + radius * 0.707, 8), max(9, self.width - 8))
                ly = min(max(oy - radius * 0.707, 8), max(9, self.height - 8))
                self._range_label(name, lx, ly, font, line, halo)

        # The origin, so it is obvious what the bands are measured from.
        r = 7 if revealed else 4
        c.create_oval(ox - r, oy - r, ox + r, oy + r, fill=halo,
                      outline=line, width=2, tags="ranges")

    def _range_label(self, name, x, y, font, line, halo):
        c = self.canvas
        pad = 6
        probe = c.create_text(0, -300, text=name, anchor="nw", font=font,
                              tags="ranges")
        bounds = c.bbox(probe)
        c.delete(probe)
        w = (bounds[2] - bounds[0]) if bounds else 60
        h = (bounds[3] - bounds[1]) if bounds else 14
        c.create_rectangle(x - w / 2 - pad, y - h / 2 - pad,
                           x + w / 2 + pad, y + h / 2 + pad,
                           fill=halo, outline=line, tags="ranges")
        c.create_text(x, y, text=name, anchor="center", fill=line,
                      font=font, tags="ranges")

    def clear_ranges(self):
        self.canvas.delete("ranges")

    def draw_conditions(self, markers, radius, font, font_for=None):
        """A coloured band on each marked creature, with its name on the band.

        Modelled on the plastic rings that slip over a miniature's base, and
        borrowing the detail that makes those work: the name is set twice, on
        opposite sides of the ring, so it reads whether you are sitting at the
        top of the table or the bottom. On a screen laid flat that matters as
        much as it does with the physical thing.

        Falls back to a plain label underneath when the ring is too small to
        carry text, which happens at small cell sizes.
        """
        c = self.canvas
        c.delete("conditions")
        radius = max(6.0, float(radius))
        band = max(5.0, radius * 0.46)

        for x, y, name, colour in markers:
            if not HEX_RE.match(str(colour)):
                colour = "#FFFFFF"
            halo = contrast_halo(colour)
            box = (x - radius, y - radius, x + radius, y + radius)
            c.create_oval(*box, outline=halo, width=band + 4,
                          tags="conditions")
            c.create_oval(*box, outline=colour, width=band, tags="conditions")

            placed = False
            if font_for is not None and band >= 9 and self.can_rotate_text:
                placed = self._band_text(x, y, radius, name.upper(), halo,
                                         font_for, band)
            if not placed:
                ly = y + radius + 11
                if ly > self.height - 8:
                    ly = y - radius - 11
                c.create_text(x + 1, ly + 1, text=name, anchor="center",
                              fill=halo, font=font, tags="conditions")
                c.create_text(x, ly, text=name, anchor="center", fill=colour,
                              font=font, tags="conditions")

    def _band_text(self, cx, cy, radius, text, fill, font_for, band):
        """Set text around the ring, twice, facing opposite ways.

        Each glyph is placed and rotated individually, since a canvas has no
        notion of text on a path. Returns False if it will not fit, so the
        caller can fall back.
        """
        usable = math.pi * radius * 0.78          # arc available to one copy
        size = int(band * 0.66)
        font = None
        while size >= 7:
            font = font_for(size)
            if sum(font.measure(ch) for ch in text) <= usable:
                break
            size -= 1
        else:
            return False

        widths = [font.measure(ch) for ch in text]
        total = sum(widths) / float(radius)       # arc length, in radians

        # Both copies are laid out in the same direction. That looks wrong and
        # is not: the lower one is upside down from here, which puts it the
        # right way up, and in the right order, for whoever sits opposite.
        for centre in (-math.pi / 2, math.pi / 2):
            angle = centre - total / 2
            for ch, width in zip(text, widths):
                step = width / float(radius)
                at = angle + step / 2
                # A glyph at the top of the ring stands upright, so the
                # rotation is its arc position turned back by a quarter turn.
                self.canvas.create_text(
                    cx + radius * math.cos(at),
                    cy + radius * math.sin(at),
                    text=ch, font=font, fill=fill, anchor="center",
                    angle=-(math.degrees(at) + 90) % 360,
                    tags="conditions")
                angle += step
        return True

    def clear_conditions(self):
        self.canvas.delete("conditions")

    def draw(self, kind, size, off_x, off_y, colour, weight):
        c = self.canvas
        c.delete("grid")
        w, h = self.width, self.height
        if kind == "Square":
            for x1, y1, x2, y2 in square_lines(w, h, size, off_x, off_y):
                c.create_line(x1, y1, x2, y2, fill=colour, width=weight, tags="grid")
        else:
            for pts in hex_polys(w, h, size, off_x, off_y,
                                 pointy=(kind == "Hex (pointy top)")):
                c.create_polygon(pts, outline=colour, fill="", width=weight,
                                 tags="grid")
        # Redrawing the grid puts its lines at the front of the canvas, which
        # buried any markers already placed. Everything else belongs on top of
        # the grid, so the grid is pushed to the back every time it is drawn.
        c.tag_lower("grid")


# ==========================================================================
# Colour picker
# ==========================================================================

class ColourPicker:
    """A colour picker drawn by us, so it follows the theme.

    Tk's colorchooser opens the operating system's dialog, which breaks out of
    the interface everywhere else in this program - and on Windows it is the
    old common dialog, which looks nothing like the rest. This is the familiar
    saturation/value square with a hue rail beside it, painted on canvases as a
    mosaic of small rectangles, since a plain canvas cannot draw a gradient.
    """

    SQUARE = 170          # unscaled px
    RAIL_W = 20
    CELLS = 24            # resolution of the square: CELLS x CELLS rectangles
    RAIL_STEPS = 96       # bands in the hue rail

    def __init__(self, app, parent, initial="#FFFFFF", title="Colour"):
        self.app = app
        self.result = None
        self.initial = initial if HEX_RE.match(str(initial)) else "#FFFFFF"
        px = app._px

        self.hue, self.sat, self.val = colorsys.rgb_to_hsv(
            *hex_to_rgb(self.initial)
        )

        self.win = tk.Toplevel(parent)
        self.win.withdraw()                      # placed before it is shown
        self.win.title(title)
        self.win.configure(bg=INK)
        self.win.transient(parent)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.cancel)

        outer = ttk.Frame(self.win, style="Shell.TFrame")
        outer.pack(fill="both", expand=True)
        card = ttk.Frame(outer, style="Card.TFrame")
        card.pack(fill="both", expand=True)
        inner = ttk.Frame(card, style="Card.TFrame")
        inner.pack(fill="both", expand=True, padx=px(14), pady=px(13))

        # square + hue rail ------------------------------------------------
        top = ttk.Frame(inner, style="Card.TFrame")
        top.pack(fill="x")

        side = px(self.SQUARE)
        self.square = tk.Canvas(top, width=side, height=side,
                                highlightthickness=1, highlightbackground=LINE,
                                bd=0, takefocus=0, cursor="crosshair")
        self.square.pack(side="left")
        self.square.bind("<Button-1>", self._square_pick)
        self.square.bind("<B1-Motion>", self._square_pick)

        self.rail = tk.Canvas(top, width=px(self.RAIL_W), height=side,
                              highlightthickness=1, highlightbackground=LINE,
                              bd=0, takefocus=0, cursor="sb_v_double_arrow")
        self.rail.pack(side="left", padx=(px(10), 0))
        self.rail.bind("<Button-1>", self._rail_pick)
        self.rail.bind("<B1-Motion>", self._rail_pick)

        # quick swatches ---------------------------------------------------
        ttk.Label(inner, text="QUICK", style="Head.TLabel").pack(
            anchor="w", pady=(px(11), px(5))
        )
        self.quick = tk.Canvas(inner, height=px(18), highlightthickness=0,
                               bd=0, takefocus=0, cursor="hand2")
        self.quick.pack(fill="x")
        self.quick.bind("<Button-1>", self._quick_pick)
        self.quick_colours = self._quick_palette()

        # before / after and hex ------------------------------------------
        readout = ttk.Frame(inner, style="Card.TFrame")
        readout.pack(fill="x", pady=(px(12), 0))
        self.compare = tk.Canvas(readout, width=px(72), height=px(24),
                                 highlightthickness=1,
                                 highlightbackground=LINE, bd=0, takefocus=0)
        self.compare.pack(side="left")
        ttk.Label(readout, text="was / now", style="Hint.TLabel").pack(
            side="left", padx=(px(6), 0)
        )
        self.hex_value = tk.StringVar(value=self.initial.upper())
        entry = ttk.Entry(readout, textvariable=self.hex_value,
                          font=app.f_num, width=9, justify="center")
        entry.pack(side="right")
        entry.bind("<Return>", lambda e: self._hex_typed())
        entry.bind("<FocusOut>", lambda e: self._hex_typed())

        # footer -----------------------------------------------------------
        ttk.Separator(outer, orient="horizontal").pack(fill="x")
        foot = ttk.Frame(outer, style="Shell.TFrame")
        foot.pack(fill="x", padx=px(14), pady=px(10))
        ttk.Button(foot, text="Choose", command=self.choose).pack(side="right")
        ttk.Button(foot, text="Cancel", command=self.cancel).pack(
            side="right", padx=(0, px(6))
        )

        self.win.bind("<Return>", lambda e: self.choose())
        self.win.bind("<Escape>", lambda e: self.cancel())

        self.win.update_idletasks()
        self._centre_on(parent)
        set_frame_mode(self.win)
        self.win.deiconify()
        self.win.update_idletasks()
        self._paint_rail()
        self._paint_square()
        self._paint_quick()
        self._paint_compare()

    # -- palette -----------------------------------------------------------

    def _quick_palette(self):
        greys = ["#000000", "#404040", "#808080", "#C0C0C0", "#FFFFFF"]
        hues = [rgb_to_hex(*colorsys.hsv_to_rgb(i / 8.0, 0.85, 0.95))
                for i in range(8)]
        return greys + hues

    # -- painting ----------------------------------------------------------

    def _paint_square(self):
        """Repaint the mosaic. Only needed when the hue changes."""
        c = self.square
        c.delete("mosaic")
        width = int(c["width"])
        height = int(c["height"])
        cells = self.CELLS
        step_x = width / float(cells)
        step_y = height / float(cells)
        for row in range(cells):
            value = 1.0 - row / float(cells - 1)
            for col in range(cells):
                sat = col / float(cells - 1)
                fill = rgb_to_hex(*colorsys.hsv_to_rgb(self.hue, sat, value))
                c.create_rectangle(col * step_x, row * step_y,
                                   (col + 1) * step_x + 1,
                                   (row + 1) * step_y + 1,
                                   fill=fill, outline="", tags="mosaic")
        c.tag_lower("mosaic")
        self._paint_marker()

    def _paint_marker(self):
        """Just the crosshair, so dragging stays cheap."""
        c = self.square
        c.delete("marker")
        width = int(c["width"])
        height = int(c["height"])
        x = self.sat * width
        y = (1.0 - self.val) * height
        # Outline in whichever of black or white will actually show up here.
        edge = "#000000" if self.val > 0.55 and self.sat < 0.65 else "#FFFFFF"
        r = self.app._px(5)
        c.create_oval(x - r, y - r, x + r, y + r, outline=edge, width=2,
                      tags="marker")

    def _paint_rail(self):
        c = self.rail
        c.delete("all")
        width = int(c["width"])
        height = int(c["height"])
        step = height / float(self.RAIL_STEPS)
        for i in range(self.RAIL_STEPS):
            fill = rgb_to_hex(*colorsys.hsv_to_rgb(i / float(self.RAIL_STEPS),
                                                   1.0, 1.0))
            c.create_rectangle(0, i * step, width, (i + 1) * step + 1,
                               fill=fill, outline="")
        y = self.hue * height
        c.create_line(0, y, width, y, fill="#FFFFFF", width=2)
        c.create_line(0, y, width, y, fill="#000000", width=1)

    def _paint_quick(self):
        c = self.quick
        c.delete("all")
        c.configure(bg=PANEL)
        box = self.app._px(18)
        gap = self.app._px(4)
        width = c.winfo_width()
        current = self.hex_value.get().upper()
        for index, colour in enumerate(self.quick_colours):
            x = index * (box + gap)
            if width > 1 and x + box > width:
                break
            c.create_rectangle(
                x, 0, x + box, box, fill=colour,
                outline=HILITE if colour.upper() == current else LINE,
                width=2 if colour.upper() == current else 1,
            )

    def _paint_compare(self):
        c = self.compare
        c.delete("all")
        width = int(c["width"])
        height = int(c["height"])
        c.create_rectangle(0, 0, width / 2, height,
                           fill=self.initial, outline="")
        c.create_rectangle(width / 2, 0, width, height,
                           fill=self.current_hex(), outline="")

    # -- interaction -------------------------------------------------------

    def current_hex(self):
        return rgb_to_hex(*colorsys.hsv_to_rgb(self.hue, self.sat, self.val))

    def _sync(self, hue_changed=False):
        self.hex_value.set(self.current_hex().upper())
        if hue_changed:
            self._paint_square()
            self._paint_rail()
        else:
            self._paint_marker()
        self._paint_quick()
        self._paint_compare()

    def _square_pick(self, event):
        width = max(1, int(self.square["width"]))
        height = max(1, int(self.square["height"]))
        self.sat = min(1.0, max(0.0, event.x / float(width)))
        self.val = min(1.0, max(0.0, 1.0 - event.y / float(height)))
        self._sync()

    def _rail_pick(self, event):
        height = max(1, int(self.rail["height"]))
        self.hue = min(0.9999, max(0.0, event.y / float(height)))
        self._sync(hue_changed=True)

    def _quick_pick(self, event):
        box = self.app._px(18)
        gap = self.app._px(4)
        index = int(event.x / (box + gap))
        if 0 <= index < len(self.quick_colours) and event.y <= box:
            self._set_hex(self.quick_colours[index])

    def _hex_typed(self):
        value = self.hex_value.get().strip()
        if not value.startswith("#"):
            value = "#" + value
        if HEX_RE.match(value):
            self._set_hex(value)
        else:
            self.hex_value.set(self.current_hex().upper())

    def _set_hex(self, value):
        self.hue, self.sat, self.val = colorsys.rgb_to_hsv(*hex_to_rgb(value))
        self._sync(hue_changed=True)

    # -- window ------------------------------------------------------------

    def _centre_on(self, parent):
        try:
            self.win.update_idletasks()
            width = max(self.win.winfo_reqwidth(), self.win.winfo_width())
            x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
            y = parent.winfo_rooty() + self.app._px(50)
            self.win.geometry("+%d+%d" % (max(0, x), max(0, y)))
        except tk.TclError:
            pass

    def choose(self):
        self.result = self.current_hex().upper()
        self._close()

    def cancel(self):
        self.result = None
        self._close()

    def _close(self):
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()

    def show(self):
        """Run modally and return a hex string, or None if cancelled."""
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        self.win.wait_window()
        return self.result


# ==========================================================================
# Settings window
# ==========================================================================

class SettingsWindow:
    """Tabbed settings: startup behaviour, hotkeys, and themes.

    Each tab commits on its own terms rather than behind one global Apply.
    Startup options and themes take effect the moment they are changed, since
    both are instantly reversible and a theme is its own preview. Hotkeys are
    the exception: they need an explicit Apply, because registering them can
    fail when another program already owns a combo, and that outcome has to be
    reported per row.
    """

    def __init__(self, app):
        self.app = app
        self.rows = {}
        self.role_widgets = {}

        self.win = tk.Toplevel(app.root)
        # Hidden until it has been built and positioned. Tk maps a new window
        # at the default spot immediately, so moving it afterwards makes it
        # flash in the top-left corner of the screen first.
        self.win.withdraw()
        self.win.title("Settings")
        self.win.configure(bg=INK)
        self.win.transient(app.root)
        self.win.resizable(True, True)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self._build()
        self._load_hotkeys(app.hotkeys)

        self.win.update_idletasks()
        self.win.minsize(self.win.winfo_reqwidth(), self.win.winfo_reqheight())
        self._centre_on_parent()
        set_frame_mode(self.win)
        self.win.deiconify()
        self.win.focus_set()

    # -- shell -------------------------------------------------------------

    def _build(self):
        pad = self.app._px

        outer = ttk.Frame(self.win, style="Shell.TFrame")
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer, style="Shell.TFrame")
        head.pack(fill="x", padx=pad(14), pady=pad(12))
        ttk.Label(head, text="Settings", style="App.TLabel").pack(side="left")

        self._build_tab_strip(outer)
        self._add_page("General", self._build_general())
        self._add_page("Hotkeys", self._build_hotkeys())
        self._add_page("Bands", self._build_bands())
        self._add_page("Conditions", self._build_conditions())
        self._add_page("Theme", self._build_themes())
        self._select_page(0)
        self._lock_tab_size()

        ttk.Separator(outer, orient="horizontal").pack(fill="x", pady=(pad(10), 0))
        foot = ttk.Frame(outer, style="Shell.TFrame")
        foot.pack(fill="x", padx=pad(14), pady=pad(10))
        ttk.Button(foot, text="Close", command=self.close).pack(side="right")
        ttk.Label(foot, text="Changes are saved as you make them.",
                  style="Shell.TLabel").pack(side="left")

    def _build_tab_strip(self, outer):
        """A hand-built tab strip.

        Under clam, ttk's notebook draws the *selected* tab smaller than its
        neighbours, and neither the expand nor the padding style map reliably
        overrides that. Building the strip directly costs a few more lines and
        gives exact control, so the active tab can genuinely be the largest.
        """
        px = self.app._px
        self.tab_bar = tk.Frame(outer, bg=INK)
        self.tab_bar.pack(fill="x", padx=px(10))
        self.tab_body = tk.Frame(outer, bg=PANEL)
        self.tab_body.pack(fill="both", expand=True, padx=px(10))
        self.tab_items = []
        self.tab_pages = []
        self.active_tab = 0

    def _add_page(self, title, page):
        px = self.app._px
        index = len(self.tab_items)
        holder = tk.Frame(self.tab_bar, bg=INK)
        holder.pack(side="left", padx=(0, px(3)))
        accent = tk.Frame(holder, height=px(2), bg=INK)
        accent.pack(fill="x")
        label = tk.Label(holder, text=title, font=self.app.f_body,
                         bg=INK, fg=MUTE, cursor="hand2")
        label.pack(fill="both", expand=True)
        for widget in (holder, accent, label):
            widget.bind("<Button-1>", lambda e, i=index: self._select_page(i))
        self.tab_items.append({"holder": holder, "accent": accent,
                               "label": label})
        self.tab_pages.append(page)

    def _select_page(self, index):
        self.active_tab = index
        for page in self.tab_pages:
            page.pack_forget()
        self.tab_pages[index].pack(fill="both", expand=True)
        self._restyle_tabs()

    def _restyle_tabs(self):
        """The selected tab is taller, brighter, and fused with the panel."""
        px = self.app._px
        # Derived from the panel so it stays distinct in every theme, including
        # Classic, where the chassis and panel colours are identical.
        resting = blend(PANEL, LINE, 0.5)
        for index, item in enumerate(self.tab_items):
            active = index == self.active_tab
            background = PANEL if active else resting
            item["holder"].configure(bg=background)
            item["accent"].configure(bg=HILITE if active else resting,
                                     height=px(3) if active else px(2))
            item["label"].configure(
                bg=background, fg=TEXT if active else MUTE,
                padx=px(18) if active else px(14),
                pady=px(9) if active else px(5),
            )
        self.tab_bar.configure(bg=INK)
        self.tab_body.configure(bg=PANEL)

    def _lock_tab_size(self):
        """Freeze the page area to the largest page.

        Each tab needs a different amount of room, so without this the window
        jumps size every time you switch - which is disorienting and moves the
        buttons out from under the pointer. Measuring each page and holding the
        container at the maximum keeps the window still.
        """
        heights, widths = [], []
        for page in self.tab_pages:
            page.pack(fill="both", expand=True)
            self.win.update_idletasks()
            heights.append(page.winfo_reqheight())
            widths.append(page.winfo_reqwidth())
            page.pack_forget()
        if heights:
            self.tab_body.configure(width=max(widths), height=max(heights))
            self.tab_body.pack_propagate(False)
        self._select_page(self.active_tab)

    def _tab(self):
        holder = ttk.Frame(self.tab_body, style="Card.TFrame")
        inner = ttk.Frame(holder, style="Card.TFrame")
        inner.pack(fill="both", expand=True,
                   padx=self.app._px(14), pady=self.app._px(13))
        return holder, inner

    def _note(self, parent, text, pady=(0, 0)):
        label = ttk.Label(parent, text=text, style="Hint.TLabel",
                          justify="left", wraplength=self.app._px(430))
        label.pack(anchor="w", fill="x", pady=pady)
        return label

    # -- General tab -------------------------------------------------------

    def _build_general(self):
        pad = self.app._px
        holder, inner = self._tab()

        ttk.Label(inner, text="STARTUP", style="Head.TLabel").pack(
            anchor="w", pady=(0, pad(8))
        )

        # The registry, not the settings file, decides whether this is on -
        # the entry may have been removed by other means since last time.
        enabled, _recorded = autostart_state()
        self.autostart = tk.BooleanVar(value=enabled)
        self.autostart_check = ttk.Checkbutton(
            inner, text="Start with Windows", variable=self.autostart,
            command=self._toggle_autostart,
        )
        self.autostart_check.pack(anchor="w")
        self._note(inner,
                   "Registers this program for the current user only, so no "
                   "administrator rights are needed. If you move or rename the "
                   "file, the entry is repaired the next time it runs.",
                   pady=(pad(3), pad(10)))

        ttk.Checkbutton(inner, text="Start minimised",
                        variable=self.start_minimised_proxy(),
                        command=self._toggle_minimised).pack(anchor="w")
        self._note(inner,
                   "The grid still appears - only this panel starts out of the "
                   "way, on the taskbar.",
                   pady=(pad(3), pad(10)))

        ttk.Checkbutton(inner, text="Show the overlay at startup",
                        variable=self.app.overlay_on_start,
                        command=self._toggle_overlay_start).pack(anchor="w")
        self._note(inner,
                   "Off means the grid waits until you switch it on, which "
                   "suits starting with Windows on a machine you are not "
                   "always running a game on.",
                   pady=(pad(3), 0))

        ttk.Separator(inner, orient="horizontal").pack(fill="x",
                                                       pady=(pad(12), pad(11)))
        ttk.Label(inner, text="UPDATES", style="Head.TLabel").pack(
            anchor="w", pady=(0, pad(8)))

        ttk.Checkbutton(inner, text="Look for a newer version at startup",
                        variable=self.app.check_updates,
                        command=self._toggle_updates).pack(anchor="w")
        self._note(inner,
                   "Asks GitHub once a day whether a newer release exists, and "
                   "says so. It never downloads or installs anything: finding "
                   "an update gives you a button that opens the download page. "
                   "Nothing about you is sent, and switching this off stops "
                   "Gridwyrm using the network at all.",
                   pady=(pad(3), pad(8)))

        check_row = ttk.Frame(inner, style="Card.TFrame")
        check_row.pack(fill="x")
        ttk.Button(check_row, text="Check now",
                   command=lambda: self.app.check_for_update(manual=True)
                   ).pack(side="left")
        ttk.Label(check_row, textvariable=self.app.update_notice,
                  style="Hint.TLabel").pack(side="left",
                                            padx=(pad(8), 0))
        ttk.Label(inner, text="This copy is version %s." % VERSION,
                  style="Hint.TLabel").pack(anchor="w", pady=(pad(6), 0))

        self.general_status = ttk.Label(inner, text="", style="Hint.TLabel",
                                       justify="left",
                                       wraplength=self.app._px(430))
        self.general_status.pack(anchor="w", fill="x", pady=(pad(10), 0))

        if not IS_WINDOWS:
            self.autostart_check.state(["disabled"])
            self.general_status.configure(
                text="Starting with the system needs Windows."
            )
        return holder

    def start_minimised_proxy(self):
        return self.app.start_minimised

    def _toggle_autostart(self):
        wanted = bool(self.autostart.get())
        ok, message = set_autostart(wanted)
        if ok:
            self.general_status.configure(
                text="Will start with Windows." if wanted
                else "Will no longer start with Windows."
            )
        else:
            self.autostart.set(not wanted)       # reflect what really happened
            self.general_status.configure(
                text="Could not change the registry entry: %s" % message
            )

    def _toggle_minimised(self):
        self.general_status.configure(
            text="This panel will start minimised."
            if self.app.start_minimised.get()
            else "This panel will start visible."
        )

    def _toggle_updates(self):
        self.general_status.configure(
            text="Gridwyrm will look for a newer version at startup."
            if self.app.check_updates.get()
            else "Gridwyrm will not use the network at all.")

    def _toggle_overlay_start(self):
        self.general_status.configure(
            text="The grid will be showing when the app starts."
            if self.app.overlay_on_start.get()
            else "The grid will start switched off."
        )

    # -- Hotkeys tab -------------------------------------------------------

    def _build_hotkeys(self):
        pad = self.app._px
        holder, inner = self._tab()

        self._note(inner,
                   "These work anywhere in Windows, even while the map has "
                   "focus. A hotkey is claimed system-wide, so avoid combos "
                   "your other programs need \u2014 that is why the defaults "
                   "use two or three modifiers.",
                   pady=(0, pad(10)))

        table = ttk.Frame(inner, style="Card.TFrame")
        table.pack(fill="both", expand=True)
        table.columnconfigure(0, weight=1)

        ttk.Label(table, text="ACTION", style="Head.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, pad(5))
        )
        for column, title in ((1, "MODIFIERS"), (2, "KEY")):
            ttk.Label(table, text=title, style="Head.TLabel").grid(
                row=0, column=column, sticky="w", padx=(pad(8), 0),
                pady=(0, pad(5))
            )

        for index, (action, label, _repeat) in enumerate(ACTIONS, start=1):
            ttk.Label(table, text=label, style="TLabel").grid(
                row=index, column=0, sticky="w", pady=pad(2)
            )
            mods, key = tk.StringVar(), tk.StringVar()
            mods_box = self.app.register_combo(ttk.Combobox(
                table, values=MODIFIER_ORDER, textvariable=mods,
                state="readonly", width=17))
            mods_box.grid(row=index, column=1, sticky="w",
                          padx=(pad(8), 0), pady=pad(2))
            key_box = self.app.register_combo(ttk.Combobox(
                table, values=KEY_ORDER, textvariable=key,
                state="readonly", width=10))
            key_box.grid(row=index, column=2, sticky="w",
                         padx=(pad(8), 0), pady=pad(2))
            status = ttk.Label(table, text="", style="Hint.TLabel", width=15)
            status.grid(row=index, column=3, sticky="w", padx=(pad(8), 0))
            self.rows[action] = {"mods": mods, "key": key, "status": status,
                                 "key_box": key_box}
            mods.trace_add("write", lambda *_a, a=action: self._sync_row(a))

        self.hotkey_status = ttk.Label(inner, text="", style="Hint.TLabel",
                                       justify="left",
                                       wraplength=self.app._px(430))
        self.hotkey_status.pack(anchor="w", fill="x", pady=(pad(10), 0))

        if not IS_WINDOWS:
            self.hotkey_status.configure(
                text="System-wide hotkeys need Windows. The shortcuts listed "
                     "at the bottom of the main panel still work while the "
                     "panel has focus."
            )

        buttons = ttk.Frame(inner, style="Card.TFrame")
        buttons.pack(fill="x", pady=(pad(10), 0))
        ttk.Button(buttons, text="Apply hotkeys",
                   command=self.apply_hotkeys).pack(side="right")
        ttk.Button(buttons, text="Restore defaults",
                   command=self.restore_hotkey_defaults).pack(side="left")
        return holder

    def _sync_row(self, action):
        """A disabled row has no key to choose."""
        row = self.rows[action]
        off = row["mods"].get() == HOTKEY_OFF
        row["key_box"].configure(state="disabled" if off else "readonly")
        if off:
            row["status"].configure(text="")

    def _load_hotkeys(self, hotkeys):
        for action, _label, _repeat in ACTIONS:
            mods, key = hotkeys.get(action, DEFAULT_HOTKEYS[action])
            self.rows[action]["mods"].set(mods)
            self.rows[action]["key"].set(key or "G")
            self._sync_row(action)

    def restore_hotkey_defaults(self):
        self._load_hotkeys(DEFAULT_HOTKEYS)
        self.hotkey_status.configure(
            text="Defaults restored. Choose Apply hotkeys to use them."
        )

    def apply_hotkeys(self):
        bindings = {
            action: [self.rows[action]["mods"].get(),
                     self.rows[action]["key"].get()]
            for action, _label, _repeat in ACTIONS
        }

        # Catch two actions sharing one combo before Windows does.
        seen, clashes = {}, set()
        for action, pair in bindings.items():
            if pair[0] == HOTKEY_OFF:
                continue
            signature = (pair[0], pair[1])
            if signature in seen:
                clashes.add(action)
                clashes.add(seen[signature])
            seen[signature] = action

        for action, _label, _repeat in ACTIONS:
            self.rows[action]["status"].configure(text="")

        if clashes:
            for action in clashes:
                self.rows[action]["status"].configure(text="duplicate")
            self.hotkey_status.configure(
                text="Two actions share a combo. Change one of the rows "
                     "marked duplicate."
            )
            return

        failures = self.app.apply_hotkeys(bindings)
        if not failures:
            self.hotkey_status.configure(text="All hotkeys active.")
            return
        for action, reason in failures.items():
            self.rows[action]["status"].configure(text=reason)
        self.hotkey_status.configure(
            text="Some combos were refused, usually because another program "
                 "already owns them. Everything else is active \u2014 pick "
                 "different keys for the rows marked above."
        )

    # -- Bands tab ---------------------------------------------------------

    def _build_bands(self):
        pad = self.app._px
        holder, inner = self._tab()

        self._note(inner,
                   "A name and a distance for each ring. Distances are in "
                   "whatever unit the panel is set to, and they are sorted for "
                   "you, so the order you enter them in does not matter.",
                   pady=(0, pad(10)))

        # StringVars live in self.band_rows and outlast the widgets, so the grid
        # can be rebuilt wholesale whenever a row is added or removed without
        # anyone losing what they were typing.
        self.band_rows = [
            {"name": tk.StringVar(value=name),
             "distance": tk.StringVar(value=tidy_number(distance, 2))}
            for name, distance in self.app.bands
        ]

        self.band_grid = ttk.Frame(inner, style="Card.TFrame")
        self.band_grid.pack(fill="x")

        self.add_band_button = ttk.Button(inner, text="Add a band",
                                         command=self.add_band_row)
        self.add_band_button.pack(anchor="w", pady=(pad(10), 0))

        self.band_status = ttk.Label(inner, text="", style="Hint.TLabel",
                                     justify="left",
                                     wraplength=self.app._px(430))
        self.band_status.pack(anchor="w", fill="x", pady=(pad(8), 0))

        buttons = ttk.Frame(inner, style="Card.TFrame")
        buttons.pack(fill="x", pady=(pad(10), 0))
        ttk.Button(buttons, text="Apply bands",
                   command=self.apply_bands).pack(side="right")
        ttk.Button(buttons, text="Restore defaults",
                   command=self.restore_bands).pack(side="left")

        self._rebuild_band_rows()
        return holder

    def _rebuild_band_rows(self):
        """Redraw the rows. Cheap, and it keeps the columns aligned."""
        pad = self.app._px
        for child in self.band_grid.winfo_children():
            child.destroy()
        self.band_grid.columnconfigure(0, weight=1)

        unit = self.app.unit.get()
        heading = "DISTANCE" if unit == "squares" else "DISTANCE (%s)" % unit
        ttk.Label(self.band_grid, text="NAME", style="Head.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, pad(5)))
        ttk.Label(self.band_grid, text=heading, style="Head.TLabel").grid(
            row=0, column=1, sticky="w", padx=(pad(8), 0), pady=(0, pad(5)))

        removable = len(self.band_rows) > 1
        for index, row in enumerate(self.band_rows, start=1):
            ttk.Entry(self.band_grid, textvariable=row["name"]).grid(
                row=index, column=0, sticky="we", pady=pad(2))
            ttk.Entry(self.band_grid, textvariable=row["distance"],
                      font=self.app.f_num, width=9, justify="right").grid(
                row=index, column=1, sticky="w", padx=(pad(8), 0), pady=pad(2))
            remove = ttk.Button(self.band_grid, text="\u00d7", width=3,
                                command=lambda r=row: self.remove_band_row(r))
            remove.grid(row=index, column=2, padx=(pad(6), 0), pady=pad(2))
            if not removable:
                remove.state(["disabled"])       # never leave the list empty

        full = len(self.band_rows) >= MAX_BANDS
        self.add_band_button.state(["disabled"] if full else ["!disabled"])
        if full:
            self.band_status.configure(
                text="%d bands is as many as stays readable on a map."
                     % MAX_BANDS)

    def add_band_row(self):
        if len(self.band_rows) >= MAX_BANDS:
            return
        self.band_rows.append({"name": tk.StringVar(value=""),
                               "distance": tk.StringVar(value="")})
        self._rebuild_band_rows()
        self.band_status.configure(text="Fill the new row, then Apply bands.")

    def remove_band_row(self, row):
        if len(self.band_rows) <= 1:
            return
        self.band_rows.remove(row)
        self._rebuild_band_rows()
        self.band_status.configure(text="Choose Apply bands to confirm.")

    def apply_bands(self):
        rows = [(row["name"].get(), row["distance"].get())
                for row in self.band_rows]
        error = self.app.set_bands(rows)
        if error:
            self.band_status.configure(text=error)
            return
        # Reload from what was accepted, so the rows show the sorted order and
        # the tidied numbers rather than whatever was typed.
        self.band_rows = [
            {"name": tk.StringVar(value=name),
             "distance": tk.StringVar(value=tidy_number(distance, 2))}
            for name, distance in self.app.bands
        ]
        self._rebuild_band_rows()
        self.band_status.configure(
            text="%d bands in use." % len(self.app.bands))

    def restore_bands(self):
        self.band_rows = [
            {"name": tk.StringVar(value=name),
             "distance": tk.StringVar(value=tidy_number(distance, 2))}
            for name, distance in DEFAULT_BANDS
        ]
        self._rebuild_band_rows()
        self.band_status.configure(
            text="Defaults restored. Choose Apply bands to use them.")

    # -- Conditions tab ----------------------------------------------------

    def _build_conditions(self):
        pad = self.app._px
        holder, inner = self._tab()

        self._note(inner,
                   "A name and a colour for each condition. Click a swatch to "
                   "change it. Markers already on the map follow any change you "
                   "make here.",
                   pady=(0, pad(10)))

        self.cond_rows = [
            {"name": tk.StringVar(value=name),
             "colour": tk.StringVar(value=colour)}
            for name, colour in self.app.conditions
        ]

        self.cond_grid = ttk.Frame(inner, style="Card.TFrame")
        self.cond_grid.pack(fill="x")

        self.add_cond_button = ttk.Button(inner, text="Add a condition",
                                         command=self.add_cond_row)
        self.add_cond_button.pack(anchor="w", pady=(pad(10), 0))

        self.cond_status = ttk.Label(inner, text="", style="Hint.TLabel",
                                     justify="left",
                                     wraplength=self.app._px(430))
        self.cond_status.pack(anchor="w", fill="x", pady=(pad(8), 0))

        buttons = ttk.Frame(inner, style="Card.TFrame")
        buttons.pack(fill="x", pady=(pad(10), 0))
        ttk.Button(buttons, text="Apply conditions",
                   command=self.apply_conditions).pack(side="right")
        ttk.Button(buttons, text="Restore defaults",
                   command=self.restore_conditions).pack(side="left")

        self._rebuild_cond_rows()
        return holder

    def _rebuild_cond_rows(self):
        """Two columns. The full condition list in one would run off a screen."""
        pad = self.app._px
        for child in self.cond_grid.winfo_children():
            child.destroy()

        columns = 2 if len(self.cond_rows) > 8 else 1
        for column in range(columns):
            self.cond_grid.columnconfigure(column * 4, weight=1)

        for column in range(columns):
            left = column * 4
            ttk.Label(self.cond_grid, text="NAME", style="Head.TLabel").grid(
                row=0, column=left, sticky="w", pady=(0, pad(5)),
                padx=(pad(12) if column else 0, 0))
            ttk.Label(self.cond_grid, text="COLOUR",
                      style="Head.TLabel").grid(
                row=0, column=left + 1, sticky="w", padx=(pad(8), 0),
                pady=(0, pad(5)))

        per_column = -(-len(self.cond_rows) // columns)     # round up
        removable = len(self.cond_rows) > 1
        for index, row in enumerate(self.cond_rows):
            column = index // per_column
            left = column * 4
            line = index % per_column + 1

            ttk.Entry(self.cond_grid, textvariable=row["name"],
                      width=16).grid(
                row=line, column=left, sticky="we", pady=pad(2),
                padx=(pad(12) if column else 0, 0))

            swatch = tk.Canvas(self.cond_grid, width=pad(40), height=pad(18),
                               highlightthickness=1, bd=0, takefocus=0,
                               cursor="hand2")
            swatch.grid(row=line, column=left + 1, sticky="w",
                        padx=(pad(8), 0), pady=pad(2))
            self._paint_cond_swatch(swatch, row["colour"].get())
            swatch.bind("<Button-1>",
                        lambda e, r=row, s=swatch: self.pick_cond_colour(r, s))

            remove = ttk.Button(self.cond_grid, text="\u00d7", width=3,
                                command=lambda r=row: self.remove_cond_row(r))
            remove.grid(row=line, column=left + 2, padx=(pad(5), 0),
                        pady=pad(2))
            if not removable:
                remove.state(["disabled"])

        full = len(self.cond_rows) >= MAX_CONDITIONS
        self.add_cond_button.state(["disabled"] if full else ["!disabled"])
        if full:
            self.cond_status.configure(
                text="%d conditions is as many as fits." % MAX_CONDITIONS)

    def _paint_cond_swatch(self, swatch, colour):
        try:
            swatch.configure(bg=colour if HEX_RE.match(str(colour)) else "#808080",
                             highlightbackground=LINE)
        except tk.TclError:
            swatch.configure(bg="#808080", highlightbackground=LINE)

    def pick_cond_colour(self, row, swatch):
        chosen = ColourPicker(self.app, self.win, row["colour"].get(),
                              "Colour for %s" % (row["name"].get() or "condition")
                              ).show()
        if chosen:
            row["colour"].set(chosen)
            self._paint_cond_swatch(swatch, chosen)

    def add_cond_row(self):
        if len(self.cond_rows) >= MAX_CONDITIONS:
            return
        self.cond_rows.append({"name": tk.StringVar(value=""),
                               "colour": tk.StringVar(value="#FFFFFF")})
        self._rebuild_cond_rows()
        self.cond_status.configure(
            text="Name the new row, pick a colour, then Apply conditions.")

    def remove_cond_row(self, row):
        if len(self.cond_rows) <= 1:
            return
        self.cond_rows.remove(row)
        self._rebuild_cond_rows()
        self.cond_status.configure(text="Choose Apply conditions to confirm.")

    def apply_conditions(self):
        rows = [(row["name"].get(), row["colour"].get())
                for row in self.cond_rows]
        error = self.app.set_conditions(rows)
        if error:
            self.cond_status.configure(text=error)
            return
        self.cond_rows = [
            {"name": tk.StringVar(value=name),
             "colour": tk.StringVar(value=colour)}
            for name, colour in self.app.conditions
        ]
        self._rebuild_cond_rows()
        self.cond_status.configure(
            text="%d conditions in use." % len(self.app.conditions))

    def restore_conditions(self):
        self.cond_rows = [
            {"name": tk.StringVar(value=name),
             "colour": tk.StringVar(value=colour)}
            for name, colour in DEFAULT_CONDITIONS
        ]
        self._rebuild_cond_rows()
        self.cond_status.configure(
            text="Defaults restored. Choose Apply conditions to use them.")

    # -- Theme tab ---------------------------------------------------------

    def _build_themes(self):
        pad = self.app._px
        holder, inner = self._tab()

        picker = ttk.Frame(inner, style="Card.TFrame")
        picker.pack(fill="x")
        ttk.Label(picker, text="Theme", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        self.theme_choice = tk.StringVar(value=self.app.theme_name)
        self.app.register_combo(ttk.Combobox(
            picker, values=list(THEME_ORDER), textvariable=self.theme_choice,
            state="readonly")).pack(side="left", fill="x", expand=True)
        self.theme_choice.trace_add("write", lambda *_: self._choose_theme())

        self.theme_note = self._note(inner, "", pady=(pad(8), pad(12)))

        ttk.Separator(inner, orient="horizontal").pack(fill="x")
        self.custom_head = ttk.Label(inner, text="CUSTOM COLOURS",
                                     style="Head.TLabel")
        self.custom_head.pack(anchor="w", pady=(pad(11), pad(8)))

        table = ttk.Frame(inner, style="Card.TFrame")
        table.pack(fill="x")
        table.columnconfigure(1, weight=1)

        for index, (role, label) in enumerate(THEME_ROLES):
            ttk.Label(table, text=label, style="TLabel").grid(
                row=index, column=0, sticky="w", pady=pad(2)
            )
            swatch = tk.Canvas(table, width=pad(34), height=pad(18),
                               highlightthickness=1, bd=0, takefocus=0,
                               cursor="hand2")
            swatch.grid(row=index, column=1, sticky="w",
                        padx=(pad(8), pad(8)), pady=pad(2))
            swatch.bind("<Button-1>", lambda e, r=role: self._pick_role(r))
            value = tk.StringVar()
            entry = ttk.Entry(table, textvariable=value, font=self.app.f_num,
                              width=9)
            entry.grid(row=index, column=2, sticky="w", pady=pad(2))
            entry.bind("<Return>", lambda e, r=role: self._commit_role(r))
            entry.bind("<FocusOut>", lambda e, r=role: self._commit_role(r))
            button = ttk.Button(table, text="Pick\u2026",
                                command=lambda r=role: self._pick_role(r))
            button.grid(row=index, column=3, sticky="w", padx=(pad(6), 0),
                        pady=pad(2))
            self.role_widgets[role] = {"swatch": swatch, "value": value,
                                       "entry": entry, "button": button}

        actions = ttk.Frame(inner, style="Card.TFrame")
        actions.pack(fill="x", pady=(pad(10), 0))
        self.copy_button = ttk.Button(
            actions, text="Start a custom theme from this one",
            command=self._seed_custom,
        )
        self.copy_button.pack(side="left")

        self.theme_status = ttk.Label(inner, text="", style="Hint.TLabel",
                                      justify="left",
                                      wraplength=self.app._px(430))
        self.theme_status.pack(anchor="w", fill="x", pady=(pad(8), 0))

        self._load_role_rows()
        self._sync_custom_state()
        return holder

    def _choose_theme(self):
        name = self.theme_choice.get()
        self.app.apply_theme(name)
        self._sync_custom_state()

    def _sync_custom_state(self):
        """Only the Custom theme is editable; the rest are shown as they are."""
        custom = self.theme_choice.get() == "Custom"
        state = "normal" if custom else "disabled"
        for widgets in self.role_widgets.values():
            widgets["entry"].configure(state=state)
            widgets["button"].configure(state=state)
        self.custom_head.configure(
            text="CUSTOM COLOURS" if custom else "COLOURS IN THIS THEME"
        )
        self.theme_note.configure(
            text=THEME_NOTES.get(self.theme_choice.get(), "")
        )
        self.theme_status.configure(
            text="" if custom else
            "Read-only. Use the button below to start a custom theme from these."
        )
        self._load_role_rows()

    def _load_role_rows(self):
        """Show the colours of whichever theme is selected.

        Reading from the stored custom theme regardless of selection meant that
        choosing Dark still displayed leftover custom values - wrong
        information presented as fact.
        """
        resolved = resolve_theme(self.theme_choice.get(), self.app.custom_theme)
        for role, widgets in self.role_widgets.items():
            colour = resolved.get(role, "#000000")
            widgets["value"].set(colour)
            self._paint_swatch(role, colour)

    def _paint_swatch(self, role, colour):
        swatch = self.role_widgets[role]["swatch"]
        swatch.delete("all")
        try:
            swatch.configure(bg=colour, highlightbackground=LINE)
        except tk.TclError:
            swatch.configure(bg="#808080", highlightbackground=LINE)

    def _pick_role(self, role):
        if self.theme_choice.get() != "Custom":
            return
        current = self.role_widgets[role]["value"].get()
        chosen = ColourPicker(
            self.app, self.win,
            current if HEX_RE.match(current) else "#808080",
            "Colour for %s" % dict(THEME_ROLES)[role],
        ).show()
        if chosen:
            self.role_widgets[role]["value"].set(chosen.upper())
            self._commit_role(role)

    def _commit_role(self, role):
        if self.theme_choice.get() != "Custom":
            return
        value = self.role_widgets[role]["value"].get().strip()
        if not value.startswith("#"):
            value = "#" + value
        if not HEX_RE.match(value):
            self.theme_status.configure(
                text="%s needs a six-digit hex colour, such as #1E222B."
                     % dict(THEME_ROLES)[role]
            )
            self._load_role_rows()
            return
        value = value.upper()
        self.app.custom_theme[role] = value
        self.theme_status.configure(text="")
        self.app.apply_theme("Custom", self.app.custom_theme)
        self._load_role_rows()

    def _seed_custom(self):
        """Start a custom theme from the one currently selected."""
        source = resolve_theme(self.theme_choice.get(), self.app.custom_theme)
        self.app.custom_theme = {role: source[role] for role in ROLE_KEYS}
        # Setting the picker applies the theme and re-syncs the rows.
        self.theme_choice.set("Custom")
        self.theme_status.configure(
            text="Copied. Edit any colour above to see it applied at once."
        )

    # -- window ------------------------------------------------------------

    def restyle(self):
        """Follow a live theme change."""
        try:
            self.win.configure(bg=INK)
            self._restyle_tabs()
            for role in self.role_widgets:
                self._paint_swatch(role, self.role_widgets[role]["value"].get())
            set_frame_mode(self.win)
        except tk.TclError:
            pass

    def _centre_on_parent(self):
        # winfo_width is 1 until a window is mapped, so the requested size is
        # what to centre against while it is still hidden.
        try:
            parent = self.app.root
            width = max(self.win.winfo_reqwidth(), self.win.winfo_width())
            x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
            y = parent.winfo_rooty() + self.app._px(40)
            self.win.geometry("+%d+%d" % (max(0, x), max(0, y)))
        except tk.TclError:
            pass

    def close(self):
        self.app.settings_window = None
        self.win.destroy()


# ==========================================================================
# Control panel
# ==========================================================================

class App:
    GRID_TYPES = ("Square", "Hex (pointy top)", "Hex (flat top)")

    # Below this panel width, value rows stack onto two lines.
    NARROW_AT = 380

    def __init__(self):
        hide_own_console()
        # Before any window exists, or the taskbar groups this under whatever
        # launched it and shows that program's icon.
        claim_taskbar_identity()
        self._fault_log = enable_fault_log()
        log_event("---- start  pid=%s  frozen=%s  python=%s"
                  % (os.getpid(), bool(getattr(sys, "frozen", False)),
                     sys.version.split()[0]))

        self.root = tk.Tk()
        self.root.title("Gridwyrm")
        self.root.configure(bg=INK)
        self.root.resizable(True, True)

        dpi = screen_dpi(self.root)
        self.s = min(2.0, max(1.0, dpi / 96.0))
        self.root.tk.call("tk", "scaling", dpi / 72.0)

        self.monitors = list_monitors() or [
            (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        ]
        saved = load_settings()

        # Theme first: everything built afterwards reads these colours.
        self.theme_name = saved.get("theme", "Dark")
        if self.theme_name not in THEME_ORDER:
            self.theme_name = "Dark"
        self.custom_theme = {
            key: value
            for key, value in (saved.get("custom_theme") or {}).items()
            if key in ROLE_KEYS and HEX_RE.match(str(value))
        }
        apply_palette(resolve_theme(self.theme_name, self.custom_theme))
        self.root.configure(bg=INK)
        self._combos = []
        self._swatch_strips = []
        self.start_minimised = tk.BooleanVar(
            value=bool(saved.get("start_minimised", False))
        )
        refresh_autostart_path()

        self.screen_choice = tk.StringVar()
        self.region = tk.StringVar(value=saved.get("region", ""))
        self.grid_type = tk.StringVar(value=saved.get("grid_type", "Square"))
        self.cell = tk.DoubleVar(value=saved.get("cell", 64.0))
        self.off_x = tk.DoubleVar(value=saved.get("off_x", 0.0))
        self.off_y = tk.DoubleVar(value=saved.get("off_y", 0.0))
        self.line_w = tk.IntVar(value=saved.get("line_w", 1))
        self.opacity = tk.IntVar(value=saved.get("opacity", 70))
        self.colour = tk.StringVar(value=saved.get("colour", "#FFFFFF"))
        self.preview_image_path = saved.get("preview_image", "") or ""
        self.preview_photo = None
        self._photo_key = None
        self.backdrop_label = tk.StringVar(value="Built-in sample map")
        self.overlay_on_start = tk.BooleanVar(
            value=bool(saved.get("overlay_on_start", True))
        )
        self.visible = tk.BooleanVar(value=bool(self.overlay_on_start.get()))
        self.click_through = tk.BooleanVar(value=saved.get("click_through", True))
        self.per_square = tk.DoubleVar(value=saved.get("per_square", 5.0))
        self.unit = tk.StringVar(value=saved.get("unit", "ft"))
        self.diagonal_rule = tk.StringVar(
            value=saved.get("diagonal_rule", DIAGONAL_RULES[0]))
        if self.diagonal_rule.get() not in DIAGONAL_RULES:
            self.diagonal_rule.set(DIAGONAL_RULES[0])
        if self.unit.get() not in UNIT_CHOICES:
            self.unit.set("ft")
        self.measure_readout = tk.StringVar(value="")
        self.span_squares = tk.StringVar(value="")
        self.measure = None                      # None, or the span in progress
        self.bands, _error = parse_bands(saved.get("bands", "")) or (None, "")
        if not self.bands:
            self.bands = [list(pair) for pair in DEFAULT_BANDS]
        self.range_mode = tk.StringVar(value=saved.get("range_mode", "DM only"))
        if self.range_mode.get() not in RANGE_MODES:
            self.range_mode.set("DM only")
        self.band_colour = tk.StringVar(
            value=saved.get("band_colour", "#F5C542"))
        self.range_readout = tk.StringVar(value="")
        self.band_summary = tk.StringVar(value="")
        self.range_origin = None
        self.placing_ranges = False
        self.revealing = False
        self.conditions = normalise_conditions(
            saved.get("conditions", ""), saved.get("conditions_version", 0))
        self.condition_choice = tk.StringVar(value=self.conditions[0][0])
        # Markers are held in grid coordinates, not pixels. A marker sits on a
        # creature standing in a square, so when the grid is rescaled or nudged
        # into alignment the marker has to travel with its square rather than
        # staying at a pixel the square has moved away from.
        self.markers = []
        self.marker_size = tk.IntVar(value=saved.get("marker_size", 84))
        self.placing_condition = False
        self._ring_fonts = {}
        self._measure_timer = None
        self._measure_restore = True

        self.check_updates = tk.BooleanVar(
            value=bool(saved.get("check_updates", True)))
        self.last_update_check = saved.get("last_update_check", 0)
        # Remembered, so a known update is announced at the next startup without
        # waiting on the network, and keeps being announced until it is taken.
        self.latest_seen = str(saved.get("latest_seen", "") or "")
        self.update_notice = tk.StringVar(value="")
        self.update_action = tk.StringVar(value="Open page")
        self.update_url = RELEASES_PAGE
        self.update_asset = None
        self.update_state = "idle"           # idle, ready, or installing
        self._update_reply = []
        self._update_worker = None
        self._download_reply = []
        self._download_worker = None
        self.pending_update = ""

        self.status = tk.StringVar(value="Overlay live")
        self.hotkey_hint = tk.StringVar(value="")

        if self.grid_type.get() not in self.GRID_TYPES:
            self.grid_type.set("Square")

        self.overlay = Overlay(self.root)
        self._pending = False
        self._wrap_labels = []
        self._value_rows = []
        self._narrow = None
        self.hotkeys = normalise_hotkeys(saved.get("hotkeys", {}),
                                         saved.get("hotkeys_version", 0))
        self.hotkey_manager = HotkeyManager(self.root)
        self.settings_window = None

        self._install_error_guard()
        self._set_window_icon()
        self._build_fonts()
        self._build_theme()
        self._build_ui(saved.get("screen", ""))
        self._bind_keys()

        set_frame_mode(self.root)
        self._setup_sizing(saved.get("panel_geometry", ""))

        for var in (self.grid_type, self.cell, self.off_x, self.off_y,
                    self.line_w, self.colour):
            var.trace_add("write", lambda *_: self.schedule_draw())
        for var in (self.per_square, self.unit, self.diagonal_rule):
            var.trace_add("write", lambda *_: self.measure_readout.set(""))
        for var in (self.per_square, self.diagonal_rule, self.cell,
                    self.range_mode, self.band_colour):
            var.trace_add("write", lambda *_: self._paint_ranges())
        for var in (self.cell, self.off_x, self.off_y, self.marker_size,
                    self.grid_type):
            var.trace_add("write", lambda *_: self._paint_conditions())
        self.band_colour.trace_add("write", lambda *_: self._paint_swatches())
        self.unit.trace_add("write", lambda *_: self._refresh_band_summary())
        self.opacity.trace_add("write", lambda *_: self.apply_opacity())

        self.apply_screen()
        self.apply_opacity()
        self.apply_visibility()
        self.apply_click_through()
        self._style_dropdown_lists()
        self._register_hotkeys(announce=True)
        self.hotkey_manager.start_polling()
        self._hold_top()

        # A previously seen update is announced straight away. Waiting on the
        # network for something already known would mean saying nothing at all
        # on the days the throttle skips the check.
        if self.latest_seen and is_newer(self.latest_seen, VERSION):
            # The button offers the page for now. The check a moment later
            # fetches the asset details and upgrades it to a real install.
            self.announce_update(self.latest_seen)

        # Delayed, so a slow network cannot hold up the window appearing.
        self.root.after(3000, self.check_for_update)

        if self.start_minimised.get():
            self.root.iconify()

        self.root.protocol("WM_DELETE_WINDOW", self._close_button)

    # -- typography --------------------------------------------------------

    def _build_fonts(self):
        families = set(tkfont.families(self.root))

        def pick(candidates, fallback):
            for name in candidates:
                if name in families:
                    return name
            return fallback

        ui = pick(["Segoe UI Variable Text", "Segoe UI", "Inter", "Ubuntu",
                   "DejaVu Sans", "Helvetica"], "TkDefaultFont")
        mono = pick(["Cascadia Mono", "Consolas", "SF Mono", "Menlo",
                     "DejaVu Sans Mono"], "TkFixedFont")

        self.f_app = tkfont.Font(family=ui, size=11, weight="bold")
        self.f_head = tkfont.Font(family=ui, size=8, weight="bold")
        self.f_body = tkfont.Font(family=ui, size=9)
        self.f_num = tkfont.Font(family=mono, size=9)
        self.f_hint = tkfont.Font(family=ui, size=8)

    # -- theme -------------------------------------------------------------

    def _build_theme(self):
        """Apply the current palette to ttk.

        Two routes. For Classic, ttk is handed back to the operating system's
        own widget engine and only the surfaces we draw ourselves are coloured,
        so controls look exactly as Windows intends. For every other theme,
        'clam' is used because it is the one built-in whose element colours are
        fully configurable, letting real ttk widgets keep every native
        affordance while wearing our palette.
        """
        style = self.style = getattr(self, "style", None) or ttk.Style(self.root)
        available = style.theme_names()

        if NATIVE_WIDGETS:
            for candidate in ("vista", "xpnative", "winnative", "aqua",
                              "default"):
                if candidate in available:
                    style.theme_use(candidate)
                    break
        elif "clam" in available:
            style.theme_use("clam")

        self._style_surfaces(style)
        if not NATIVE_WIDGETS:
            self._style_controls(style)

    def _style_surfaces(self, style):
        """Frames, labels and separators: needed under every theme."""
        style.configure("Card.TFrame", background=PANEL)
        style.configure("Shell.TFrame", background=INK)
        style.configure("TLabel", background=PANEL, foreground=TEXT)
        style.configure("Head.TLabel", background=PANEL, foreground=MUTE,
                        font=self.f_head)
        style.configure("Hint.TLabel", background=PANEL, foreground=MUTE,
                        font=self.f_hint)
        style.configure("Shell.TLabel", background=INK, foreground=MUTE,
                        font=self.f_hint)
        style.configure("App.TLabel", background=INK, foreground=TEXT,
                        font=self.f_app)
        style.configure("Status.TLabel", background=INK, foreground=MUTE,
                        font=self.f_hint)
        style.configure("TSeparator", background=LINE)

    def _style_controls(self, style):
        """The full restyle, for every theme except Classic."""
        pad = int(6 * self.s)

        style.configure(".", background=PANEL, foreground=TEXT,
                        fieldbackground=FIELD, bordercolor=LINE,
                        lightcolor=PANEL, darkcolor=PANEL,
                        focuscolor=HILITE, font=self.f_body)

        # Buttons: flat, hairline border, lift a step on hover.
        style.configure("TButton", background=FIELD, foreground=TEXT,
                        bordercolor=LINE, relief="flat", padding=(pad, pad // 2),
                        lightcolor=FIELD, darkcolor=FIELD)
        style.map("TButton",
                  background=[("pressed", LINE), ("active", LINE)],
                  bordercolor=[("active", MUTE)],
                  foreground=[("disabled", MUTE)])

        style.configure("Nudge.TButton", padding=(0, 0), font=self.f_num)

        # Entries and spinboxes: recessed field, highlight border on focus.
        for name in ("TEntry", "TSpinbox"):
            style.configure(name, fieldbackground=FIELD, foreground=TEXT,
                            bordercolor=LINE, insertcolor=HILITE,
                            lightcolor=FIELD, darkcolor=FIELD,
                            arrowcolor=MUTE, padding=(pad // 2, pad // 2))
            style.map(name,
                      bordercolor=[("focus", HILITE)],
                      arrowcolor=[("active", TEXT)],
                      lightcolor=[("focus", FIELD)])

        style.configure("TCombobox", fieldbackground=FIELD, foreground=TEXT,
                        bordercolor=LINE, arrowcolor=MUTE,
                        lightcolor=FIELD, darkcolor=FIELD,
                        padding=(pad // 2, pad // 2))
        style.map("TCombobox",
                  fieldbackground=[("readonly", FIELD)],
                  foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", FIELD)],
                  selectforeground=[("readonly", TEXT)],
                  bordercolor=[("focus", HILITE), ("active", MUTE)],
                  arrowcolor=[("active", TEXT)])

        # Scales: thin dark trough, pale grip, brighter grip while dragging.
        style.configure("Horizontal.TScale", background=PANEL,
                        troughcolor=FIELD, bordercolor=LINE,
                        lightcolor=MUTE, darkcolor=MUTE)
        style.map("Horizontal.TScale",
                  lightcolor=[("active", HILITE)],
                  darkcolor=[("active", HILITE)])

        for name in ("TCheckbutton", "TRadiobutton"):
            style.configure(name, background=PANEL, foreground=TEXT,
                            indicatorbackground=FIELD,
                            indicatorforeground=ONHILITE,
                            bordercolor=LINE, focuscolor=PANEL,
                            lightcolor=FIELD, darkcolor=FIELD)
            style.map(name,
                      indicatorbackground=[("selected", HILITE),
                                           ("active", LINE)],
                      foreground=[("disabled", MUTE)],
                      background=[("active", PANEL)])

        # Scrollbar: no arrows, thumb is just a lighter step of the ramp.
        style.configure("Panel.Vertical.TScrollbar",
                        background=LINE, troughcolor=INK, bordercolor=INK,
                        arrowcolor=INK, relief="flat", borderwidth=0,
                        lightcolor=LINE, darkcolor=LINE, width=int(10 * self.s))
        style.map("Panel.Vertical.TScrollbar",
                  background=[("active", MUTE), ("pressed", MUTE)])
        try:
            style.layout("Panel.Vertical.TScrollbar", [
                ("Vertical.Scrollbar.trough", {"children": [
                    ("Vertical.Scrollbar.thumb",
                     {"expand": "1", "sticky": "nswe"})
                ], "sticky": "ns"})
            ])
        except tk.TclError:
            pass

    def _style_dropdown_lists(self):
        """Combobox popup lists are plain Tk listboxes, styled separately.

        option_add only reaches widgets created afterwards, so live theme
        changes have to reconfigure each existing popup by hand.
        """
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", HILITE)
        self.root.option_add("*TCombobox*Listbox.selectForeground", ONHILITE)
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)
        self.root.option_add("*TCombobox*Listbox.font", self.f_body)
        for combo in list(self._combos):
            try:
                popdown = combo.tk.eval(
                    "ttk::combobox::PopdownWindow %s" % combo
                )
                combo.tk.call("%s.f.l" % popdown, "configure",
                              "-background", FIELD, "-foreground", TEXT,
                              "-selectbackground", HILITE,
                              "-selectforeground", ONHILITE)
            except tk.TclError:
                pass

    def register_combo(self, combo):
        """Track comboboxes so their popup lists can be re-themed later."""
        self._combos.append(combo)
        return combo

    # -- layout scaffolding ------------------------------------------------

    def _px(self, n):
        return int(n * self.s)

    def _card(self, parent, heading=None, grow=False):
        """A titled section. Cards sit on the darker shell with a hairline.

        `grow` marks the one card that absorbs spare vertical space, so extra
        height goes somewhere useful instead of leaving a dead gap.
        """
        holder = ttk.Frame(parent, style="Card.TFrame")
        holder.pack(fill="both" if grow else "x", expand=grow)
        ttk.Separator(parent, orient="horizontal").pack(fill="x")
        inner = ttk.Frame(holder, style="Card.TFrame")
        inner.pack(fill="both" if grow else "x", expand=grow,
                   padx=self._px(14), pady=self._px(11))
        if heading:
            ttk.Label(inner, text=heading, style="Head.TLabel").pack(
                anchor="w", pady=(0, self._px(8))
            )
        return inner

    def _wrapping(self, label, reserve=0):
        """Register a label whose wraplength must track the window width.

        `reserve` is space taken by a sibling on the same row, such as the
        Quit button beside the shortcut list.
        """
        self._wrap_labels.append((label, reserve))
        return label

    def _rewrap(self):
        width = self.root.winfo_width()
        if width <= 1:
            return
        for label, reserve in self._wrap_labels:
            try:
                label.configure(
                    wraplength=max(self._px(110), width - self._px(34) - reserve)
                )
            except tk.TclError:
                pass

    # -- value rows --------------------------------------------------------

    def _value_row(self, parent, label, var, lo, hi, fine, unit):
        """Label, slider, numeric field, and -/+ nudge buttons.

        All four affordances matter: the slider for coarse sweeps, the field
        for typing an exact figure read off a map, and the buttons for single
        steps without hunting for a keyboard shortcut.
        """
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=self._px(3))

        parts = {
            "label": ttk.Label(row, text=label, style="TLabel", anchor="w"),
            "scale": ttk.Scale(row, from_=lo, to=hi, orient="horizontal",
                               variable=var, style="Horizontal.TScale"),
            "entry": ttk.Entry(row, textvariable=var, font=self.f_num,
                               width=6, justify="right"),
            "unit": ttk.Label(row, text=unit, style="Hint.TLabel", width=2),
            "minus": ttk.Button(row, text="\u2212", width=2,
                                style="Nudge.TButton",
                                command=lambda: self.bump(var, -fine)),
            "plus": ttk.Button(row, text="+", width=2, style="Nudge.TButton",
                               command=lambda: self.bump(var, fine)),
        }
        self._value_rows.append((row, parts))
        return row

    def _grid_value_row(self, row, parts, narrow):
        """Place one value row, in wide (single line) or narrow (two) form."""
        for widget in parts.values():
            widget.grid_forget()

        gap = self._px(4)
        if narrow:
            # label ............ [field][unit]
            # [-------slider-------][-][+]
            row.columnconfigure(0, weight=1)
            row.columnconfigure(1, weight=0)
            parts["label"].configure(width=0)
            parts["label"].grid(row=0, column=0, sticky="w")
            parts["entry"].grid(row=0, column=1, sticky="e")
            parts["unit"].grid(row=0, column=2, sticky="w", padx=(gap // 2, 0))
            parts["scale"].grid(row=1, column=0, sticky="we",
                                pady=(self._px(3), 0), padx=(0, gap))
            parts["minus"].grid(row=1, column=1, sticky="e",
                                pady=(self._px(3), 0))
            parts["plus"].grid(row=1, column=2, sticky="w",
                               pady=(self._px(3), 0), padx=(gap // 2, 0))
        else:
            # label [------slider------] [field][unit][-][+]
            row.columnconfigure(0, weight=0)
            row.columnconfigure(1, weight=1)
            parts["label"].configure(width=9)
            parts["label"].grid(row=0, column=0, sticky="w")
            parts["scale"].grid(row=0, column=1, sticky="we",
                                padx=(self._px(6), self._px(9)))
            parts["entry"].grid(row=0, column=2, sticky="e")
            parts["unit"].grid(row=0, column=3, sticky="w",
                               padx=(self._px(3), self._px(5)))
            parts["minus"].grid(row=0, column=4)
            parts["plus"].grid(row=0, column=5, padx=(self._px(2), 0))

    # -- the panel ---------------------------------------------------------

    def _build_ui(self, saved_screen):
        outer = ttk.Frame(self.root, style="Shell.TFrame")
        outer.pack(fill="both", expand=True)

        # header: stays put, never scrolls -------------------------------
        head = ttk.Frame(outer, style="Shell.TFrame")
        head.pack(fill="x", padx=self._px(14), pady=self._px(12))
        ttk.Label(head, text="Gridwyrm", style="App.TLabel").pack(side="left")
        self.lamp = tk.Canvas(head, width=self._px(8), height=self._px(8),
                              bg=INK, highlightthickness=0, bd=0)
        self.lamp.pack(side="right", padx=(self._px(6), 0))
        ttk.Label(head, textvariable=self.status, style="Status.TLabel").pack(
            side="right"
        )
        ttk.Separator(outer, orient="horizontal").pack(fill="x")

        # scrolling middle -----------------------------------------------
        shell = self._build_scroll_area(outer)

        # actual-size preview: the signature element ---------------------
        preview_card = self._card(shell, "PREVIEW  (ACTUAL SIZE)", grow=True)
        self.preview = tk.Canvas(preview_card, height=self._px(98), bg=INK,
                                 highlightthickness=1, highlightbackground=LINE,
                                 bd=0, takefocus=0)
        self.preview.pack(fill="both", expand=True)
        # A bigger window shows more grid, so repaint on every resize.
        self.preview.bind("<Configure>", lambda e: self.schedule_draw())
        self._wrapping(ttk.Label(
            preview_card,
            text="The grid at actual size over a sample map, so you can judge "
                 "the colour against grass, stone and timber rather than "
                 "against a flat swatch. Drag the window bigger to see more.",
            style="Hint.TLabel", justify="left",
        )).pack(anchor="w", fill="x", pady=(self._px(5), 0))

        backdrop = ttk.Frame(preview_card, style="Card.TFrame")
        backdrop.pack(fill="x", pady=(self._px(7), 0))
        ttk.Button(backdrop, text="Use my map\u2026",
                   command=self.choose_preview_image).pack(side="left")
        ttk.Button(backdrop, text="Sample",
                   command=self.clear_preview_image).pack(side="left",
                                                          padx=(self._px(6), 0))
        ttk.Label(backdrop, textvariable=self.backdrop_label,
                  style="Hint.TLabel").pack(side="left",
                                            padx=(self._px(8), 0))

        # screen ---------------------------------------------------------
        screen = self._card(shell, "SCREEN")
        self.screen_labels = [
            f"Monitor {i + 1}  \u2014  {w}\u00d7{h} at {x:+d}{y:+d}"
            for i, (x, y, w, h) in enumerate(self.monitors)
        ]
        self.screen_labels.append("Custom region\u2026")
        self.screen_choice.set(
            saved_screen if saved_screen in self.screen_labels
            else self.screen_labels[0]
        )
        self.screen_box = self.register_combo(ttk.Combobox(
            screen, values=self.screen_labels, textvariable=self.screen_choice,
            state="readonly",
        ))
        self.screen_box.pack(fill="x")
        self.screen_box.bind("<<ComboboxSelected>>", lambda *_: self.apply_screen())

        region_row = ttk.Frame(screen, style="Card.TFrame")
        region_row.pack(fill="x", pady=(self._px(7), 0))
        self.region_entry = ttk.Entry(region_row, textvariable=self.region,
                                      font=self.f_num)
        self.region_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(region_row, text="Apply", command=self.apply_screen).pack(
            side="left", padx=(self._px(6), 0)
        )
        ttk.Label(screen, text="width \u00d7 height + x + y",
                  style="Hint.TLabel").pack(anchor="w", pady=(self._px(4), 0))

        # grid -----------------------------------------------------------
        grid_card = self._card(shell, "GRID")
        self.register_combo(ttk.Combobox(
            grid_card, values=self.GRID_TYPES, textvariable=self.grid_type,
            state="readonly")).pack(fill="x")

        # alignment ------------------------------------------------------
        align = self._card(shell, "ALIGNMENT")
        self._value_row(align, "Cell size", self.cell, 8, 400, 0.5, "px")
        self._value_row(align, "Offset X", self.off_x, -400, 400, 0.5, "px")
        self._value_row(align, "Offset Y", self.off_y, -400, 400, 0.5, "px")

        # scale ----------------------------------------------------------
        scale_card = self._card(shell, "SCALE")

        per_row = ttk.Frame(scale_card, style="Card.TFrame")
        per_row.pack(fill="x")
        ttk.Label(per_row, text="1 square =", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        ttk.Entry(per_row, textvariable=self.per_square, font=self.f_num,
                  width=6, justify="right").pack(side="left",
                                                 padx=(self._px(6), 0))
        self.register_combo(ttk.Combobox(
            per_row, values=list(UNIT_CHOICES), textvariable=self.unit,
            state="readonly", width=8)).pack(side="left",
                                             padx=(self._px(6), 0))

        diag_row = ttk.Frame(scale_card, style="Card.TFrame")
        diag_row.pack(fill="x", pady=(self._px(6), 0))
        ttk.Label(diag_row, text="Diagonals", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        self.register_combo(ttk.Combobox(
            diag_row, values=list(DIAGONAL_RULES),
            textvariable=self.diagonal_rule, state="readonly")).pack(
            side="left", fill="x", expand=True, padx=(self._px(6), 0))

        measure_row = ttk.Frame(scale_card, style="Card.TFrame")
        measure_row.pack(fill="x", pady=(self._px(8), 0))
        self.measure_button = ttk.Button(measure_row, text="Measure\u2026",
                                        command=self.toggle_measure)
        self.measure_button.pack(side="left")
        self._wrapping(ttk.Label(
            measure_row, textvariable=self.measure_readout, style="Hint.TLabel",
            justify="left",
        ), reserve=self._px(96)).pack(side="left", fill="x", expand=True,
                                      padx=(self._px(8), 0))

        # Only shown once a span has been measured.
        self.span_row = ttk.Frame(scale_card, style="Card.TFrame")
        ttk.Label(self.span_row, text="That span was", style="TLabel").pack(
            side="left")
        ttk.Entry(self.span_row, textvariable=self.span_squares,
                  font=self.f_num, width=5, justify="right").pack(
            side="left", padx=(self._px(6), self._px(6)))
        ttk.Label(self.span_row, text="squares", style="TLabel").pack(
            side="left")
        ttk.Button(self.span_row, text="Set cell size",
                   command=self.apply_span_as_cell_size).pack(
            side="right")

        self._wrapping(ttk.Label(
            scale_card,
            text="Click two points on the map, then say how many squares they "
                 "were apart. Hold Shift while measuring to lock the line to "
                 "horizontal or vertical, which is worth doing when setting the "
                 "cell size. The screen dims while measuring, because the "
                 "overlay has to hold the mouse; right-click to cancel.",
            style="Hint.TLabel", justify="left",
        )).pack(anchor="w", fill="x", pady=(self._px(6), 0))

        # range bands ----------------------------------------------------
        range_card = self._card(shell, "RANGE BANDS")

        mode_row = ttk.Frame(range_card, style="Card.TFrame")
        mode_row.pack(fill="x")
        ttk.Label(mode_row, text="Show", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        self.register_combo(ttk.Combobox(
            mode_row, values=list(RANGE_MODES), textvariable=self.range_mode,
            state="readonly")).pack(side="left", fill="x", expand=True,
                                    padx=(self._px(6), 0))

        band_colour_row = ttk.Frame(range_card, style="Card.TFrame")
        band_colour_row.pack(fill="x", pady=(self._px(8), 0))
        ttk.Label(band_colour_row, text="Colour", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        ttk.Button(band_colour_row, text="Pick\u2026",
                   command=self.pick_band_colour).pack(side="right")
        self.add_swatch_strip(band_colour_row, self.band_colour,
                              self.pick_band_colour).pack(
            side="left", fill="x", expand=True,
            padx=(self._px(6), self._px(6)))

        band_buttons = ttk.Frame(range_card, style="Card.TFrame")
        band_buttons.pack(fill="x", pady=(self._px(8), 0))
        self.range_button = ttk.Button(band_buttons, text="Place bands\u2026",
                                      command=self.toggle_place_ranges)
        self.range_button.pack(side="left")
        ttk.Button(band_buttons, text="Clear",
                   command=self.clear_ranges).pack(side="left",
                                                   padx=(self._px(6), 0))
        # The hotkey can be refused by Windows if another program owns the
        # combination, so revealing is reachable from the panel too.
        reveal = ttk.Button(band_buttons, text="Reveal")
        reveal.pack(side="left", padx=(self._px(6), 0))
        reveal.bind("<ButtonPress-1>", lambda e: self.hold_reveal(True))
        reveal.bind("<ButtonRelease-1>", lambda e: self.hold_reveal(False))
        self._wrapping(ttk.Label(
            band_buttons, textvariable=self.range_readout, style="Hint.TLabel",
            justify="left",
        ), reserve=self._px(150)).pack(side="left", fill="x", expand=True,
                                      padx=(self._px(8), 0))

        self._wrapping(ttk.Label(
            range_card, textvariable=self.band_summary, style="TLabel",
            justify="left",
        )).pack(anchor="w", fill="x", pady=(self._px(8), 0))

        self._wrapping(ttk.Label(
            range_card,
            text="Click a creature and thin rings appear around it, unlabelled. "
                 "The distances are listed above, for you. Hold the reveal key "
                 "and the rings thicken and take names, for the table. Rings "
                 "scale with the cell size, and any that would be wider than "
                 "the screen are left out. Edit the bands under Settings.",
            style="Hint.TLabel", justify="left",
        )).pack(anchor="w", fill="x", pady=(self._px(6), 0))

        # conditions -----------------------------------------------------
        cond_card = self._card(shell, "CONDITIONS")

        pick_row = ttk.Frame(cond_card, style="Card.TFrame")
        pick_row.pack(fill="x")
        ttk.Label(pick_row, text="Mark as", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        self.condition_box = self.register_combo(ttk.Combobox(
            pick_row, values=[name for name, _c in self.conditions],
            textvariable=self.condition_choice, state="readonly"))
        self.condition_box.pack(side="left", fill="x", expand=True,
                                padx=(self._px(6), 0))

        self._value_row(cond_card, "Size", self.marker_size, 20, 250, 5, "%")

        cond_buttons = ttk.Frame(cond_card, style="Card.TFrame")
        cond_buttons.pack(fill="x", pady=(self._px(8), 0))
        self.condition_button = ttk.Button(cond_buttons, text="Mark\u2026",
                                         command=self.toggle_place_condition)
        self.condition_button.pack(side="left")
        ttk.Button(cond_buttons, text="Undo",
                   command=self.undo_condition).pack(side="left",
                                                     padx=(self._px(6), 0))
        ttk.Button(cond_buttons, text="Clear all",
                   command=self.clear_conditions).pack(side="left",
                                                       padx=(self._px(6), 0))

        self._wrapping(ttk.Label(
            cond_card,
            text="A coloured ring on a creature saying what is happening to it. "
                 "Keep clicking to mark a whole group, then right-click when "
                 "done. Size is a share of one square, so rings stay "
                 "proportionate, and they hold their place on the grid if you "
                 "rescale or nudge it. Edit the list under Settings.",
            style="Hint.TLabel", justify="left",
        )).pack(anchor="w", fill="x", pady=(self._px(6), 0))

        # lines ----------------------------------------------------------
        lines = self._card(shell, "LINES")
        swatch_row = ttk.Frame(lines, style="Card.TFrame")
        swatch_row.pack(fill="x", pady=(0, self._px(8)))
        ttk.Label(swatch_row, text="Colour", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        ttk.Button(swatch_row, text="Pick\u2026",
                   command=self.pick_colour).pack(side="right")
        self.add_swatch_strip(swatch_row, self.colour, self.pick_colour).pack(
            side="left", fill="x", expand=True,
            padx=(self._px(6), self._px(6)))
        ttk.Label(lines, text="First swatch is the colour in use \u2014 click it "
                              "to change. The rest are presets.",
                  style="Hint.TLabel").pack(anchor="w", pady=(self._px(4), 0))

        weight_row = ttk.Frame(lines, style="Card.TFrame")
        weight_row.pack(fill="x", pady=self._px(3))
        ttk.Label(weight_row, text="Weight", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        ttk.Spinbox(weight_row, from_=1, to=8, textvariable=self.line_w,
                    width=4, font=self.f_num).pack(side="left")
        ttk.Label(weight_row, text="px", style="Hint.TLabel").pack(
            side="left", padx=(self._px(4), 0)
        )
        self._value_row(lines, "Opacity", self.opacity, 10, 100, 1, "%")

        # switches -------------------------------------------------------
        switches = self._card(shell)
        ttk.Checkbutton(switches, text="Show overlay", variable=self.visible,
                        command=self.apply_visibility).pack(anchor="w")
        self.pass_check = ttk.Checkbutton(
            switches, text="Let clicks pass through to the map underneath",
            variable=self.click_through, command=self.apply_click_through,
        )
        self.pass_check.pack(anchor="w", pady=(self._px(4), 0))
        if not IS_WINDOWS:
            self.pass_check.state(["disabled"])
            self._wrapping(ttk.Label(
                switches,
                text="Click-through and full transparency need Windows. "
                     "Elsewhere the overlay shows as a faint tint.",
                style="Hint.TLabel", justify="left",
            )).pack(anchor="w", fill="x", pady=(self._px(4), 0))

        # footer: stays put, never scrolls -------------------------------
        ttk.Separator(outer, orient="horizontal").pack(fill="x")

        # Only packed when there is actually something to say, so it costs no
        # space and never nags.
        self.update_row = ttk.Frame(outer, style="Shell.TFrame")
        ttk.Button(self.update_row, textvariable=self.update_action,
                   command=self.update_button_pressed).pack(side="right")
        ttk.Button(self.update_row, text="Later",
                   command=self.dismiss_update).pack(side="right",
                                                     padx=(0, self._px(6)))
        self._wrapping(ttk.Label(
            self.update_row, textvariable=self.update_notice,
            style="Shell.TLabel", justify="left",
        ), reserve=self._px(120)).pack(side="left", fill="x", expand=True,
                                       pady=(self._px(8), 0))

        foot = ttk.Frame(outer, style="Shell.TFrame")
        foot.pack(fill="x", padx=self._px(14), pady=self._px(10))
        ttk.Button(foot, text="Quit", command=self.quit).pack(side="right")
        ttk.Button(foot, text="Settings\u2026",
                   command=self.open_settings).pack(side="right",
                                                    padx=(0, self._px(6)))
        hints = ttk.Frame(foot, style="Shell.TFrame")
        hints.pack(side="left", fill="x", expand=True)
        self._wrapping(ttk.Label(
            hints,
            text="Arrows nudge  \u00b7  Shift+arrows \u00d710  \u00b7  "
                 "+ / \u2212 cell size  \u00b7  [ ] fine",
            style="Shell.TLabel", justify="left",
        ), reserve=self._px(160)).pack(anchor="w", fill="x")
        self._wrapping(ttk.Label(
            hints, textvariable=self.hotkey_hint, style="Shell.TLabel",
            justify="left",
        ), reserve=self._px(160)).pack(anchor="w", fill="x",
                                       pady=(self._px(3), 0))

        self._paint_lamp()
        self._update_backdrop_label()
        self._refresh_band_summary()

    # -- scrolling ---------------------------------------------------------

    def _build_scroll_area(self, parent):
        """A scrolling viewport that only shows its bar when needed."""
        wrap = ttk.Frame(parent, style="Shell.TFrame")
        wrap.pack(fill="both", expand=True)

        self.viewport = tk.Canvas(wrap, bg=INK, highlightthickness=0, bd=0,
                                  takefocus=0)
        self.viewport.pack(side="left", fill="both", expand=True)
        self.scrollbar = ttk.Scrollbar(
            wrap, orient="vertical", command=self.viewport.yview,
            style="Panel.Vertical.TScrollbar",
        )
        self.viewport.configure(yscrollcommand=self._on_scroll_set)

        body = ttk.Frame(self.viewport, style="Shell.TFrame")
        self.body_id = self.viewport.create_window((0, 0), window=body,
                                                   anchor="nw")
        self.body = body
        body.bind("<Configure>", lambda e: self._sync_scroll())
        self.viewport.bind("<Configure>", lambda e: self._sync_scroll())
        return body

    def _on_scroll_set(self, first, last):
        """Show the scrollbar only when the content actually overflows."""
        self.scrollbar.set(first, last)
        needed = float(first) > 0.0 or float(last) < 1.0
        mapped = bool(self.scrollbar.winfo_ismapped())
        if needed and not mapped:
            self.scrollbar.pack(side="right", fill="y")
        elif not needed and mapped:
            self.scrollbar.pack_forget()

    def _sync_scroll(self):
        """Keep the body as wide as the viewport, and as tall as it needs."""
        view_w = self.viewport.winfo_width()
        view_h = self.viewport.winfo_height()
        if view_w <= 1:
            return
        natural = self.body.winfo_reqheight()
        # Taller viewport than content: stretch, so the preview card grows.
        # Shorter: keep natural height and let the scrollbar handle it.
        height = max(natural, view_h)
        self.viewport.itemconfigure(self.body_id, width=view_w, height=height)
        self.viewport.configure(scrollregion=(0, 0, view_w, height))

    def _wheel_scroll(self, steps):
        if self.scrollbar.winfo_ismapped():
            self.viewport.yview_scroll(steps, "units")

    # -- sizing ------------------------------------------------------------

    def _setup_sizing(self, saved_geometry):
        """Any size at all: a small floor, reflow narrow, scroll when short."""
        self.root.update_idletasks()

        # Natural size = what the layout wants before anything is squeezed.
        natural_w = max(self._px(self.NARROW_AT + 40),
                        self.body.winfo_reqwidth() + self._px(4))
        self.viewport.configure(height=self.body.winfo_reqheight())
        self.root.update_idletasks()
        natural_h = self.root.winfo_reqheight()

        # Then let the viewport shrink freely, or it would set the floor.
        self.viewport.configure(height=self._px(50), width=self._px(50))

        self.root.minsize(self._px(240), self._px(170))

        screen_h = self.root.winfo_screenheight()
        natural_h = min(natural_h, max(self._px(300), screen_h - self._px(90)))

        applied = False
        match = PANEL_GEOMETRY_RE.match(saved_geometry or "")
        if match:
            w, h, x, y = (int(g) for g in match.groups())
            # Only restore a position that still lands on a real screen, so a
            # changed monitor layout cannot strand the panel out of sight.
            on_screen = any(
                mx <= x < mx + mw and my <= y < my + mh
                for mx, my, mw, mh in self.monitors
            )
            self.root.geometry(f"{w}x{h}{x:+d}{y:+d}" if on_screen else f"{w}x{h}")
            applied = True
        if not applied:
            self.root.geometry(f"{natural_w}x{natural_h}")

        self.root.bind("<Configure>", self._on_resize)
        self.root.bind_all("<MouseWheel>",
                           lambda e: self._wheel_scroll(-1 if e.delta > 0 else 1))
        self.root.bind_all("<Button-4>", lambda e: self._wheel_scroll(-1))
        self.root.bind_all("<Button-5>", lambda e: self._wheel_scroll(1))

        self._apply_layout_mode(force=True)
        self._rewrap()

    def _apply_layout_mode(self, force=False):
        """Switch value rows between the wide and narrow arrangements."""
        narrow = self.root.winfo_width() < self._px(self.NARROW_AT)
        if narrow == self._narrow and not force:
            return
        self._narrow = narrow
        for row, parts in self._value_rows:
            self._grid_value_row(row, parts, narrow)

    def _on_resize(self, event):
        if event.widget is not self.root:
            return
        self._apply_layout_mode()
        self._rewrap()

    # -- measuring ---------------------------------------------------------

    def toggle_measure(self):
        if self.measure is not None:
            self.cancel_measure("Measuring cancelled")
        else:
            self.start_measure()

    def start_measure(self):
        """Begin a span. The overlay must be visible to be measured on."""
        if not self.visible.get():
            self.visible.set(True)
            self.apply_visibility()

        self.measure = {"first": None, "last": None, "snapped": False}
        self._measure_restore = bool(self.click_through.get())
        # Both are needed: the extended style stops the window being skipped,
        # and dropping the colour key gives it pixels that can actually be hit.
        self.overlay.set_click_through(False)
        self.overlay.set_measure_surface(True)
        self.overlay.begin_measure(self._measure_click, self._measure_move,
                                   lambda: self.cancel_measure(
                                       "Measuring cancelled"))
        self.overlay.show_measure_hint(
            "Click two points to measure     hold Shift to keep it straight"
            "     right-click to cancel", self.f_num)
        self.schedule_draw()                     # redraw the grid on the wash
        self.measure_button.configure(text="Cancel")
        self.span_row.pack_forget()
        self.measure_readout.set("Click the first point on the map")
        self.status.set("Measuring")
        self._arm_measure_timeout()
        log_event("measure: started")

    def _arm_measure_timeout(self):
        """Nothing may leave the screen permanently unclickable.

        If measuring is somehow abandoned, this ends it on its own rather than
        leaving an invisible sheet swallowing every click.
        """
        if self._measure_timer is not None:
            try:
                self.root.after_cancel(self._measure_timer)
            except Exception:
                pass
        self._measure_timer = self.root.after(
            30000, lambda: self.cancel_measure("Measuring timed out"))

    def _measure_move(self, x, y, state=0):
        if self.measure is None or self.measure["first"] is None:
            return
        self._arm_measure_timeout()
        x1, y1 = self.measure["first"]
        if state & SHIFT_HELD:
            x2, y2, snapped = snap_to_axis(x1, y1, x, y)
        else:
            x2, y2, snapped = x, y, False
        self.measure["last"] = (x2, y2)
        self.measure["snapped"] = snapped
        self.overlay.draw_measure(x1, y1, x2, y2, self._span_label(x1, y1, x2, y2),
                                  self.f_num)

    def _measure_click(self, x, y):
        if self.measure is None:
            return
        self._arm_measure_timeout()
        if self.measure["first"] is None:
            self.measure["first"] = (x, y)
            self.measure_readout.set("Now click the far point")
            self.overlay.draw_measure(x, y, x, y, "", self.f_num)
            return
        self._finish_measure()

    def _span_label(self, x1, y1, x2, y2):
        text = format_measurement(
            x2 - x1, y2 - y1, max(1.0, safe_float(self.cell, 64.0)),
            self.diagonal_rule.get(), safe_float(self.per_square, 5.0),
            self.unit.get())
        return text + ("   straight" if self.measure["snapped"] else "")

    def _finish_measure(self):
        first, last = self.measure["first"], self.measure["last"]
        if first is None or last is None:
            self.cancel_measure("Measuring cancelled")
            return
        dx, dy = last[0] - first[0], last[1] - first[1]
        self._release_measure()
        self.last_span = (dx, dy)
        self.measure_readout.set(format_measurement(
            dx, dy, max(1.0, safe_float(self.cell, 64.0)),
            self.diagonal_rule.get(), safe_float(self.per_square, 5.0),
            self.unit.get()))
        self.span_row.pack(fill="x", pady=(self._px(6), 0))
        self.status.set("Overlay live" if self.visible.get() else "Overlay hidden")
        log_event("measure: %d x %d px" % (round(dx), round(dy)))

    def cancel_measure(self, message=""):
        self._release_measure()
        self.overlay.canvas.delete("measure")
        self.measure_readout.set(message)
        self.span_row.pack_forget()
        self.status.set("Overlay live" if self.visible.get() else "Overlay hidden")

    def _release_measure(self):
        """Give the mouse back. Called on every exit path, without exception."""
        self.measure = None
        if self._measure_timer is not None:
            try:
                self.root.after_cancel(self._measure_timer)
            except Exception:
                pass
            self._measure_timer = None
        try:
            self.overlay.end_measure()
        finally:
            # Order matters: put the surface back before handing the mouse
            # over, so there is no moment where the overlay is both opaque and
            # ignoring clicks.
            self.overlay.set_measure_surface(False)
            self.apply_opacity()
            self.overlay.set_click_through(self._measure_restore)
            self.schedule_draw()
        self.placing_ranges = False
        self.placing_condition = False
        try:
            self.measure_button.configure(text="Measure\u2026")
            self.range_button.configure(text="Place bands\u2026")
            self.condition_button.configure(text="Mark\u2026")
        except (tk.TclError, AttributeError):
            pass

    def apply_span_as_cell_size(self):
        """Turn the measured span into a cell size."""
        span = getattr(self, "last_span", None)
        if span is None:
            return
        size = cell_size_from_span(span[0], span[1], self.span_squares.get())
        if size is None:
            self.measure_readout.set(
                "Give the number of squares that span covered, as a plain "
                "number")
            return
        self.cell.set(size)
        self.measure_readout.set("Cell size set to %s px" % tidy_number(size, 2))
        self.span_row.pack_forget()
        self.overlay.canvas.delete("measure")
        log_event("measure: cell size set to %s" % size)

    # -- range bands -------------------------------------------------------

    def toggle_place_ranges(self):
        if self.placing_ranges:
            self.cancel_measure("")
        else:
            self.start_place_ranges()

    def start_place_ranges(self):
        """One click, then the mouse goes straight back.

        This is the whole reason bands work here and dragging tokens would not.
        A token needs the pointer for as long as you move it, which would mean
        surrendering click-through for the session. A band needs it once.
        """
        if not self.visible.get():
            self.visible.set(True)
            self.apply_visibility()
        self.placing_ranges = True
        self._measure_restore = bool(self.click_through.get())
        self.overlay.set_click_through(False)
        self.overlay.set_measure_surface(True)
        self.overlay.begin_measure(self._range_click, self._range_move,
                                   lambda: self.cancel_measure(""))
        self.overlay.show_measure_hint(
            "Click the creature to centre the bands on"
            "     right-click to cancel", self.f_num)
        self.range_button.configure(text="Cancel")
        self.range_readout.set("Click a point on the map")
        self.schedule_draw()
        self._arm_measure_timeout()
        log_event("ranges: placing")

    def _range_move(self, x, y, state=0):
        """Preview the bands under the cursor before committing to a spot."""
        self._arm_measure_timeout()
        self._paint_ranges((x, y), force=True)

    def _range_click(self, x, y):
        self.range_origin = (x, y)
        self._release_measure()
        self._paint_ranges()
        reveal = hotkey_text(self.hotkeys.get("reveal_ranges"))
        self.range_readout.set(
            "Bands placed. Hold %s to show them." % reveal
            if reveal != "not set" else "Bands placed.")
        log_event("ranges: placed at %d,%d" % (x, y))

    def clear_ranges(self):
        self.range_origin = None
        self.overlay.clear_ranges()
        self.range_readout.set("")

    def _paint_ranges(self, origin=None, force=False):
        """Draw the bands, or clear them if there is nothing to show."""
        origin = origin or self.range_origin
        mode = self.range_mode.get()
        if origin is None or (mode == "Off" and not force):
            self.overlay.clear_ranges()
            return
        rings = band_radii(self.bands,
                           max(1.0, safe_float(self.cell, 64.0)),
                           max(0.01, safe_float(self.per_square, 5.0)))
        rings, too_big = visible_rings(rings, self.overlay.width,
                                       self.overlay.height)
        revealed = self.revealing or mode == "Show players"
        self.overlay.draw_ranges(origin, rings, revealed, self.f_num,
                                 self.band_colour.get())
        if too_big:
            self.range_readout.set(
                "Too wide for this screen: %s. Lower the cell size or the "
                "distance." % ", ".join(too_big))

    def set_bands(self, rows):
        """Take name and distance pairs from the editor.

        Returns an error message, or empty when the bands were accepted.
        """
        bands, error = validate_bands(rows)
        if not bands:
            return error
        self.bands = [list(pair) for pair in bands]
        self._refresh_band_summary()
        self._paint_ranges()
        return ""

    # -- conditions --------------------------------------------------------

    def _grid_from_pixels(self, x, y):
        cell = max(1.0, safe_float(self.cell, 64.0))
        return ((x - safe_float(self.off_x)) / cell,
                (y - safe_float(self.off_y)) / cell)

    def _pixels_from_grid(self, gx, gy):
        cell = max(1.0, safe_float(self.cell, 64.0))
        return (gx * cell + safe_float(self.off_x),
                gy * cell + safe_float(self.off_y))

    def marker_radius(self):
        """Half the marker's width, as a share of a cell.

        Sized against the grid so a marker stays proportionate to a creature,
        but with its own control, because how big a ring should be is a matter
        of taste rather than arithmetic.
        """
        footprint = cell_footprint(self.grid_type.get(),
                                   max(1.0, safe_float(self.cell, 64.0)))
        percent = min(300.0, max(10.0, safe_float(self.marker_size, 84)))
        return footprint * percent / 200.0

    def condition_colour(self, name):
        for label, colour in self.conditions:
            if label == name:
                return colour
        return "#FFFFFF"

    def toggle_place_condition(self):
        if self.placing_condition:
            self.cancel_measure("")
        else:
            self.start_place_condition()

    def start_place_condition(self):
        if not self.visible.get():
            self.visible.set(True)
            self.apply_visibility()
        name = self.condition_choice.get()
        self.placing_condition = True
        self._measure_restore = bool(self.click_through.get())
        self.overlay.set_click_through(False)
        self.overlay.set_measure_surface(True)
        self.overlay.begin_measure(self._condition_click, self._condition_move,
                                   lambda: self.cancel_measure(""))
        self.overlay.show_measure_hint(
            "Click each creature that is %s     right-click when done" % name,
            self.f_num)
        self.condition_button.configure(text="Done")
        self.schedule_draw()
        self._arm_measure_timeout()
        log_event("conditions: placing %s" % name)

    def _condition_move(self, x, y, state=0):
        self._arm_measure_timeout()

    def _condition_click(self, x, y):
        """Stays in placing mode, so a whole group can be marked in one go."""
        name = self.condition_choice.get()
        gx, gy = self._grid_from_pixels(x, y)
        self.markers.append((gx, gy, name, self.condition_colour(name)))
        self._arm_measure_timeout()
        self._paint_conditions()
        self.range_readout.set("%d marked" % len(self.markers))

    def clear_conditions(self):
        self.markers = []
        self.overlay.clear_conditions()

    def undo_condition(self):
        if self.markers:
            self.markers.pop()
            self._paint_conditions()

    def _ring_font(self, size):
        """Bold text sized in pixels, so it can be fitted to the band exactly."""
        font = self._ring_fonts.get(size)
        if font is None:
            font = tkfont.Font(family=self.f_hint.actual("family"),
                               size=-size, weight="bold")
            self._ring_fonts[size] = font
        return font

    def _paint_conditions(self):
        if not self.markers:
            self.overlay.clear_conditions()
            return
        placed = [self._pixels_from_grid(gx, gy) + (name, colour)
                  for gx, gy, name, colour in self.markers]
        self.overlay.draw_conditions(placed, self.marker_radius(),
                                     self.f_num, self._ring_font)

    def set_conditions(self, rows):
        """Returns an error message, or empty when they were accepted."""
        conditions, error = validate_conditions(rows)
        if not conditions:
            return error
        self.conditions = [list(pair) for pair in conditions]
        names = [name for name, _colour in self.conditions]
        self.condition_box.configure(values=names)
        if self.condition_choice.get() not in names:
            self.condition_choice.set(names[0])
        # Markers already on the map follow any colour or name change.
        self.markers = [(gx, gy, name, self.condition_colour(name))
                        for gx, gy, name, _old in self.markers
                        if name in names]
        self._paint_conditions()
        return ""

    # -- hold to reveal ----------------------------------------------------

    def reveal_ranges(self):
        """Show the bands boldly for as long as the key is held.

        Windows reports a hotkey being pressed but never released, so the key is
        polled until it lifts. Holding rather than toggling means there is no
        state to lose track of mid-combat.

        A tap is held for MIN_REVEAL_MS regardless. Without that floor, pressing
        and letting go quickly showed the names for a single frame, which looks
        exactly like the feature not working.
        """
        if self.range_origin is None:
            self.range_readout.set("Place the bands first")
            return
        if self.revealing:
            self._reveal_since = time.monotonic()   # a re-press extends it
            return
        self.revealing = True
        self._reveal_since = time.monotonic()
        self._paint_ranges()
        self._watch_reveal_key()

    def _reveal_vk(self):
        pair = self.hotkeys.get("reveal_ranges") or [HOTKEY_OFF, ""]
        if pair[0] == HOTKEY_OFF:
            return None
        return VK_MAP.get(pair[1])

    def _watch_reveal_key(self):
        if not self.revealing:
            return
        vk = self._reveal_vk()
        if vk is None or not IS_WINDOWS:
            # Without the key to watch, fall back to a brief reveal.
            self.root.after(900, self._end_reveal)
            return
        try:
            down = ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000
        except Exception:
            down = 0
        if down:
            self.root.after(40, self._watch_reveal_key)
        else:
            self._end_reveal()

    def _end_reveal(self):
        if not self.revealing:
            return
        held = (time.monotonic() - getattr(self, "_reveal_since", 0)) * 1000
        if held < MIN_REVEAL_MS:
            # Too brief to see. Hold it, then check again.
            self.root.after(int(MIN_REVEAL_MS - held), self._end_reveal)
            return
        self.revealing = False
        self._paint_ranges()

    def hold_reveal(self, pressed):
        """The panel button, for revealing without the hotkey."""
        if pressed:
            self.reveal_ranges()
        else:
            self._end_reveal()

    # -- update check ------------------------------------------------------

    def check_for_update(self, manual=False):
        """Ask GitHub whether there is a newer release.

        The request runs on a separate thread, because a slow or unreachable
        network would otherwise freeze the whole interface for the length of the
        timeout. That thread touches nothing but a plain list: handing a reply
        back through Tk from another thread is the same mistake that made the
        hotkeys crash, and it is not worth repeating.
        """
        if self._update_worker is not None and self._update_worker.is_alive():
            return
        if not manual:
            if not self.check_updates.get():
                return
            if not update_check_due(self.last_update_check):
                return

        self._update_reply = []
        if manual:
            self.update_notice.set("Checking\u2026")

        def work():
            try:
                self._update_reply.append(read_latest_release())
            except Exception as error:                # noqa: BLE001
                self._update_reply.append(error)

        self._update_worker = threading.Thread(target=work, daemon=True)
        self._update_worker.start()
        self.last_update_check = time.time()
        self._await_update(manual, 0)

    def _await_update(self, manual, waited):
        if not self._update_reply:
            if waited > 15000:
                if manual:
                    self.update_notice.set("GitHub did not answer in time.")
                return
            self.root.after(250,
                            lambda: self._await_update(manual, waited + 250))
            return

        reply = self._update_reply[0]
        if isinstance(reply, Exception):
            # No network, a rate limit, or a changed reply. Say nothing unless
            # the check was asked for by hand.
            log_event("update check failed: %s" % reply)
            if manual:
                self.update_notice.set("Could not reach GitHub just now.")
            return

        tag = reply.get("tag", "")
        if is_newer(tag, VERSION):
            self.latest_seen = tag
            self.update_url = reply.get("page") or RELEASES_PAGE
            self.update_asset = reply.get("asset")
            self.announce_update(tag)
            log_event("update available: %s" % tag)
        else:
            self.latest_seen = ""
            self.update_notice.set("Up to date. You have %s." % VERSION)
            log_event("up to date at %s" % VERSION)

    def announce_update(self, tag):
        """Show the notice, and label the button for what it can actually do."""
        self.update_state = "idle"
        if self.can_install():
            self.update_notice.set(
                "%s is out. You have %s." % (tag, VERSION))
            self.update_action.set("Update now")
        else:
            self.update_notice.set(
                "%s is out. You have %s." % (tag, VERSION))
            self.update_action.set("Open page")
        self.update_row.pack(fill="x", padx=self._px(14),
                             pady=(0, self._px(8)))

    def can_install(self):
        """Whether Gridwyrm is able to replace itself in place.

        Only a packaged build can: replacing a .pyw would mean guessing what
        someone did with their copy of the source. The folder also has to be
        writable, which rules out a copy sitting in Program Files.
        """
        if not IS_WINDOWS or not getattr(sys, "frozen", False):
            return False
        if not self.update_asset:
            return False
        folder = os.path.dirname(os.path.abspath(sys.executable))
        probe = os.path.join(folder, ".gridwyrm-write-test")
        try:
            with open(probe, "wb") as handle:
                handle.write(b"x")
            os.remove(probe)
            return True
        except Exception:
            return False

    def update_button_pressed(self):
        """One button, three jobs, depending on where the update has got to."""
        if self.update_state == "installing":
            return
        if self.update_state == "ready":
            self.install_update()
            return
        if self.can_install():
            self.start_download()
        else:
            self.open_release_page()

    def start_download(self):
        """Fetch the new program to a file beside the current one."""
        asset = self.update_asset
        if not asset or not download_is_trusted(asset.get("url", "")):
            self.open_release_page()
            return
        folder = os.path.dirname(os.path.abspath(sys.executable))
        incoming = os.path.join(folder, "Gridwyrm.update.exe")

        self.update_state = "installing"
        self.update_action.set("Downloading\u2026")
        self.update_notice.set("Fetching %s\u2026" % asset.get("name", "update"))
        self._download_reply = []

        def work():
            # Off the Tk thread, so it appends to a list and nothing more.
            try:
                download_release_asset(asset["url"], incoming,
                                       asset.get("size", 0))
                self._download_reply.append(incoming)
            except Exception as error:                # noqa: BLE001
                self._download_reply.append(error)

        self._download_worker = threading.Thread(target=work, daemon=True)
        self._download_worker.start()
        self._await_download(0)

    def _await_download(self, waited):
        if not self._download_reply:
            if waited > 300000:                       # five minutes is plenty
                self.update_state = "idle"
                self.update_action.set("Open page")
                self.update_notice.set("The download stalled. Try the page.")
                return
            self.root.after(300, lambda: self._await_download(waited + 300))
            return

        reply = self._download_reply[0]
        if isinstance(reply, Exception):
            log_event("update download failed: %s" % reply)
            self.update_state = "idle"
            self.update_action.set("Open page")
            self.update_notice.set("Download failed. Try the page instead.")
            return

        self.pending_update = reply
        self.update_state = "ready"
        self.update_action.set("Restart now")
        self.update_notice.set(
            "Downloaded. Gridwyrm will close and reopen updated.")
        log_event("update downloaded to %s" % reply)

    def install_update(self):
        """Hand the swap to a script that outlives this process, then quit."""
        incoming = getattr(self, "pending_update", "")
        if not incoming or not os.path.exists(incoming):
            self.update_state = "idle"
            self.update_action.set("Open page")
            return

        current = os.path.abspath(sys.executable)
        folder = os.path.dirname(current)
        backup = os.path.join(folder, "Gridwyrm.previous.exe")
        script = os.path.join(folder, "gridwyrm-update.bat")

        try:
            # cmd.exe reads a batch file in the system code page, so that is
            # what it gets. A folder with an accent in its name would fail to
            # encode as plain ASCII.
            with open(script, "w", encoding="mbcs", errors="strict") as handle:
                handle.write(swap_script(current, incoming, backup,
                                         os.getpid()))
            creation = 0x00000008 | 0x08000000        # detached, no window
            subprocess.Popen(["cmd", "/c", script], close_fds=True,
                             creationflags=creation, cwd=folder)
        except Exception as error:                    # noqa: BLE001
            log_event("update install failed: %s" % error)
            self.update_state = "idle"
            self.update_action.set("Open page")
            self.update_notice.set(
                "Could not start the update. Try the page instead.")
            return

        log_event("update handed to %s, exiting" % script)
        self.quit()

    def open_release_page(self):
        try:
            webbrowser.open(self.update_url or RELEASES_PAGE)
        except Exception:
            self.update_notice.set(RELEASES_PAGE)   # at least show the address

    def dismiss_update(self):
        self.update_row.pack_forget()

    # -- window icon -------------------------------------------------------

    def _set_window_icon(self):
        """Put the Gridwyrm mark on every surface Windows draws it on.

        There are three, and they are fed separately, which is why getting one
        right does not get the others:

          the .exe file      PyInstaller's --icon, at build time
          the title bar      iconphoto, from images held in memory
          the taskbar button iconbitmap, which insists on a real file path

        So the embedded PNGs are reassembled into an .ico in the temporary
        folder and pointed at. Together with an explicit application identity,
        set before any window exists, that covers all three.
        """
        try:
            images = [tk.PhotoImage(data=blob) for blob in
                      (ICON_PNG_64, ICON_PNG_32, ICON_PNG_16)]
            # Tk discards images it holds no reference to, so keep them.
            self._icon_images = images
            # True makes it the default for the settings and picker windows too.
            self.root.iconphoto(True, *images)
        except Exception:
            pass                                 # a missing icon is not fatal

        if not IS_WINDOWS:
            return
        try:
            data = base64.b64decode(ICON_ICO)
            path = os.path.join(tempfile.gettempdir(), "gridwyrm-taskbar.ico")
            if not os.path.exists(path) or os.path.getsize(path) != len(data):
                with open(path, "wb") as handle:
                    handle.write(data)
            # Both calls: default sets it for windows opened later, the plain
            # one applies it to this window, which already exists.
            self.root.iconbitmap(default=path)
            self.root.iconbitmap(path)
        except Exception:
            pass

    # -- error containment -------------------------------------------------

    def _install_error_guard(self):
        """Stop any single callback from taking the whole app down.

        A .pyw process has no stderr. Tkinter's default error reporter writes
        to it, so the reporter itself raises and the interpreter aborts - the
        window simply vanishes, with nothing on screen to explain why. This
        replaces the reporter: the message goes to the header and to a log file
        next to the settings, and the app keeps running.
        """
        def report(exc_type, value, tb):
            summary = "%s: %s" % (getattr(exc_type, "__name__", exc_type), value)
            log_event("EXCEPTION %s" % summary[:120])
            try:
                self.status.set("Error: %s" % summary[:70])
            except Exception:
                pass
            try:
                path = os.path.join(os.path.dirname(settings_path()),
                                    "errors.log")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write("\n%s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                    traceback.print_exception(exc_type, value, tb, file=handle)
            except Exception:
                pass

        self.root.report_callback_exception = report

    def _guard(self, function):
        """Wrap a hotkey handler so a failure reports instead of vanishing."""
        name = getattr(function, "__name__", "handler")

        def guarded():
            log_event("hotkey picked up: %s" % name)
            try:
                function()
            except Exception:
                log_event("hotkey raised: %s" % name)
                self.root.report_callback_exception(*sys.exc_info())
            else:
                log_event("hotkey done: %s" % name)
        return guarded

    # -- hotkeys -----------------------------------------------------------

    def _hotkey_handlers(self):
        raw = {
            "toggle": self.toggle_visible,
            "nudge_left": lambda: self.bump(self.off_x, -1, force=True),
            "nudge_right": lambda: self.bump(self.off_x, 1, force=True),
            "nudge_up": lambda: self.bump(self.off_y, -1, force=True),
            "nudge_down": lambda: self.bump(self.off_y, 1, force=True),
            "cell_down": lambda: self.bump(self.cell, -1, force=True),
            "cell_up": lambda: self.bump(self.cell, 1, force=True),
            "cycle_shape": self.cycle_shape,
            "focus_panel": self.focus_panel,
            "reveal_ranges": self.reveal_ranges,
        }
        return {name: self._guard(function) for name, function in raw.items()}

    def _register_hotkeys(self, announce=False):
        failures = self.hotkey_manager.apply(self.hotkeys, self._hotkey_handlers())
        log_event("hotkeys: %d requested, %d refused%s"
                  % (sum(1 for p in self.hotkeys.values()
                         if p[0] != HOTKEY_OFF),
                     len(failures),
                     (" (" + ", ".join(sorted(failures)) + ")")
                     if failures else ""))
        if announce and failures and IS_WINDOWS:
            self.status.set("%d hotkey%s unavailable" % (
                len(failures), "" if len(failures) == 1 else "s"))
        self._refresh_hotkey_hint()
        return failures

    def apply_hotkeys(self, bindings):
        """Called by the settings window. Returns {action: reason} failures."""
        self.hotkeys = dict(bindings)
        return self._register_hotkeys()

    def _refresh_hotkey_hint(self):
        toggle = hotkey_text(self.hotkeys.get("toggle"))
        if IS_WINDOWS and toggle != "not set":
            self.hotkey_hint.set("%s shows or hides the grid from anywhere"
                                 % toggle)
        else:
            self.hotkey_hint.set("Global hotkeys need Windows")

    def open_settings(self):
        if self.settings_window is not None:
            try:
                self.settings_window.win.lift()
                self.settings_window.win.focus_set()
                return
            except tk.TclError:
                self.settings_window = None
        self.settings_window = SettingsWindow(self)

    def cycle_shape(self):
        try:
            index = self.GRID_TYPES.index(self.grid_type.get())
        except ValueError:
            index = -1
        self.grid_type.set(self.GRID_TYPES[(index + 1) % len(self.GRID_TYPES)])

    def focus_panel(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    # -- themes ------------------------------------------------------------

    def apply_theme(self, name, custom=None):
        """Switch themes without a restart.

        ttk styles update themselves once reconfigured, but the canvases we
        draw by hand hold their own colours, so those are refreshed here.
        """
        if name not in THEME_ORDER:
            name = "Dark"
        self.theme_name = name
        if custom is not None:
            self.custom_theme = dict(custom)
        apply_palette(resolve_theme(name, self.custom_theme))

        self._build_theme()
        self._style_dropdown_lists()

        self.root.configure(bg=INK)
        self.lamp.configure(bg=INK)
        self.viewport.configure(bg=INK)
        self.preview.configure(bg=INK, highlightbackground=LINE)
        self._map_size = None                    # chip colours follow the theme
        for strip in self._swatch_strips:
            strip["canvas"].configure(bg=PANEL)
        set_frame_mode(self.root)
        if self.settings_window is not None:
            self.settings_window.restyle()

        self._paint_lamp()
        self.schedule_draw()

    # -- painted bits ------------------------------------------------------

    def _paint_lamp(self):
        self.lamp.delete("all")
        size = self._px(8)
        on = bool(self.visible.get())
        self.lamp.create_oval(0, 0, size - 1, size - 1,
                              fill=HILITE if on else FIELD,
                              outline="" if on else LINE)

    def _swatch_metrics(self):
        """Geometry of the swatch strip: current colour, divider, then presets."""
        box = self._px(18)
        big = self._px(26)
        gap = self._px(5)
        divider = big + self._px(7)
        start = big + self._px(15)
        return box, big, gap, divider, start

    def add_swatch_strip(self, parent, variable, picker):
        """A colour-in-use swatch, a divider, then the presets.

        Registered rather than hard-wired, so the grid colour and the band
        colour share one implementation and both follow a theme change.
        """
        canvas = tk.Canvas(parent, height=self._px(20), bg=PANEL,
                           highlightthickness=0, bd=0, takefocus=0,
                           cursor="hand2")
        strip = {"canvas": canvas, "var": variable, "picker": picker}
        self._swatch_strips.append(strip)
        canvas.bind("<Button-1>", lambda e, s=strip: self._swatch_click(e, s))
        canvas.bind("<Configure>", lambda e: self._paint_swatches())
        return canvas

    def _paint_swatches(self):
        for strip in self._swatch_strips:
            self._paint_swatch_strip(strip)

    def _paint_swatch_strip(self, strip):
        c = strip["canvas"]
        c.delete("all")
        width = c.winfo_width()
        current = str(strip["var"].get())
        box, big, gap, divider, start = self._swatch_metrics()

        # The colour in use, kept apart from the presets. A colour chosen from
        # the picker matches no preset, so without its own swatch there was
        # nowhere on this screen showing what the grid is actually drawn in.
        c.create_rectangle(
            0, 0, big, box,
            fill=current if HEX_RE.match(current) else "#808080",
            outline=HILITE, width=2,
        )
        c.create_line(divider, 0, divider, box, fill=LINE)

        for index, colour in enumerate(GRID_PRESETS):
            x = start + index * (box + gap)
            if width > 1 and x + box > width:
                break                            # no half-drawn swatches
            active = colour.upper() == current.upper()
            c.create_rectangle(
                x, 0, x + box, box, fill=colour,
                outline=HILITE if active else LINE,
                width=2 if active else 1,
            )

    def _swatch_click(self, event, strip):
        box, big, gap, _divider, start = self._swatch_metrics()
        if event.x <= big and event.y <= box:
            strip["picker"]()                    # the current swatch opens the picker
            return
        index = int((event.x - start) / float(box + gap))
        if 0 <= index < len(GRID_PRESETS) and event.y <= box:
            left = start + index * (box + gap)
            if left <= event.x <= left + box:    # ignore clicks in the gaps
                strip["var"].set(GRID_PRESETS[index])

    # -- preview backdrop --------------------------------------------------

    def choose_preview_image(self):
        """Point the preview at a real map - ideally tonight's map."""
        formats = [("Images", "*.png *.gif *.jpg *.jpeg" if HAVE_PIL
                    else "*.png *.gif"), ("All files", "*.*")]
        path = filedialog.askopenfilename(
            parent=self.root, title="Choose a map image for the preview",
            filetypes=formats,
        )
        if not path:
            return
        self.preview_image_path = path
        self._photo_key = None
        self._map_size = None                    # force the backdrop to rebuild
        self._update_backdrop_label()
        self.schedule_draw()

    def clear_preview_image(self):
        self.preview_image_path = ""
        self.preview_photo = None
        self._photo_key = None
        self._map_size = None
        self._update_backdrop_label()
        self.schedule_draw()

    def _update_backdrop_label(self):
        if self.preview_image_path:
            name = os.path.basename(self.preview_image_path)
            self.backdrop_label.set(name if len(name) <= 34
                                    else name[:31] + "\u2026")
        else:
            self.backdrop_label.set("Built-in sample map")

    def _scaled_photo(self, path, target_h):
        """Scale an image down to about `target_h` pixels tall."""
        if HAVE_PIL:
            image = Image.open(path).convert("RGB")
            scale = target_h / float(max(1, image.height))
            size = (max(1, int(image.width * scale)),
                    max(1, int(image.height * scale)))
            return ImageTk.PhotoImage(image.resize(size, Image.LANCZOS))
        # Tk handles PNG and GIF unaided, but only whole-number downscaling.
        photo = tk.PhotoImage(file=path)
        factor = max(1, int(round(photo.height() / float(max(1, target_h)))))
        if factor > 1:
            photo = photo.subsample(factor, factor)
        return photo

    def _ensure_preview_photo(self, height):
        """Load and cache the backdrop, rescaling only when the size changes."""
        if not self.preview_image_path:
            self.preview_photo = None
            return
        key = (self.preview_image_path, height)
        if self._photo_key == key and self.preview_photo is not None:
            return
        try:
            self.preview_photo = self._scaled_photo(self.preview_image_path,
                                                    height)
            self._photo_key = key
        except Exception:
            self.preview_photo = None
            self._photo_key = None
            self.preview_image_path = ""
            self._update_backdrop_label()
            self.status.set(
                "Could not read that image \u2014 PNG or GIF works"
                if not HAVE_PIL else "Could not read that image"
            )

    def _paint_sample_map(self, c, w, h):
        """A small stylised battle map: grass, trees, a path and a building.

        Used when no real map has been chosen. Tiled from a fixed-width scene
        so any panel width looks deliberate, and tagged so it is only rebuilt
        when the canvas is resized rather than on every slider movement.
        """
        self._ensure_preview_photo(int(h))
        if self.preview_photo is not None:
            # Tile the real map to cover, so a portrait map still fills a wide
            # strip instead of leaving the rest of the preview blank.
            image_w = max(1, self.preview_photo.width())
            image_h = max(1, self.preview_photo.height())
            for x in range(0, int(w) + image_w, image_w):
                for y in range(0, int(h) + image_h, image_h):
                    c.create_image(x, y, anchor="nw", image=self.preview_photo,
                                   tags="map")
            return

        c.create_rectangle(0, 0, w, h, fill=MAP_GRASS, outline="", tags="map")

        # Grass mottling, coarse enough to stay cheap.
        step = self._px(9)
        columns = int(w / step) + 1
        for index in range(columns * (int(h / step) + 1)):
            if deterministic_noise(index * 7 + 3) > 0.62:
                x = (index % columns) * step
                y = (index // columns) * step
                c.create_rectangle(x, y, x + step, y + step,
                                   fill=MAP_GRASS_DARK, outline="", tags="map")

        scene = max(self._px(150), self._px(210))
        for start in range(0, int(w) + scene, scene):
            self._paint_scene(c, start, scene, h)

    def _paint_scene(self, c, x0, width, height):
        px = self._px

        # Trees on the left of the scene.
        for i in range(3):
            radius = px(7) + px(4) * deterministic_noise(x0 + i * 31)
            cx = x0 + width * (0.04 + 0.09 * i) + px(3)
            cy = height * (0.22 + 0.5 * deterministic_noise(x0 + i * 57))
            c.create_oval(cx - radius, cy - radius, cx + radius, cy + radius,
                          fill=MAP_TREE, outline="", tags="map")
            c.create_oval(cx - radius * 0.55, cy - radius * 0.75,
                          cx + radius * 0.25, cy - radius * 0.05,
                          fill=MAP_TREE_LIT, outline="", tags="map")

        # A stone path running the full height.
        path_x = x0 + width * 0.36
        path_w = max(px(16), width * 0.11)
        c.create_rectangle(path_x, 0, path_x + path_w, height,
                           fill=MAP_PATH, outline="", tags="map")
        cobble = px(6)
        rows = int(height / cobble) + 1
        for row in range(rows):
            for col in range(int(path_w / cobble) + 1):
                if deterministic_noise(x0 + row * 13 + col * 101) > 0.55:
                    x = path_x + col * cobble
                    y = row * cobble
                    c.create_rectangle(x, y, x + cobble, y + cobble,
                                       fill=MAP_PATH_DARK, outline="",
                                       tags="map")

        # A building: stone wall, timber floor, a tiled room and a carpet.
        left = x0 + width * 0.56
        right = x0 + width * 0.95
        top = height * 0.14
        bottom = height * 0.88
        if right - left < px(30) or bottom - top < px(18):
            return
        c.create_rectangle(left, top, right, bottom, fill=MAP_WALL,
                           outline=MAP_DARK, tags="map")
        wall = max(px(3), (bottom - top) * 0.08)
        c.create_rectangle(left + wall, top + wall, right - wall, bottom - wall,
                           fill=MAP_WOOD, outline="", tags="map")
        # Floorboards.
        board = px(5)
        y = top + wall
        while y < bottom - wall:
            c.create_line(left + wall, y, right - wall, y,
                          fill=MAP_WOOD_DARK, tags="map")
            y += board
        # Tiled room in the left third.
        split = left + (right - left) * 0.38
        c.create_rectangle(left + wall, top + wall, split, bottom - wall,
                           fill=MAP_TILE, outline=MAP_DARK, tags="map")
        # Carpet in the right part.
        carpet_x = split + (right - split) * 0.25
        carpet_y = top + (bottom - top) * 0.35
        c.create_rectangle(carpet_x, carpet_y,
                           carpet_x + (right - split) * 0.42,
                           carpet_y + (bottom - top) * 0.32,
                           fill=MAP_CARPET, outline="", tags="map")

    def _paint_colour_chip(self, c, w, colour, opacity):
        """State the colour outright, so the preview cannot be misread."""
        px = self._px
        label = "%s   %d%%" % (colour.upper(), opacity)
        probe = c.create_text(0, -50, text=label, anchor="nw",
                              font=self.f_hint, tags="chip")
        bounds = c.bbox(probe)
        c.delete(probe)
        text_w = (bounds[2] - bounds[0]) if bounds else px(60)
        text_h = (bounds[3] - bounds[1]) if bounds else px(11)

        pad = px(5)
        chip = px(9)
        plate_w = pad + chip + px(5) + text_w + pad
        plate_h = max(chip, text_h) + pad
        x0 = w - plate_w - px(6)
        y0 = px(6)
        c.create_rectangle(x0, y0, x0 + plate_w, y0 + plate_h,
                           fill=INK, outline=LINE, tags="chip")
        middle = y0 + plate_h / 2
        c.create_rectangle(x0 + pad, middle - chip / 2,
                           x0 + pad + chip, middle + chip / 2,
                           fill=colour, outline=LINE, tags="chip")
        c.create_text(x0 + pad + chip + px(5), middle, text=label, anchor="w",
                      fill=TEXT, font=self.f_hint, tags="chip")

    def _paint_preview(self, kind, size, off_x, off_y, colour, weight, opacity):
        c = self.preview
        w, h = self.preview.winfo_width(), self.preview.winfo_height()
        if w <= 1 or h <= 1:
            return

        # The map is static, so rebuild it only when the canvas changes size.
        if getattr(self, "_map_size", None) != (w, h):
            c.delete("map")
            self._paint_sample_map(c, w, h)
            self._map_size = (w, h)

        c.delete("grid")
        c.delete("chip")
        # A canvas has no alpha, so fade the line toward a mid map tone by the
        # same fraction the real overlay would be transparent by.
        shown = blend(colour, MAP_MID, max(0.10, opacity / 100.0))
        if kind == "Square":
            for x1, y1, x2, y2 in square_lines(w, h, size, off_x, off_y):
                c.create_line(x1, y1, x2, y2, fill=shown, width=weight,
                              tags="grid")
        else:
            for pts in hex_polys(w, h, size, off_x, off_y,
                                 pointy=(kind == "Hex (pointy top)")):
                c.create_polygon(pts, outline=shown, fill="", width=weight,
                                 tags="grid")
        c.tag_raise("grid")
        self._paint_colour_chip(c, w, colour, opacity)

    # -- keys --------------------------------------------------------------

    def _bind_keys(self):
        r = self.root
        pairs = (
            ("<Left>", self.off_x, -1), ("<Right>", self.off_x, 1),
            ("<Up>", self.off_y, -1), ("<Down>", self.off_y, 1),
            ("<Shift-Left>", self.off_x, -10), ("<Shift-Right>", self.off_x, 10),
            ("<Shift-Up>", self.off_y, -10), ("<Shift-Down>", self.off_y, 10),
            ("<plus>", self.cell, 1), ("<KP_Add>", self.cell, 1),
            ("<minus>", self.cell, -1), ("<KP_Subtract>", self.cell, -1),
            ("<bracketleft>", self.cell, -0.5), ("<bracketright>", self.cell, 0.5),
        )
        for sequence, var, delta in pairs:
            r.bind(sequence, lambda e, v=var, d=delta: self.bump(v, d))

        # There is deliberately no bare-letter shortcut here. A plain "h" used
        # to hide the overlay, but a key binding on the window catches the
        # keystroke wherever the focus is, so typing a band name containing an
        # h - Reach, for one - toggled the grid mid-word. The global hotkey
        # already does the job and works whether this panel has focus or not,
        # which made the local one redundant as well as hazardous. The bindings
        # above are safe because bump ignores them while a field has focus.
        # Escape deliberately does nothing here. Closing a tool that sits open
        # all session on a single stray keypress is too easy to do by accident;
        # dialogs still use Escape to dismiss themselves.

    # -- behaviour ---------------------------------------------------------

    def bump(self, var, delta, force=False):
        if not force:
            try:
                focused = self.root.focus_get()
            except (tk.TclError, KeyError):
                focused = None                   # focus is on a foreign window
            if isinstance(focused, (ttk.Entry, tk.Entry, ttk.Spinbox)):
                return                           # typing in a field
        value = round(safe_float(var) + delta, 2)
        if var is self.cell:
            value = max(8.0, value)
        if var is self.opacity:
            value = min(100.0, max(10.0, value))
        var.set(int(round(value)) if isinstance(var, tk.IntVar) else value)

    def pick_colour(self):
        chosen = ColourPicker(self, self.root, self.colour.get(),
                              "Grid line colour").show()
        if chosen:
            self.colour.set(chosen)

    def _refresh_band_summary(self):
        """The distances, listed for the DM only.

        This is where the numbers live now. Nothing is printed on the map until
        the reveal key is held, so glancing at the panel is how you know what
        the rings mean.
        """
        unit = self.unit.get()
        suffix = "" if unit == "squares" else " " + unit
        self.band_summary.set("   \u00b7   ".join(
            "%s %s%s" % (name, tidy_number(distance, 2), suffix)
            for name, distance in self.bands))

    def pick_band_colour(self):
        chosen = ColourPicker(self, self.root, self.band_colour.get(),
                              "Range band colour").show()
        if chosen:
            self.band_colour.set(chosen)

    def apply_screen(self):
        choice = self.screen_choice.get()
        if choice.startswith("Custom"):
            rect = parse_geometry(self.region.get())
            if rect is None:
                self.region_entry.focus_set()
                self.status.set("Region needs the form 1920x1080+0+0")
                return
        else:
            index = self.screen_box.current()
            if index < 0 or index >= len(self.monitors):
                index = 0
            rect = self.monitors[index]
        x, y, w, h = rect
        self.region.set(f"{w}x{h}{x:+d}{y:+d}")
        self.overlay.place_on(x, y, w, h)
        self.status.set("Overlay live" if self.visible.get() else "Overlay hidden")
        self.schedule_draw()

    def apply_opacity(self):
        try:
            self.overlay.set_opacity(self.opacity.get())
        except tk.TclError:
            pass
        self.schedule_draw()

    def apply_visibility(self):
        if self.visible.get():
            self.status.set("Overlay live")
            self.overlay.show()
            self.apply_click_through()
            self.schedule_draw()
        else:
            self.status.set("Overlay hidden")
            self.overlay.hide()
        self._paint_lamp()

    def apply_click_through(self):
        self.overlay.set_click_through(bool(self.click_through.get()))

    def toggle_visible(self):
        self.visible.set(not self.visible.get())
        self.apply_visibility()

    def schedule_draw(self):
        if self._pending:
            return
        self._pending = True
        self.root.after(25, self._draw)

    def _draw(self):
        self._pending = False
        colour = str(self.colour.get())
        if not colour.startswith("#"):
            return
        kind = self.grid_type.get()
        size = max(8.0, safe_float(self.cell, 64.0))
        off_x, off_y = safe_float(self.off_x), safe_float(self.off_y)
        weight = max(1, int(safe_float(self.line_w, 1)))
        opacity = max(10, min(100, int(safe_float(self.opacity, 70))))

        self._paint_swatches()
        self._paint_preview(kind, size, off_x, off_y, colour, weight, opacity)
        if self.visible.get():
            self.overlay.draw(kind, size, off_x, off_y, colour, weight)

    def _close_button(self):
        log_event("window close button pressed")
        self.quit()

    def _hold_top(self):
        if self.visible.get():
            self.overlay.raise_above()
        self.root.after(2000, self._hold_top)

    def quit(self):
        # The single most useful breadcrumb: if the app disappears and this
        # line is absent from the log, nothing asked it to close - it died.
        caller = "".join(traceback.format_stack(limit=4)[:-1]).strip()
        log_event("quit() called\n    %s" % caller.replace("\n", "\n    "))
        try:
            panel_geometry = self.root.geometry()
        except tk.TclError:
            panel_geometry = ""
        save_settings({
            "panel_geometry": panel_geometry,
            "screen": self.screen_choice.get(),
            "region": self.region.get(),
            "grid_type": self.grid_type.get(),
            "cell": safe_float(self.cell, 64.0),
            "off_x": safe_float(self.off_x),
            "off_y": safe_float(self.off_y),
            "line_w": int(safe_float(self.line_w, 1)),
            "opacity": int(safe_float(self.opacity, 70)),
            "colour": self.colour.get(),
            "click_through": bool(self.click_through.get()),
            "overlay_on_start": bool(self.overlay_on_start.get()),
            "preview_image": self.preview_image_path,
            "per_square": safe_float(self.per_square, 5.0),
            "unit": self.unit.get(),
            "diagonal_rule": self.diagonal_rule.get(),
            "bands": format_bands(self.bands),
            "range_mode": self.range_mode.get(),
            "band_colour": self.band_colour.get(),
            "conditions": format_conditions(self.conditions),
            "conditions_version": CONDITION_DEFAULTS_VERSION,
            "marker_size": int(safe_float(self.marker_size, 84)),
            "check_updates": bool(self.check_updates.get()),
            "last_update_check": self.last_update_check,
            "latest_seen": self.latest_seen,
            "hotkeys": self.hotkeys,
            "hotkeys_version": HOTKEY_DEFAULTS_VERSION,
            "theme": self.theme_name,
            "custom_theme": self.custom_theme,
            "start_minimised": bool(self.start_minimised.get()),
        })
        self.hotkey_manager.destroy()
        log_event("---- clean exit")
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
