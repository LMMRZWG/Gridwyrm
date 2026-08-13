"""Fonts, ttk styling, and the composite widgets built from them.

Taken out of the application class, which had no business owning three hundred
lines of appearance. Two jobs live here: turning a palette into ttk styles, and
the handful of small widgets that the panel and the settings window both need.
Nothing in this file knows what a grid is.

The one thing it is given from outside is `nudge`, the callback the plus and
minus buttons on a value row call. A row of controls has to do something when
pressed, and what that something is belongs to whoever owns the value.
"""

import tkinter as tk
import tkinter.font as tkfont

from tkinter import ttk

from ..core import theme
from ..core.theme import HEX_RE


class Styling:
    """Fonts, ttk styles and small widgets for one palette."""

    # Below this panel width, value rows stack onto two lines.
    NARROW_AT = 380

    def __init__(self, root, scale, nudge):
        self.root = root
        self.scale = scale
        self.nudge = nudge
        self.style = None
        self._combos = []
        self._swatch_strips = []
        self._wrap_labels = []
        self._value_rows = []
        self._narrow = None
        self._build_fonts()
        self.rebuild()

    def rebuild(self):
        """Apply the current palette. Called again on every theme change."""
        self._build_theme()

    def px(self, n):
        return int(n * self.scale)

    def _build_fonts(self):
        families = set(tkfont.families(self.root))

        def pick(candidates, fallback):
            for name in candidates:
                if name in families:
                    return name
            return fallback

        ui = pick(["Segoe UI Variable Text", "Segoe UI", "Inter", "Ubuntu",
                   "DejaVu Sans", "Helvetica"], "TkDefaultFont")
        mono = pick(["Cascadia Mono", "Consolas", "SF Mono", "Menlo",
                     "DejaVu Sans Mono"], "TkFixedFont")

        self.f_app = tkfont.Font(family=ui, size=11, weight="bold")
        self.f_head = tkfont.Font(family=ui, size=8, weight="bold")
        self.f_body = tkfont.Font(family=ui, size=9)
        self.f_num = tkfont.Font(family=mono, size=9)
        self.f_hint = tkfont.Font(family=ui, size=8)

    def _build_theme(self):
        """Apply the current palette to ttk.

        Two routes. For Classic, ttk is handed back to the operating system's
        own widget engine and only the surfaces we draw ourselves are coloured,
        so controls look exactly as Windows intends. For every other theme,
        'clam' is used because it is the one built-in whose element colours are
        fully configurable, letting real ttk widgets keep every native
        affordance while wearing our palette.
        """
        style = self.style = getattr(self, "style", None) or ttk.Style(self.root)
        available = style.theme_names()

        if theme.NATIVE_WIDGETS:
            for candidate in ("vista", "xpnative", "winnative", "aqua",
                              "default"):
                if candidate in available:
                    style.theme_use(candidate)
                    break
        elif "clam" in available:
            style.theme_use("clam")

        self._style_surfaces(style)
        if not theme.NATIVE_WIDGETS:
            self._style_controls(style)

    def _style_surfaces(self, style):
        """Frames, labels and separators: needed under every theme."""
        style.configure("Card.TFrame", background=theme.PANEL)
        style.configure("Shell.TFrame", background=theme.INK)
        style.configure("TLabel", background=theme.PANEL, foreground=theme.TEXT)
        style.configure("Head.TLabel", background=theme.PANEL, foreground=theme.MUTE,
                        font=self.f_head)
        style.configure("Hint.TLabel", background=theme.PANEL, foreground=theme.MUTE,
                        font=self.f_hint)
        style.configure("Shell.TLabel", background=theme.INK, foreground=theme.MUTE,
                        font=self.f_hint)
        style.configure("App.TLabel", background=theme.INK, foreground=theme.TEXT,
                        font=self.f_app)
        style.configure("Status.TLabel", background=theme.INK, foreground=theme.MUTE,
                        font=self.f_hint)
        style.configure("TSeparator", background=theme.LINE)

    def _style_controls(self, style):
        """The full restyle, for every theme except Classic."""
        pad = int(6 * self.scale)

        style.configure(".", background=theme.PANEL, foreground=theme.TEXT,
                        fieldbackground=theme.FIELD, bordercolor=theme.LINE,
                        lightcolor=theme.PANEL, darkcolor=theme.PANEL,
                        focuscolor=theme.HILITE, font=self.f_body)

        # Buttons: flat, hairline border, lift a step on hover.
        style.configure("TButton", background=theme.FIELD, foreground=theme.TEXT,
                        bordercolor=theme.LINE, relief="flat", padding=(pad, pad // 2),
                        lightcolor=theme.FIELD, darkcolor=theme.FIELD)
        style.map("TButton",
                  background=[("pressed", theme.LINE), ("active", theme.LINE)],
                  bordercolor=[("active", theme.MUTE)],
                  foreground=[("disabled", theme.MUTE)])

        style.configure("Nudge.TButton", padding=(0, 0), font=self.f_num)

        # Entries and spinboxes: recessed field, highlight border on focus.
        for name in ("TEntry", "TSpinbox"):
            style.configure(name, fieldbackground=theme.FIELD, foreground=theme.TEXT,
                            bordercolor=theme.LINE, insertcolor=theme.HILITE,
                            lightcolor=theme.FIELD, darkcolor=theme.FIELD,
                            arrowcolor=theme.MUTE, padding=(pad // 2, pad // 2))
            style.map(name,
                      bordercolor=[("focus", theme.HILITE)],
                      arrowcolor=[("active", theme.TEXT)],
                      lightcolor=[("focus", theme.FIELD)])

        style.configure("TCombobox", fieldbackground=theme.FIELD, foreground=theme.TEXT,
                        bordercolor=theme.LINE, arrowcolor=theme.MUTE,
                        lightcolor=theme.FIELD, darkcolor=theme.FIELD,
                        padding=(pad // 2, pad // 2))
        style.map("TCombobox",
                  fieldbackground=[("readonly", theme.FIELD)],
                  foreground=[("readonly", theme.TEXT)],
                  selectbackground=[("readonly", theme.FIELD)],
                  selectforeground=[("readonly", theme.TEXT)],
                  bordercolor=[("focus", theme.HILITE), ("active", theme.MUTE)],
                  arrowcolor=[("active", theme.TEXT)])

        # Scales: thin dark trough, pale grip, brighter grip while dragging.
        style.configure("Horizontal.TScale", background=theme.PANEL,
                        troughcolor=theme.FIELD, bordercolor=theme.LINE,
                        lightcolor=theme.MUTE, darkcolor=theme.MUTE)
        style.map("Horizontal.TScale",
                  lightcolor=[("active", theme.HILITE)],
                  darkcolor=[("active", theme.HILITE)])

        for name in ("TCheckbutton", "TRadiobutton"):
            style.configure(name, background=theme.PANEL, foreground=theme.TEXT,
                            indicatorbackground=theme.FIELD,
                            indicatorforeground=theme.ONHILITE,
                            bordercolor=theme.LINE, focuscolor=theme.PANEL,
                            lightcolor=theme.FIELD, darkcolor=theme.FIELD)
            style.map(name,
                      indicatorbackground=[("selected", theme.HILITE),
                                           ("active", theme.LINE)],
                      foreground=[("disabled", theme.MUTE)],
                      background=[("active", theme.PANEL)])

        # Scrollbar: no arrows, thumb is just a lighter step of the ramp.
        style.configure("Panel.Vertical.TScrollbar",
                        background=theme.LINE, troughcolor=theme.INK, bordercolor=theme.INK,
                        arrowcolor=theme.INK, relief="flat", borderwidth=0,
                        lightcolor=theme.LINE, darkcolor=theme.LINE, width=int(10 * self.scale))
        style.map("Panel.Vertical.TScrollbar",
                  background=[("active", theme.MUTE), ("pressed", theme.MUTE)])
        try:
            style.layout("Panel.Vertical.TScrollbar", [
                ("Vertical.Scrollbar.trough", {"children": [
                    ("Vertical.Scrollbar.thumb",
                     {"expand": "1", "sticky": "nswe"})
                ], "sticky": "ns"})
            ])
        except tk.TclError:
            pass

    def style_dropdown_lists(self):
        """Combobox popup lists are plain Tk listboxes, styled separately.

        option_add only reaches widgets created afterwards, so live theme
        changes have to reconfigure each existing popup by hand.
        """
        self.root.option_add("*TCombobox*Listbox.background", theme.FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", theme.TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", theme.HILITE)
        self.root.option_add("*TCombobox*Listbox.selectForeground", theme.ONHILITE)
        self.root.option_add("*TCombobox*Listbox.borderWidth", 0)
        self.root.option_add("*TCombobox*Listbox.font", self.f_body)
        for combo in list(self._combos):
            try:
                popdown = combo.tk.eval(
                    "ttk::combobox::PopdownWindow %s" % combo
                )
                combo.tk.call("%s.f.l" % popdown, "configure",
                              "-background", theme.FIELD, "-foreground", theme.TEXT,
                              "-selectbackground", theme.HILITE,
                              "-selectforeground", theme.ONHILITE)
            except tk.TclError:
                pass

    def register_combo(self, combo):
        """Track comboboxes so their popup lists can be re-themed later."""
        self._combos.append(combo)
        return combo

    def card(self, parent, heading=None, grow=False):
        """A titled section. Cards sit on the darker shell with a hairline.

        `grow` marks the one card that absorbs spare vertical space, so extra
        height goes somewhere useful instead of leaving a dead gap.
        """
        holder = ttk.Frame(parent, style="Card.TFrame")
        holder.pack(fill="both" if grow else "x", expand=grow)
        ttk.Separator(parent, orient="horizontal").pack(fill="x")
        inner = ttk.Frame(holder, style="Card.TFrame")
        inner.pack(fill="both" if grow else "x", expand=grow,
                   padx=self.px(14), pady=self.px(11))
        if heading:
            ttk.Label(inner, text=heading, style="Head.TLabel").pack(
                anchor="w", pady=(0, self.px(8))
            )
        return inner

    def wrapping(self, label, reserve=0):
        """Register a label whose wraplength must track the window width.

        `reserve` is space taken by a sibling on the same row, such as the
        Quit button beside the shortcut list.
        """
        self._wrap_labels.append((label, reserve))
        return label

    def rewrap(self):
        width = self.root.winfo_width()
        if width <= 1:
            return
        for label, reserve in self._wrap_labels:
            try:
                label.configure(
                    wraplength=max(self.px(110), width - self.px(34) - reserve)
                )
            except tk.TclError:
                pass

    def value_row(self, parent, label, var, lo, hi, fine, unit):
        """Label, slider, numeric field, and -/+ nudge buttons.

        All four affordances matter: the slider for coarse sweeps, the field
        for typing an exact figure read off a map, and the buttons for single
        steps without hunting for a keyboard shortcut.
        """
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=self.px(3))

        parts = {
            "label": ttk.Label(row, text=label, style="TLabel", anchor="w"),
            "scale": ttk.Scale(row, from_=lo, to=hi, orient="horizontal",
                               variable=var, style="Horizontal.TScale"),
            "entry": ttk.Entry(row, textvariable=var, font=self.f_num,
                               width=6, justify="right"),
            "unit": ttk.Label(row, text=unit, style="Hint.TLabel", width=2),
            "minus": ttk.Button(row, text="\u2212", width=2,
                                style="Nudge.TButton",
                                command=lambda: self.nudge(var, -fine)),
            "plus": ttk.Button(row, text="+", width=2, style="Nudge.TButton",
                               command=lambda: self.nudge(var, fine)),
        }
        self._value_rows.append((row, parts))
        return row

    def _grid_value_row(self, row, parts, narrow):
        """Place one value row, in wide (single line) or narrow (two) form."""
        for widget in parts.values():
            widget.grid_forget()

        gap = self.px(4)
        if narrow:
            # label ............ [field][unit]
            # [-------slider-------][-][+]
            row.columnconfigure(0, weight=1)
            row.columnconfigure(1, weight=0)
            parts["label"].configure(width=0)
            parts["label"].grid(row=0, column=0, sticky="w")
            parts["entry"].grid(row=0, column=1, sticky="e")
            parts["unit"].grid(row=0, column=2, sticky="w", padx=(gap // 2, 0))
            parts["scale"].grid(row=1, column=0, sticky="we",
                                pady=(self.px(3), 0), padx=(0, gap))
            parts["minus"].grid(row=1, column=1, sticky="e",
                                pady=(self.px(3), 0))
            parts["plus"].grid(row=1, column=2, sticky="w",
                               pady=(self.px(3), 0), padx=(gap // 2, 0))
        else:
            # label [------slider------] [field][unit][-][+]
            row.columnconfigure(0, weight=0)
            row.columnconfigure(1, weight=1)
            parts["label"].configure(width=9)
            parts["label"].grid(row=0, column=0, sticky="w")
            parts["scale"].grid(row=0, column=1, sticky="we",
                                padx=(self.px(6), self.px(9)))
            parts["entry"].grid(row=0, column=2, sticky="e")
            parts["unit"].grid(row=0, column=3, sticky="w",
                               padx=(self.px(3), self.px(5)))
            parts["minus"].grid(row=0, column=4)
            parts["plus"].grid(row=0, column=5, padx=(self.px(2), 0))

    def apply_layout_mode(self, force=False):
        """Switch value rows between the wide and narrow arrangements."""
        narrow = self.root.winfo_width() < self.px(self.NARROW_AT)
        if narrow == self._narrow and not force:
            return
        self._narrow = narrow
        for row, parts in self._value_rows:
            self._grid_value_row(row, parts, narrow)

    def _swatch_metrics(self):
        """Geometry of the swatch strip: current colour, divider, then presets."""
        box = self.px(18)
        big = self.px(26)
        gap = self.px(5)
        divider = big + self.px(7)
        start = big + self.px(15)
        return box, big, gap, divider, start

    def swatch_strip(self, parent, variable, picker):
        """A colour-in-use swatch, a divider, then the presets.

        Registered rather than hard-wired, so the grid colour and the band
        colour share one implementation and both follow a theme change.
        """
        canvas = tk.Canvas(parent, height=self.px(20), bg=theme.PANEL,
                           highlightthickness=0, bd=0, takefocus=0,
                           cursor="hand2")
        strip = {"canvas": canvas, "var": variable, "picker": picker}
        self._swatch_strips.append(strip)
        canvas.bind("<Button-1>", lambda e, s=strip: self._swatch_click(e, s))
        canvas.bind("<Configure>", lambda e: self.paint_swatches())
        return canvas

    def paint_swatches(self):
        for strip in self._swatch_strips:
            self._paint_swatch_strip(strip)

    def _paint_swatch_strip(self, strip):
        c = strip["canvas"]
        c.delete("all")
        width = c.winfo_width()
        current = str(strip["var"].get())
        box, big, gap, divider, start = self._swatch_metrics()

        # The colour in use, kept apart from the presets. A colour chosen from
        # the picker matches no preset, so without its own swatch there was
        # nowhere on this screen showing what the grid is actually drawn in.
        c.create_rectangle(
            0, 0, big, box,
            fill=current if HEX_RE.match(current) else "#808080",
            outline=theme.HILITE, width=2,
        )
        c.create_line(divider, 0, divider, box, fill=theme.LINE)

        for index, colour in enumerate(theme.GRID_PRESETS):
            x = start + index * (box + gap)
            if width > 1 and x + box > width:
                break                            # no half-drawn swatches
            active = colour.upper() == current.upper()
            c.create_rectangle(
                x, 0, x + box, box, fill=colour,
                outline=theme.HILITE if active else theme.LINE,
                width=2 if active else 1,
            )

    def _swatch_click(self, event, strip):
        box, big, gap, _divider, start = self._swatch_metrics()
        if event.x <= big and event.y <= box:
            strip["picker"]()                    # the current swatch opens the picker
            return
        index = int((event.x - start) / float(box + gap))
        if 0 <= index < len(theme.GRID_PRESETS) and event.y <= box:
            left = start + index * (box + gap)
            if left <= event.x <= left + box:    # ignore clicks in the gaps
                strip["var"].set(theme.GRID_PRESETS[index])
