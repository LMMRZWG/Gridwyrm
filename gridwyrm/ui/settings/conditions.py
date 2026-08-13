"""Editing the condition list."""

from tkinter import ttk

from ...core.conditions import DEFAULT_CONDITIONS, MAX_CONDITIONS
from ..row_editor import RowEditor, swatch_editor


class ConditionsTab:
    """A name and a colour per condition.

    Shares RowEditor with the bands tab. The only difference is the second
    column: a swatch that opens the colour picker rather than a text field,
    which is passed in as the row editor's widget builder.
    """

    def __init__(self, window):
        self.window = window
        self.app = window.app
        self.win = window.win
        self.editor = None

    def build(self):
        pad = self.app.ui.px
        holder, inner = self.window._tab()

        self.window._note(
            inner,
            "A name and a colour for each condition. Click a swatch to change "
            "it. Markers already on the map follow any change you make here.",
            pady=(0, pad(10)))

        # Two columns once the list gets long: fifteen rows in one would run off
        # the bottom of a laptop screen.
        self.editor = RowEditor(inner, self.app, "condition", "COLOUR",
                                swatch_editor(self.app, self.win),
                                MAX_CONDITIONS, two_column_above=8)
        self.editor.load(list(self.app.conditions))

        buttons = ttk.Frame(inner, style="Card.TFrame")
        buttons.pack(fill="x", pady=(pad(10), 0))
        ttk.Button(buttons, text="Apply conditions",
                   command=self.apply).pack(side="right")
        ttk.Button(buttons, text="Restore defaults",
                   command=self.restore).pack(side="left")
        return holder

    def apply(self):
        error = self.app.markers_feature.set_conditions(self.editor.pairs())
        if error:
            self.editor.say(error)
            return
        self.editor.load(list(self.app.conditions))
        self.editor.say("%d conditions in use." % len(self.app.conditions))

    def restore(self):
        self.editor.load(list(DEFAULT_CONDITIONS))
        self.editor.say(
            "Defaults restored. Choose Apply conditions to use them.")
