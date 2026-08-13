"""Placing a window over the one that opened it.

Both dialogs did this, in two copies that had already drifted by a few pixels.
"""

import tkinter as tk


def centre_on(window, parent, drop=40):
    """Put `window` over `parent`, `drop` pixels down from its top.

    Measured against the requested size rather than the actual one, because
    winfo_width reports 1 until a window has been mapped and both dialogs are
    positioned while still hidden.
    """
    try:
        window.update_idletasks()
        width = max(window.winfo_reqwidth(), window.winfo_width())
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + drop
        window.geometry("+%d+%d" % (max(0, x), max(0, y)))
    except tk.TclError:
        pass
