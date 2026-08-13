"""Measuring a span, and setting the cell size from one."""

from ..core.geometry import safe_float
from ..core.measuring import (cell_size_from_span,
                             format_measurement, snap_to_axis,
                             tidy_number)
from ..core.storage import log_event
from ..core.win32 import SHIFT_HELD

class Measure:
    """Measuring a span, and setting the cell size from one.
    Two jobs from one gesture: reading a distance off the map during
    play, and working backwards from a span of known length to the
    cell size, which is how the grid gets aligned in the first place.

    Given the application, which is where the shared state and the overlay
    live. Nothing here reaches into another feature.
    """

    def __init__(self, app):
        self.app = app
        self.state = None               # the span in progress, or None
        self.span = None

    def forget_span(self):
        """Clear the span in progress, however the mouse came back.

        Called by the application when the overlay releases the pointer, which
        covers all of it: a finished measurement, a right-click, the panel
        button, and the timeout. Without this the span outlives the session and
        the next press of Measure believes one is already running, so it cancels
        instead of starting.
        """
        self.state = None

    def toggle_measure(self):
        if self.state is not None:
            self.cancel_measure("Measuring cancelled")
        else:
            self.start_measure()

    def start_measure(self):
        """Begin a span. The overlay must be visible to be measured on."""
        self.state = {"first": None, "last": None, "snapped": False}
        self.app._take_pointer(
            "measure",
            "Click two points to measure     hold Shift to keep it straight"
            "     right-click to cancel",
            self._measure_click, self._measure_move,
            getattr(self.app, "measure_button", None))
        self.app.span_row.pack_forget()
        self.app.measure_readout.set("Click the first point on the map")
        self.app.status.set("Measuring")
        log_event("measure: started")

    def _measure_move(self, x, y, state=0):
        if self.state is None or self.state["first"] is None:
            return
        self.app._arm_measure_timeout()
        x1, y1 = self.state["first"]
        if state & SHIFT_HELD:
            x2, y2, snapped = snap_to_axis(x1, y1, x, y)
        else:
            x2, y2, snapped = x, y, False
        self.state["last"] = (x2, y2)
        self.state["snapped"] = snapped
        self.app.overlay.draw_measure(x1, y1, x2, y2, self._span_label(x1, y1, x2, y2),
                                  self.app.ui.f_num)

    def _measure_click(self, x, y):
        if self.state is None:
            return
        self.app._arm_measure_timeout()
        if self.state["first"] is None:
            self.state["first"] = (x, y)
            self.app.measure_readout.set("Now click the far point")
            self.app.overlay.draw_measure(x, y, x, y, "", self.app.ui.f_num)
            return
        self._finish_measure()

    def _span_label(self, x1, y1, x2, y2):
        text = format_measurement(
            x2 - x1, y2 - y1, max(1.0, safe_float(self.app.cell, 64.0)),
            self.app.diagonal_rule.get(), safe_float(self.app.per_square, 5.0),
            self.app.unit.get())
        return text + ("   straight" if self.state["snapped"] else "")

    def _finish_measure(self):
        first, last = self.state["first"], self.state["last"]
        if first is None or last is None:
            self.cancel_measure("Measuring cancelled")
            return
        dx, dy = last[0] - first[0], last[1] - first[1]
        self.app._release_measure()
        self.span = (dx, dy)
        self.app.measure_readout.set(format_measurement(
            dx, dy, max(1.0, safe_float(self.app.cell, 64.0)),
            self.app.diagonal_rule.get(), safe_float(self.app.per_square, 5.0),
            self.app.unit.get()))
        self.app.span_row.pack(fill="x", pady=(self.app.ui.px(6), 0))
        self.app.status.set("Overlay live" if self.app.visible.get() else "Overlay hidden")
        log_event("measure: %d x %d px" % (round(dx), round(dy)))

    def cancel_measure(self, message=""):
        self.app._release_measure()
        self.app.overlay.canvas.delete("measure")
        self.app.measure_readout.set(message)
        self.app.span_row.pack_forget()
        self.app.status.set("Overlay live" if self.app.visible.get() else "Overlay hidden")

    def apply_span_as_cell_size(self):
        """Turn the measured span into a cell size."""
        span = self.span
        if span is None:
            return
        size = cell_size_from_span(span[0], span[1], self.app.span_squares.get())
        if size is None:
            self.app.measure_readout.set(
                "Give the number of squares that span covered, as a plain "
                "number")
            return
        self.app.cell.set(size)
        self.app.measure_readout.set("Cell size set to %s px" % tidy_number(size, 2))
        self.app.span_row.pack_forget()
        self.app.overlay.canvas.delete("measure")
        log_event("measure: cell size set to %s" % size)
