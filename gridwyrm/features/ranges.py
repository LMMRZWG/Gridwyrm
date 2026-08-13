"""Named range bands, and revealing them to the table."""

import ctypes
import time

from ..core.bands import band_radii, validate_bands, visible_rings
from ..core.geometry import safe_float
from ..core.hotkeys import HOTKEY_OFF, VK_MAP, hotkey_text
from ..core.measuring import tidy_number
from ..core.storage import log_event
from ..core.theme import MIN_REVEAL_MS
from ..core.win32 import IS_WINDOWS
from ..ui.colour_picker import ColourPicker

class Ranges:
    """Named range bands, and revealing them to the table.
    Placing a band takes the mouse for exactly one click and hands it
    straight back. That is the whole reason bands work here and
    dragging tokens would not: a token needs the pointer for as long
    as it moves, which would mean giving up click-through for the
    session.

    Given the application, which is where the shared state and the overlay
    live. Nothing here reaches into another feature.
    """

    def __init__(self, app):
        self.app = app
        self.reveal_since = 0.0


    def start_place_ranges(self):
        """One click, then the mouse goes straight back.

        This is the whole reason bands work here and dragging tokens would not.
        A token needs the pointer for as long as you move it, which would mean
        surrendering click-through for the session. A band needs it once.
        """
        self.app.placing_ranges = True
        self.app._take_pointer(
            "ranges",
            "Click the creature to centre the bands on"
            "     right-click to cancel",
            self._range_click, self._range_move,
            getattr(self, "range_button", None))
        self.app.range_readout.set("Click a point on the map")
        log_event("ranges: placing")

    def toggle_place_ranges(self):
        if self.app.placing_ranges:
            self.app.measure_feature.cancel_measure("")
        else:
            self.start_place_ranges()

    def _range_move(self, x, y, state=0):
        """Preview the bands under the cursor before committing to a spot."""
        self.app._arm_measure_timeout()
        self._paint_ranges((x, y), force=True)

    def _range_click(self, x, y):
        self.app.range_origin = (x, y)
        self.app._release_measure()
        self._paint_ranges()
        reveal = hotkey_text(self.app.hotkeys.get("reveal_ranges"))
        self.app.range_readout.set(
            "Bands placed. Hold %s to show them." % reveal
            if reveal != "not set" else "Bands placed.")
        log_event("ranges: placed at %d,%d" % (x, y))

    def clear_ranges(self):
        self.app.range_origin = None
        self.app.overlay.clear_ranges()
        self.app.range_readout.set("")

    def _paint_ranges(self, origin=None, force=False):
        """Draw the bands, or clear them if there is nothing to show."""
        origin = origin or self.app.range_origin
        mode = self.app.range_mode.get()
        if origin is None or (mode == "Off" and not force):
            self.app.overlay.clear_ranges()
            return
        rings = band_radii(self.app.bands,
                           max(1.0, safe_float(self.app.cell, 64.0)),
                           max(0.01, safe_float(self.app.per_square, 5.0)))
        rings, too_big = visible_rings(rings, self.app.overlay.width,
                                       self.app.overlay.height)
        revealed = self.app.revealing or mode == "Show players"
        self.app.overlay.draw_ranges(origin, rings, revealed, self.app.ui.f_num,
                                 self.app.band_colour.get())
        if too_big:
            self.app.range_readout.set(
                "Too wide for this screen: %s. Lower the cell size or the "
                "distance." % ", ".join(too_big))

    def set_bands(self, rows):
        """Take name and distance pairs from the editor.

        Returns an error message, or empty when the bands were accepted.
        """
        bands, error = validate_bands(rows)
        if not bands:
            return error
        self.app.bands = [list(pair) for pair in bands]
        self._refresh_band_summary()
        self._paint_ranges()
        return ""

    def reveal_ranges(self):
        """Show the bands boldly for as long as the key is held.

        Windows reports a hotkey being pressed but never released, so the key is
        polled until it lifts. Holding rather than toggling means there is no
        state to lose track of mid-combat.

        A tap is held for MIN_REVEAL_MS regardless. Without that floor, pressing
        and letting go quickly showed the names for a single frame, which looks
        exactly like the feature not working.
        """
        if self.app.range_origin is None:
            self.app.range_readout.set("Place the bands first")
            return
        if self.app.revealing:
            self.reveal_since = time.monotonic()   # a re-press extends it
            return
        self.app.revealing = True
        self.reveal_since = time.monotonic()
        self._paint_ranges()
        self._watch_reveal_key()

    def _reveal_vk(self):
        pair = self.app.hotkeys.get("reveal_ranges") or [HOTKEY_OFF, ""]
        if pair[0] == HOTKEY_OFF:
            return None
        return VK_MAP.get(pair[1])

    def _watch_reveal_key(self):
        if not self.app.revealing:
            return
        vk = self._reveal_vk()
        if vk is None or not IS_WINDOWS:
            # Without the key to watch, fall back to a brief reveal.
            self.app.root.after(900, self._end_reveal)
            return
        try:
            down = ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000
        except Exception:
            down = 0
        if down:
            self.app.root.after(40, self._watch_reveal_key)
        else:
            self._end_reveal()

    def _end_reveal(self):
        if not self.app.revealing:
            return
        held = (time.monotonic() - self.reveal_since) * 1000
        if held < MIN_REVEAL_MS:
            # Too brief to see. Hold it, then check again.
            self.app.root.after(int(MIN_REVEAL_MS - held), self._end_reveal)
            return
        self.app.revealing = False
        self._paint_ranges()

    def hold_reveal(self, pressed):
        """The panel button, for revealing without the hotkey."""
        if pressed:
            self.reveal_ranges()
        else:
            self._end_reveal()

    def _refresh_band_summary(self):
        """The distances, listed for the DM only.

        This is where the numbers live now. Nothing is printed on the map until
        the reveal key is held, so glancing at the panel is how you know what
        the rings mean.
        """
        unit = self.app.unit.get()
        suffix = "" if unit == "squares" else " " + unit
        self.app.band_summary.set("   \u00b7   ".join(
            "%s %s%s" % (name, tidy_number(distance, 2), suffix)
            for name, distance in self.app.bands))

    def pick_band_colour(self):
        chosen = ColourPicker(self, self.app.root, self.app.band_colour.get(),
                              "Range band colour").show()
        if chosen:
            self.app.band_colour.set(chosen)
