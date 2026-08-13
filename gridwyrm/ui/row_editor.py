"""A table of editable rows, with add and remove.

Written once because it was written twice. The bands editor and the conditions
editor were 84 to 99 percent the same code: the same grid, the same add and
remove, the same reload-after-apply. Only two things actually differ, and both
are now arguments: what the second column edits, and how a row is checked.
"""

import tkinter as tk

from tkinter import ttk

from ..core import theme
from ..core.theme import HEX_RE


class RowEditor:
    """Rows of a name plus one other value.

    `kind` names the thing being edited, for the messages. `columns` is the
    heading for the second column. `editor` is called to build the widget that
    edits a row's value, which is what lets bands use a text field and
    conditions use a colour swatch without either knowing about the other.
    """

    def __init__(self, parent, app, kind, second_heading, editor, limit,
                 two_column_above=None):
        self.app = app
        self.kind = kind
        self.second_heading = second_heading
        self.editor = editor
        self.limit = limit
        self.two_column_above = two_column_above
        self.rows = []

        self.grid = ttk.Frame(parent, style="Card.TFrame")
        self.grid.pack(fill="x")

        self.add_button = ttk.Button(parent, text="Add a %s" % kind,
                                    command=self.add_row)
        self.add_button.pack(anchor="w", pady=(app.ui.px(10), 0))

        self.status = ttk.Label(parent, text="", style="Hint.TLabel",
                                justify="left", wraplength=app.ui.px(430))
        self.status.pack(anchor="w", fill="x", pady=(app.ui.px(8), 0))

    # -- contents ----------------------------------------------------------

    def load(self, pairs):
        """Replace the rows. Variables are rebuilt, so nothing stale survives."""
        self.rows = [{"name": tk.StringVar(value=name),
                      "value": tk.StringVar(value=value)}
                     for name, value in pairs]
        self.rebuild()

    def pairs(self):
        return [(row["name"].get(), row["value"].get()) for row in self.rows]

    def say(self, message):
        self.status.configure(text=message)

    # -- the grid ----------------------------------------------------------

    def rebuild(self):
        """Redraw every row. Cheap, and it keeps the columns aligned.

        The variables outlive the widgets, so a row can be added or removed
        without anyone losing what they were part-way through typing.
        """
        pad = self.app.ui.px
        for child in self.grid.winfo_children():
            child.destroy()

        columns = 1
        if self.two_column_above and len(self.rows) > self.two_column_above:
            columns = 2
        for column in range(columns):
            self.grid.columnconfigure(column * 4, weight=1)
            left = column * 4
            ttk.Label(self.grid, text="NAME", style="Head.TLabel").grid(
                row=0, column=left, sticky="w", pady=(0, pad(5)),
                padx=(pad(12) if column else 0, 0))
            ttk.Label(self.grid, text=self.second_heading,
                      style="Head.TLabel").grid(
                row=0, column=left + 1, sticky="w", padx=(pad(8), 0),
                pady=(0, pad(5)))

        per_column = -(-len(self.rows) // columns)          # round up
        removable = len(self.rows) > 1
        for index, row in enumerate(self.rows):
            column = index // per_column
            left = column * 4
            line = index % per_column + 1

            ttk.Entry(self.grid, textvariable=row["name"],
                      width=16 if columns > 1 else 20).grid(
                row=line, column=left, sticky="we", pady=pad(2),
                padx=(pad(12) if column else 0, 0))

            widget = self.editor(self.grid, row)
            widget.grid(row=line, column=left + 1, sticky="w",
                        padx=(pad(8), 0), pady=pad(2))

            remove = ttk.Button(self.grid, text="\u00d7", width=3,
                                command=lambda r=row: self.remove_row(r))
            remove.grid(row=line, column=left + 2, padx=(pad(5), 0),
                        pady=pad(2))
            if not removable:
                remove.state(["disabled"])       # never leave the list empty

        full = len(self.rows) >= self.limit
        self.add_button.state(["disabled"] if full else ["!disabled"])
        if full:
            self.say("%d %ss is as many as fits." % (self.limit, self.kind))

    def add_row(self):
        if len(self.rows) >= self.limit:
            return
        self.rows.append({"name": tk.StringVar(value=""),
                          "value": tk.StringVar(value="")})
        self.rebuild()
        self.say("Fill the new row, then apply.")

    def remove_row(self, row):
        if len(self.rows) <= 1:
            return
        self.rows.remove(row)
        self.rebuild()
        self.say("Apply to confirm.")


def text_editor(app):
    """Second column as a plain field, for a distance."""
    def build(parent, row):
        return ttk.Entry(parent, textvariable=row["value"], font=app.ui.f_num,
                         width=9, justify="right")
    return build


def swatch_editor(app, window):
    """Second column as a colour swatch that opens the picker."""
    def build(parent, row):
        swatch = tk.Canvas(parent, width=app.ui.px(40), height=app.ui.px(18),
                           highlightthickness=1, bd=0, takefocus=0,
                           cursor="hand2")
        paint_swatch(swatch, row["value"].get())
        swatch.bind("<Button-1>",
                    lambda event: _pick(app, window, row, swatch))
        return swatch
    return build


def paint_swatch(swatch, colour):
    try:
        swatch.configure(
            bg=colour if HEX_RE.match(str(colour)) else "#808080",
            highlightbackground=theme.LINE)
    except tk.TclError:
        swatch.configure(bg="#808080", highlightbackground=theme.LINE)


def _pick(app, window, row, swatch):
    from .colour_picker import ColourPicker
    chosen = ColourPicker(app, window, row["value"].get(),
                          "Colour for %s" % (row["name"].get() or "this")
                          ).show()
    if chosen:
        row["value"].set(chosen)
        paint_swatch(swatch, chosen)
