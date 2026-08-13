"""Choosing a theme, and editing a custom one."""

import tkinter as tk

from tkinter import ttk

from ...core import theme
from ...core.theme import (HEX_RE, ROLE_KEYS, THEME_NOTES, THEME_ORDER,
                          THEME_ROLES, resolve_theme)
from ..colour_picker import ColourPicker


class ThemeTab:
    """Five themes, and seven colours when Custom is chosen.

    Constructed by the settings window, which passes itself in. The tab reaches
    back through it for the application and for the framing helpers every tab
    shares, and owns nothing else.
    """

    def __init__(self, window):
        self.window = window
        self.app = window.app
        self.win = window.win
        self.role_widgets = {}               # one entry per colour role

    def restyle(self):
        """Repaint the role swatches after a live theme change.

        _paint_swatch takes the role name and looks the widget up itself, which
        is worth remembering: passing the widget in instead fails with a
        KeyError, and only when a theme is actually switched.
        """
        for role in list(self.role_widgets):
            self._paint_swatch(role, self.role_widgets[role]["value"].get())

    def _tab(self):
        return self.window._tab()

    def _note(self, parent, text, pady=(0, 0)):
        return self.window._note(parent, text, pady)

    def build(self):
        pad = self.app.ui.px
        holder, inner = self._tab()

        picker = ttk.Frame(inner, style="Card.TFrame")
        picker.pack(fill="x")
        ttk.Label(picker, text="Theme", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        self.theme_choice = tk.StringVar(value=self.app.theme_name)
        self.app.ui.register_combo(ttk.Combobox(
            picker, values=list(THEME_ORDER), textvariable=self.theme_choice,
            state="readonly")).pack(side="left", fill="x", expand=True)
        self.theme_choice.trace_add("write", lambda *_: self._choose_theme())

        self.theme_note = self._note(inner, "", pady=(pad(8), pad(12)))

        ttk.Separator(inner, orient="horizontal").pack(fill="x")
        self.custom_head = ttk.Label(inner, text="CUSTOM COLOURS",
                                     style="Head.TLabel")
        self.custom_head.pack(anchor="w", pady=(pad(11), pad(8)))

        table = ttk.Frame(inner, style="Card.TFrame")
        table.pack(fill="x")
        table.columnconfigure(1, weight=1)

        for index, (role, label) in enumerate(THEME_ROLES):
            ttk.Label(table, text=label, style="TLabel").grid(
                row=index, column=0, sticky="w", pady=pad(2)
            )
            swatch = tk.Canvas(table, width=pad(34), height=pad(18),
                               highlightthickness=1, bd=0, takefocus=0,
                               cursor="hand2")
            swatch.grid(row=index, column=1, sticky="w",
                        padx=(pad(8), pad(8)), pady=pad(2))
            swatch.bind("<Button-1>", lambda e, r=role: self._pick_role(r))
            value = tk.StringVar()
            entry = ttk.Entry(table, textvariable=value, font=self.app.ui.f_num,
                              width=9)
            entry.grid(row=index, column=2, sticky="w", pady=pad(2))
            entry.bind("<Return>", lambda e, r=role: self._commit_role(r))
            entry.bind("<FocusOut>", lambda e, r=role: self._commit_role(r))
            button = ttk.Button(table, text="Pick\u2026",
                                command=lambda r=role: self._pick_role(r))
            button.grid(row=index, column=3, sticky="w", padx=(pad(6), 0),
                        pady=pad(2))
            self.role_widgets[role] = {"swatch": swatch, "value": value,
                                       "entry": entry, "button": button}

        actions = ttk.Frame(inner, style="Card.TFrame")
        actions.pack(fill="x", pady=(pad(10), 0))
        self.copy_button = ttk.Button(
            actions, text="Start a custom theme from this one",
            command=self._seed_custom,
        )
        self.copy_button.pack(side="left")

        self.theme_status = ttk.Label(inner, text="", style="Hint.TLabel",
                                      justify="left",
                                      wraplength=self.app.ui.px(430))
        self.theme_status.pack(anchor="w", fill="x", pady=(pad(8), 0))

        self._load_role_rows()
        self._sync_custom_state()
        return holder

    def _choose_theme(self):
        name = self.theme_choice.get()
        self.app.apply_theme(name)
        self._sync_custom_state()

    def _sync_custom_state(self):
        """Only the Custom theme is editable; the rest are shown as they are."""
        custom = self.theme_choice.get() == "Custom"
        state = "normal" if custom else "disabled"
        for widgets in self.role_widgets.values():
            widgets["entry"].configure(state=state)
            widgets["button"].configure(state=state)
        self.custom_head.configure(
            text="CUSTOM COLOURS" if custom else "COLOURS IN THIS THEME"
        )
        self.theme_note.configure(
            text=THEME_NOTES.get(self.theme_choice.get(), "")
        )
        self.theme_status.configure(
            text="" if custom else
            "Read-only. Use the button below to start a custom theme from these."
        )
        self._load_role_rows()

    def _load_role_rows(self):
        """Show the colours of whichever theme is selected.

        Reading from the stored custom theme regardless of selection meant that
        choosing Dark still displayed leftover custom values - wrong
        information presented as fact.
        """
        resolved = resolve_theme(self.theme_choice.get(), self.app.custom_theme)
        for role, widgets in self.role_widgets.items():
            colour = resolved.get(role, "#000000")
            widgets["value"].set(colour)
            self._paint_swatch(role, colour)

    def _paint_swatch(self, role, colour):
        swatch = self.role_widgets[role]["swatch"]
        swatch.delete("all")
        try:
            swatch.configure(bg=colour, highlightbackground=theme.LINE)
        except tk.TclError:
            swatch.configure(bg="#808080", highlightbackground=theme.LINE)

    def _pick_role(self, role):
        if self.theme_choice.get() != "Custom":
            return
        current = self.role_widgets[role]["value"].get()
        chosen = ColourPicker(
            self.app, self.win,
            current if HEX_RE.match(current) else "#808080",
            "Colour for %s" % dict(THEME_ROLES)[role],
        ).show()
        if chosen:
            self.role_widgets[role]["value"].set(chosen.upper())
            self._commit_role(role)

    def _commit_role(self, role):
        if self.theme_choice.get() != "Custom":
            return
        value = self.role_widgets[role]["value"].get().strip()
        if not value.startswith("#"):
            value = "#" + value
        if not HEX_RE.match(value):
            self.theme_status.configure(
                text="%s needs a six-digit hex colour, such as #1E222B."
                     % dict(THEME_ROLES)[role]
            )
            self._load_role_rows()
            return
        value = value.upper()
        self.app.custom_theme[role] = value
        self.theme_status.configure(text="")
        self.app.apply_theme("Custom", self.app.custom_theme)
        self._load_role_rows()

    def _seed_custom(self):
        """Start a custom theme from the one currently selected."""
        source = resolve_theme(self.theme_choice.get(), self.app.custom_theme)
        self.app.custom_theme = {role: source[role] for role in ROLE_KEYS}
        # Setting the picker applies the theme and re-syncs the rows.
        self.theme_choice.set("Custom")
        self.theme_status.configure(
            text="Copied. Edit any colour above to see it applied at once."
        )
