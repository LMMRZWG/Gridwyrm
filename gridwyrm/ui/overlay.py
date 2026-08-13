"""The transparent window the grid is drawn on."""

import ctypes
import math
import tkinter as tk

from ..core.bands import RING_WEIGHT_PRIVATE, RING_WEIGHT_REVEALED
from ..core.geometry import hex_polys, square_lines
from ..core.theme import HEX_RE, KEY_COLOR, MEASURE_ALPHA, MEASURE_WASH, blend, contrast_halo
from ..core.win32 import IS_WINDOWS, hwnd_of


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
