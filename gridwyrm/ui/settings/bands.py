"""Editing the named range bands."""

from tkinter import ttk

from ...core.bands import DEFAULT_BANDS, MAX_BANDS
from ...core.measuring import tidy_number
from ..row_editor import RowEditor, text_editor


class BandsTab:
    """A name and a distance per band.

    The grid, the add and remove buttons, and the reload-after-apply all come
    from RowEditor, which the conditions tab uses as well. What is left here is
    only what is particular to bands: distances are in the panel's unit, and
    they are sorted.
    """

    def __init__(self, window):
        self.window = window
        self.app = window.app
        self.win = window.win
        self.editor = None

    def build(self):
        pad = self.app.ui.px
        holder, inner = self.window._tab()

        unit = self.app.unit.get()
        self.window._note(
            inner,
            "A name and a distance for each ring. Distances are in %s, the unit "
            "the panel is set to. They are sorted for you, so the order you "
            "enter them in does not matter."
            % ("squares" if unit == "squares" else unit),
            pady=(0, pad(10)))

        heading = "DISTANCE" if unit == "squares" else "DISTANCE (%s)" % unit
        self.editor = RowEditor(inner, self.app, "band", heading,
                                text_editor(self.app), MAX_BANDS)
        self.editor.load([(name, tidy_number(distance, 2))
                          for name, distance in self.app.bands])

        buttons = ttk.Frame(inner, style="Card.TFrame")
        buttons.pack(fill="x", pady=(pad(10), 0))
        ttk.Button(buttons, text="Apply bands", command=self.apply).pack(
            side="right")
        ttk.Button(buttons, text="Restore defaults",
                   command=self.restore).pack(side="left")
        return holder

    def apply(self):
        error = self.app.ranges_feature.set_bands(self.editor.pairs())
        if error:
            self.editor.say(error)
            return
        # Reload from what was accepted, so the rows show the sorted order and
        # the tidied numbers rather than whatever was typed.
        self.editor.load([(name, tidy_number(distance, 2))
                          for name, distance in self.app.bands])
        self.editor.say("%d bands in use." % len(self.app.bands))

    def restore(self):
        self.editor.load([(name, tidy_number(distance, 2))
                          for name, distance in DEFAULT_BANDS])
        self.editor.say("Defaults restored. Choose Apply bands to use them.")
