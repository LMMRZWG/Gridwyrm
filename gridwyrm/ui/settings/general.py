"""Startup behaviour and the update check."""

import tkinter as tk

from tkinter import ttk

from ...core.updates import VERSION
from ...core.win32 import IS_WINDOWS, autostart_state, set_autostart


class GeneralTab:
    """Start with Windows, start minimised, and updates.

    Constructed by the settings window, which passes itself in. The tab reaches
    back through it for the application and for the framing helpers every tab
    shares, and owns nothing else.
    """

    def __init__(self, window):
        self.window = window
        self.app = window.app
        self.win = window.win

    def _tab(self):
        return self.window._tab()

    def _note(self, parent, text, pady=(0, 0)):
        return self.window._note(parent, text, pady)

    def build(self):
        pad = self.app.ui.px
        holder, inner = self._tab()

        ttk.Label(inner, text="STARTUP", style="Head.TLabel").pack(
            anchor="w", pady=(0, pad(8))
        )

        # The registry, not the settings file, decides whether this is on -
        # the entry may have been removed by other means since last time.
        enabled, _recorded = autostart_state()
        self.autostart = tk.BooleanVar(value=enabled)
        self.autostart_check = ttk.Checkbutton(
            inner, text="Start with Windows", variable=self.autostart,
            command=self._toggle_autostart,
        )
        self.autostart_check.pack(anchor="w")
        self._note(inner,
                   "Registers this program for the current user only, so no "
                   "administrator rights are needed. If you move or rename the "
                   "file, the entry is repaired the next time it runs.",
                   pady=(pad(3), pad(10)))

        ttk.Checkbutton(inner, text="Start minimised",
                        variable=self.start_minimised_proxy(),
                        command=self._toggle_minimised).pack(anchor="w")
        self._note(inner,
                   "The grid still appears - only this panel starts out of the "
                   "way, on the taskbar.",
                   pady=(pad(3), pad(10)))

        ttk.Checkbutton(inner, text="Show the overlay at startup",
                        variable=self.app.overlay_on_start,
                        command=self._toggle_overlay_start).pack(anchor="w")
        self._note(inner,
                   "Off means the grid waits until you switch it on, which "
                   "suits starting with Windows on a machine you are not "
                   "always running a game on.",
                   pady=(pad(3), 0))

        ttk.Separator(inner, orient="horizontal").pack(fill="x",
                                                       pady=(pad(12), pad(11)))
        ttk.Label(inner, text="UPDATES", style="Head.TLabel").pack(
            anchor="w", pady=(0, pad(8)))

        ttk.Checkbutton(inner, text="Look for a newer version at startup",
                        variable=self.app.check_updates,
                        command=self._toggle_updates).pack(anchor="w")
        self._note(inner,
                   "Asks GitHub once a day whether a newer release exists, and "
                   "says so. It never downloads or installs anything: finding "
                   "an update gives you a button that opens the download page. "
                   "Nothing about you is sent, and switching this off stops "
                   "Gridwyrm using the network at all.",
                   pady=(pad(3), pad(8)))

        check_row = ttk.Frame(inner, style="Card.TFrame")
        check_row.pack(fill="x")
        ttk.Button(check_row, text="Check now",
                   command=lambda: self.app.updater.check_for_update(manual=True)
                   ).pack(side="left")
        ttk.Label(check_row, textvariable=self.app.update_notice,
                  style="Hint.TLabel").pack(side="left",
                                            padx=(pad(8), 0))
        ttk.Label(inner, text="This copy is version %s." % VERSION,
                  style="Hint.TLabel").pack(anchor="w", pady=(pad(6), 0))

        self.general_status = ttk.Label(inner, text="", style="Hint.TLabel",
                                       justify="left",
                                       wraplength=self.app.ui.px(430))
        self.general_status.pack(anchor="w", fill="x", pady=(pad(10), 0))

        if not IS_WINDOWS:
            self.autostart_check.state(["disabled"])
            self.general_status.configure(
                text="Starting with the system needs Windows."
            )
        return holder

    def start_minimised_proxy(self):
        return self.app.start_minimised

    def _toggle_autostart(self):
        wanted = bool(self.autostart.get())
        ok, message = set_autostart(wanted)
        if ok:
            self.general_status.configure(
                text="Will start with Windows." if wanted
                else "Will no longer start with Windows."
            )
        else:
            self.autostart.set(not wanted)       # reflect what really happened
            self.general_status.configure(
                text="Could not change the registry entry: %s" % message
            )

    def _toggle_minimised(self):
        self.general_status.configure(
            text="This panel will start minimised."
            if self.app.start_minimised.get()
            else "This panel will start visible."
        )

    def _toggle_updates(self):
        self.general_status.configure(
            text="Gridwyrm will look for a newer version at startup."
            if self.app.check_updates.get()
            else "Gridwyrm will not use the network at all.")

    def _toggle_overlay_start(self):
        self.general_status.configure(
            text="The grid will be showing when the app starts."
            if self.app.overlay_on_start.get()
            else "The grid will start switched off."
        )
