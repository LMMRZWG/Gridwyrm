"""Condition markers: coloured rings on creatures."""

import tkinter.font as tkfont

from ..core.geometry import cell_footprint, safe_float
from ..core.storage import log_event
from ..core.conditions import validate_conditions

class Markers:
    """Condition markers: coloured rings on creatures.
    Positions are held in grid coordinates rather than pixels. A
    marker sits on a creature standing in a square, so rescaling the
    grid or nudging it into alignment has to move the marker with its
    square rather than leave it beside the thing it was marking.

    Given the application, which is where the shared state and the overlay
    live. Nothing here reaches into another feature.
    """

    def __init__(self, app):
        self.app = app
        self.ring_fonts = {}

    def start_place_condition(self):
        name = self.app.condition_choice.get()
        self.app.placing_condition = True
        self.app._take_pointer(
            "conditions",
            "Click each creature that is %s     right-click when done" % name,
            self._condition_click, self._condition_move,
            getattr(self, "condition_button", None), label="Done")
        log_event("conditions: placing %s" % name)

    def _grid_from_pixels(self, x, y):
        cell = max(1.0, safe_float(self.app.cell, 64.0))
        return ((x - safe_float(self.app.off_x)) / cell,
                (y - safe_float(self.app.off_y)) / cell)

    def _pixels_from_grid(self, gx, gy):
        cell = max(1.0, safe_float(self.app.cell, 64.0))
        return (gx * cell + safe_float(self.app.off_x),
                gy * cell + safe_float(self.app.off_y))

    def marker_radius(self):
        """Half the marker's width, as a share of a cell.

        Sized against the grid so a marker stays proportionate to a creature,
        but with its own control, because how big a ring should be is a matter
        of taste rather than arithmetic.
        """
        footprint = cell_footprint(self.app.grid_type.get(),
                                   max(1.0, safe_float(self.app.cell, 64.0)))
        percent = min(300.0, max(10.0, safe_float(self.app.marker_size, 84)))
        return footprint * percent / 200.0

    def condition_colour(self, name):
        for label, colour in self.app.conditions:
            if label == name:
                return colour
        return "#FFFFFF"

    def toggle_place_condition(self):
        if self.app.placing_condition:
            self.app.measure_feature.cancel_measure("")
        else:
            self.start_place_condition()

    def _condition_move(self, x, y, state=0):
        self.app._arm_measure_timeout()

    def _condition_click(self, x, y):
        """Stays in placing mode, so a whole group can be marked in one go."""
        name = self.app.condition_choice.get()
        gx, gy = self._grid_from_pixels(x, y)
        self.app.markers.append((gx, gy, name, self.condition_colour(name)))
        self.app._arm_measure_timeout()
        self._paint_conditions()
        self.app.range_readout.set("%d marked" % len(self.app.markers))

    def clear_conditions(self):
        self.app.markers = []
        self.app.overlay.clear_conditions()

    def undo_condition(self):
        if self.app.markers:
            self.app.markers.pop()
            self._paint_conditions()

    def _ring_font(self, size):
        """Bold text sized in pixels, so it can be fitted to the band exactly."""
        font = self.ring_fonts.get(size)
        if font is None:
            font = tkfont.Font(family=self.app.ui.f_hint.actual("family"),
                               size=-size, weight="bold")
            self.ring_fonts[size] = font
        return font

    def _paint_conditions(self):
        if not self.app.markers:
            self.app.overlay.clear_conditions()
            return
        placed = [self._pixels_from_grid(gx, gy) + (name, colour)
                  for gx, gy, name, colour in self.app.markers]
        self.app.overlay.draw_conditions(placed, self.marker_radius(),
                                     self.app.ui.f_num, self._ring_font)

    def set_conditions(self, rows):
        """Returns an error message, or empty when they were accepted."""
        conditions, error = validate_conditions(rows)
        if not conditions:
            return error
        self.app.conditions = [list(pair) for pair in conditions]
        names = [name for name, _colour in self.app.conditions]
        self.app.condition_box.configure(values=names)
        if self.app.condition_choice.get() not in names:
            self.app.condition_choice.set(names[0])
        # Markers already on the map follow any colour or name change.
        self.app.markers = [(gx, gy, name, self.condition_colour(name))
                        for gx, gy, name, _old in self.app.markers
                        if name in names]
        self._paint_conditions()
        return ""
