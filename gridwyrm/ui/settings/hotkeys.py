"""Editing the system-wide hotkeys."""

import tkinter as tk

from tkinter import ttk

from ...core.hotkeys import (ACTIONS, DEFAULT_HOTKEYS, HOTKEY_OFF,
                            KEY_ORDER, MODIFIER_ORDER)
from ...core.win32 import IS_WINDOWS


class HotkeysTab:
    """One row per action, with the result of registering each.

    Constructed by the settings window, which passes itself in. The tab reaches
    back through it for the application and for the framing helpers every tab
    shares, and owns nothing else.
    """

    def __init__(self, window):
        self.window = window
        self.app = window.app
        self.win = window.win
        self.rows = {}                       # one entry per action

    def _tab(self):
        return self.window._tab()

    def _note(self, parent, text, pady=(0, 0)):
        return self.window._note(parent, text, pady)

    def build(self):
        pad = self.app.ui.px
        holder, inner = self._tab()

        self._note(inner,
                   "These work anywhere in Windows, even while the map has "
                   "focus. A hotkey is claimed system-wide, so avoid combos "
                   "your other programs need \u2014 that is why the defaults "
                   "use two or three modifiers.",
                   pady=(0, pad(10)))

        table = ttk.Frame(inner, style="Card.TFrame")
        table.pack(fill="both", expand=True)
        table.columnconfigure(0, weight=1)

        ttk.Label(table, text="ACTION", style="Head.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, pad(5))
        )
        for column, title in ((1, "MODIFIERS"), (2, "KEY")):
            ttk.Label(table, text=title, style="Head.TLabel").grid(
                row=0, column=column, sticky="w", padx=(pad(8), 0),
                pady=(0, pad(5))
            )

        for index, (action, label, _repeat) in enumerate(ACTIONS, start=1):
            ttk.Label(table, text=label, style="TLabel").grid(
                row=index, column=0, sticky="w", pady=pad(2)
            )
            mods, key = tk.StringVar(), tk.StringVar()
            mods_box = self.app.ui.register_combo(ttk.Combobox(
                table, values=MODIFIER_ORDER, textvariable=mods,
                state="readonly", width=17))
            mods_box.grid(row=index, column=1, sticky="w",
                          padx=(pad(8), 0), pady=pad(2))
            key_box = self.app.ui.register_combo(ttk.Combobox(
                table, values=KEY_ORDER, textvariable=key,
                state="readonly", width=10))
            key_box.grid(row=index, column=2, sticky="w",
                         padx=(pad(8), 0), pady=pad(2))
            status = ttk.Label(table, text="", style="Hint.TLabel", width=15)
            status.grid(row=index, column=3, sticky="w", padx=(pad(8), 0))
            self.rows[action] = {"mods": mods, "key": key, "status": status,
                                 "key_box": key_box}
            mods.trace_add("write", lambda *_a, a=action: self._sync_row(a))

        self.hotkey_status = ttk.Label(inner, text="", style="Hint.TLabel",
                                       justify="left",
                                       wraplength=self.app.ui.px(430))
        self.hotkey_status.pack(anchor="w", fill="x", pady=(pad(10), 0))

        if not IS_WINDOWS:
            self.hotkey_status.configure(
                text="System-wide hotkeys need Windows. The shortcuts listed "
                     "at the bottom of the main panel still work while the "
                     "panel has focus."
            )

        buttons = ttk.Frame(inner, style="Card.TFrame")
        buttons.pack(fill="x", pady=(pad(10), 0))
        ttk.Button(buttons, text="Apply hotkeys",
                   command=self.apply_hotkeys).pack(side="right")
        ttk.Button(buttons, text="Restore defaults",
                   command=self.restore_hotkey_defaults).pack(side="left")
        return holder

    def _sync_row(self, action):
        """A disabled row has no key to choose."""
        row = self.rows[action]
        off = row["mods"].get() == HOTKEY_OFF
        row["key_box"].configure(state="disabled" if off else "readonly")
        if off:
            row["status"].configure(text="")

    def load(self, hotkeys):
        for action, _label, _repeat in ACTIONS:
            mods, key = hotkeys.get(action, DEFAULT_HOTKEYS[action])
            self.rows[action]["mods"].set(mods)
            self.rows[action]["key"].set(key or "G")
            self._sync_row(action)

    def restore_hotkey_defaults(self):
        self.load(DEFAULT_HOTKEYS)
        self.hotkey_status.configure(
            text="Defaults restored. Choose Apply hotkeys to use them."
        )

    def apply_hotkeys(self):
        bindings = {
            action: [self.rows[action]["mods"].get(),
                     self.rows[action]["key"].get()]
            for action, _label, _repeat in ACTIONS
        }

        # Catch two actions sharing one combo before Windows does.
        seen, clashes = {}, set()
        for action, pair in bindings.items():
            if pair[0] == HOTKEY_OFF:
                continue
            signature = (pair[0], pair[1])
            if signature in seen:
                clashes.add(action)
                clashes.add(seen[signature])
            seen[signature] = action

        for action, _label, _repeat in ACTIONS:
            self.rows[action]["status"].configure(text="")

        if clashes:
            for action in clashes:
                self.rows[action]["status"].configure(text="duplicate")
            self.hotkey_status.configure(
                text="Two actions share a combo. Change one of the rows "
                     "marked duplicate."
            )
            return

        failures = self.app.apply_hotkeys(bindings)
        if not failures:
            self.hotkey_status.configure(text="All hotkeys active.")
            return
        for action, reason in failures.items():
            self.rows[action]["status"].configure(text=reason)
        self.hotkey_status.configure(
            text="Some combos were refused, usually because another program "
                 "already owns them. Everything else is active \u2014 pick "
                 "different keys for the rows marked above."
        )
