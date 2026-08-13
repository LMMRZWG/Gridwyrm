"""A colour picker that follows the theme."""

import colorsys
import tkinter as tk
from tkinter import ttk

from ..core import theme
from .placement import centre_on
from ..core.theme import HEX_RE, hex_to_rgb, rgb_to_hex
from ..core.win32 import set_frame_mode


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
        px = app.ui.px

        self.hue, self.sat, self.val = colorsys.rgb_to_hsv(
            *hex_to_rgb(self.initial)
        )

        self.win = tk.Toplevel(parent)
        self.win.withdraw()                      # placed before it is shown
        self.win.title(title)
        self.win.configure(bg=theme.INK)
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
                                highlightthickness=1, highlightbackground=theme.LINE,
                                bd=0, takefocus=0, cursor="crosshair")
        self.square.pack(side="left")
        self.square.bind("<Button-1>", self._square_pick)
        self.square.bind("<B1-Motion>", self._square_pick)

        self.rail = tk.Canvas(top, width=px(self.RAIL_W), height=side,
                              highlightthickness=1, highlightbackground=theme.LINE,
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
                                 highlightbackground=theme.LINE, bd=0, takefocus=0)
        self.compare.pack(side="left")
        ttk.Label(readout, text="was / now", style="Hint.TLabel").pack(
            side="left", padx=(px(6), 0)
        )
        self.hex_value = tk.StringVar(value=self.initial.upper())
        entry = ttk.Entry(readout, textvariable=self.hex_value,
                          font=app.ui.f_num, width=9, justify="center")
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
        r = self.app.ui.px(5)
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
        c.configure(bg=theme.PANEL)
        box = self.app.ui.px(18)
        gap = self.app.ui.px(4)
        width = c.winfo_width()
        current = self.hex_value.get().upper()
        for index, colour in enumerate(self.quick_colours):
            x = index * (box + gap)
            if width > 1 and x + box > width:
                break
            c.create_rectangle(
                x, 0, x + box, box, fill=colour,
                outline=theme.HILITE if colour.upper() == current else theme.LINE,
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
        box = self.app.ui.px(18)
        gap = self.app.ui.px(4)
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
        centre_on(self.win, parent, self.app.ui.px(50))

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
