"""Gridwyrm: a transparent grid overlay for tabletop maps.

The package is split by responsibility rather than by convenience:

  core/     everything that does not touch the screen: grid maths, palettes,
            range bands, conditions, settings storage, hotkey registration,
            the update check. All of it testable without a display.

  ui/       the windows and the pieces they are built from. styling.py owns
            fonts, ttk styles and the composite widgets. overlay.py is the
            transparent window, colour_picker.py the picker, pointer.py the
            business of borrowing the mouse, row_editor.py a table of editable
            rows. settings/ is the settings window: a shell plus one module per
            tab.

  features/ one module per feature: measuring, range bands, condition markers,
            the preview strip, the update check. Each is given the application
            and nothing else, owns its own state, and builds its own card in the
            panel.

  app.py    the wiring. Holds the shared state, creates the parts above, and
            connects them.

Two things here are deliberate rather than incidental.

The palette is read as theme.INK rather than imported by name, because its
values are replaced when the theme changes and an imported name would freeze at
whatever it held when the module first loaded.

row_editor.py and pointer.py exist because their contents were written twice and
three times respectively. A table of rows and the act of borrowing the mouse are
both things this program does more than once, and the second copy of either was
where the differences crept in.

Features reach the shared state through self.app. That coupling is deliberate
and one-directional: the application knows its features and calls them, and a
feature does not know what else exists. It is not the purest arrangement, and it
is honest about what it is rather than pretending to an independence the parts do
not have.
"""

from .core.updates import VERSION


__all__ = ["VERSION"]
