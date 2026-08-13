"""Borrowing the mouse from the overlay for a moment.

Three features need it: measuring a span, placing range bands, and marking
creatures. All three were doing the same six steps by hand, which is three
chances to forget one. Forgetting the release in particular leaves a full-screen
invisible window swallowing every click, which is the worst state this program
can get into, so it is worth having exactly one copy of.
"""

import time


class PointerSession:
    """Holds the overlay's mouse for one interaction, and always gives it back.

    Every way out runs through `release`: a completing click, a right-click,
    the panel button, an exception, or the timeout. The timeout exists because
    a session that is somehow abandoned would otherwise leave the screen
    permanently unclickable.
    """

    TIMEOUT_MS = 30000

    def __init__(self, root, overlay):
        self.root = root
        self.overlay = overlay
        self.mode = None
        self.restore_click_through = True
        self._timer = None
        self._on_release = None
        self.started = 0.0

    @property
    def active(self):
        return self.mode is not None

    def take(self, mode, hint, font, on_click, on_move, on_cancel,
             click_through, on_release=None):
        """Start a session. `mode` is a name, for whoever asks what is running."""
        self.mode = mode
        self.restore_click_through = bool(click_through)
        self._on_release = on_release
        self.started = time.monotonic()

        # Both are needed. The extended style stops the window being skipped,
        # and dropping the colour key gives it pixels that can be hit at all.
        self.overlay.set_click_through(False)
        self.overlay.set_measure_surface(True)
        self.overlay.begin_measure(on_click, on_move, on_cancel)
        self.overlay.show_measure_hint(hint, font)
        self.arm()

    def arm(self):
        """Restart the timeout. Called on any sign of life."""
        self.cancel_timer()
        self._timer = self.root.after(self.TIMEOUT_MS, self._timed_out)

    def cancel_timer(self):
        if self._timer is not None:
            try:
                self.root.after_cancel(self._timer)
            except Exception:
                pass
            self._timer = None

    def _timed_out(self):
        self._timer = None
        self.release()

    def release(self):
        """Give the mouse back. Safe to call more than once."""
        if self.mode is None:
            self.cancel_timer()
            return
        self.mode = None
        self.cancel_timer()
        try:
            self.overlay.end_measure()
        finally:
            # Order matters: the surface goes back before the mouse does, so
            # there is no moment where the overlay is opaque and ignoring clicks.
            self.overlay.set_measure_surface(False)
            self.overlay.set_click_through(self.restore_click_through)
        if self._on_release is not None:
            handler, self._on_release = self._on_release, None
            handler()
