"""The settings window: the shell that holds the tabs."""

import tkinter as tk

from tkinter import ttk

from ...core import theme
from ...core.theme import blend
from ...core.win32 import set_frame_mode
from .bands import BandsTab
from .conditions import ConditionsTab
from .general import GeneralTab
from .hotkeys import HotkeysTab
from .theme import ThemeTab


class SettingsWindow:
    """Tabbed settings: startup behaviour, hotkeys, bands, conditions, themes.

    Each tab commits on its own terms rather than behind one global Apply.
    Startup options and themes take effect the moment they are changed, since
    both are instantly reversible and a theme is its own preview. Hotkeys, bands
    and conditions need an explicit Apply, because each can be refused: a combo
    another program already owns, a row with no distance, a colour that is not a
    colour. Those outcomes have to be reported per row.

    The window owns only the frame, the tab strip and the sizing. Each tab is a
    class of its own in this folder.
    """

    def __init__(self, app):
        self.app = app

        self.win = tk.Toplevel(app.root)
        # Hidden until it has been built and positioned. Tk maps a new window at
        # the default spot immediately, so moving it afterwards makes it flash in
        # the corner of the screen first.
        self.win.withdraw()
        self.win.title("Settings")
        self.win.configure(bg=theme.INK)
        self.win.transient(app.root)
        self.win.resizable(True, True)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self.general = GeneralTab(self)
        self.hotkeys = HotkeysTab(self)
        self.bands = BandsTab(self)
        self.conditions = ConditionsTab(self)
        self.theme_tab = ThemeTab(self)

        self._build()
        self.hotkeys.load(app.hotkeys)

        self.win.update_idletasks()
        self.win.minsize(self.win.winfo_reqwidth(), self.win.winfo_reqheight())
        self._centre_on_parent()
        set_frame_mode(self.win)
        self.win.deiconify()
        self.win.focus_set()

    # -- shell -------------------------------------------------------------

    def _build(self):
        pad = self.app.ui.px

        outer = ttk.Frame(self.win, style="Shell.TFrame")
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer, style="Shell.TFrame")
        head.pack(fill="x", padx=pad(14), pady=pad(12))
        ttk.Label(head, text="Settings", style="App.TLabel").pack(side="left")

        self._build_tab_strip(outer)
        self._add_page("General", self.general.build())
        self._add_page("Hotkeys", self.hotkeys.build())
        self._add_page("Bands", self.bands.build())
        self._add_page("Conditions", self.conditions.build())
        self._add_page("Theme", self.theme_tab.build())
        self._select_page(0)
        self._lock_tab_size()

        ttk.Separator(outer, orient="horizontal").pack(fill="x",
                                                       pady=(pad(10), 0))
        foot = ttk.Frame(outer, style="Shell.TFrame")
        foot.pack(fill="x", padx=pad(14), pady=pad(10))
        ttk.Button(foot, text="Close", command=self.close).pack(side="right")
        ttk.Label(foot, text="Changes are saved as you make them.",
                  style="Shell.TLabel").pack(side="left")

    def _build_tab_strip(self, outer):
        """A hand-built tab strip.

        Under clam, ttk's notebook draws the *selected* tab smaller than its
        neighbours, and neither the expand nor the padding style map reliably
        overrides that. Building the strip directly costs a few more lines and
        gives exact control, so the active tab can genuinely be the largest.
        """
        px = self.app.ui.px
        self.tab_bar = tk.Frame(outer, bg=theme.INK)
        self.tab_bar.pack(fill="x", padx=px(10))
        self.tab_body = tk.Frame(outer, bg=theme.PANEL)
        self.tab_body.pack(fill="both", expand=True, padx=px(10))
        self.tab_items = []
        self.tab_pages = []
        self.active_tab = 0

    def _add_page(self, title, page):
        px = self.app.ui.px
        index = len(self.tab_items)
        holder = tk.Frame(self.tab_bar, bg=theme.INK)
        holder.pack(side="left", padx=(0, px(3)))
        accent = tk.Frame(holder, height=px(2), bg=theme.INK)
        accent.pack(fill="x")
        label = tk.Label(holder, text=title, font=self.app.ui.f_body,
                         bg=theme.INK, fg=theme.MUTE, cursor="hand2")
        label.pack(fill="both", expand=True)
        for widget in (holder, accent, label):
            widget.bind("<Button-1>", lambda e, i=index: self._select_page(i))
        self.tab_items.append({"holder": holder, "accent": accent,
                               "label": label})
        self.tab_pages.append(page)

    def _select_page(self, index):
        self.active_tab = index
        for page in self.tab_pages:
            page.pack_forget()
        self.tab_pages[index].pack(fill="both", expand=True)
        self._restyle_tabs()

    def _restyle_tabs(self):
        """The selected tab is taller, brighter, and fused with the panel."""
        px = self.app.ui.px
        # Derived from the panel so it stays distinct in every theme, including
        # Classic, where the chassis and panel colours are identical.
        resting = blend(theme.PANEL, theme.LINE, 0.5)
        for index, item in enumerate(self.tab_items):
            active = index == self.active_tab
            background = theme.PANEL if active else resting
            item["holder"].configure(bg=background)
            item["accent"].configure(bg=theme.HILITE if active else resting,
                                     height=px(3) if active else px(2))
            item["label"].configure(
                bg=background, fg=theme.TEXT if active else theme.MUTE,
                padx=px(18) if active else px(14),
                pady=px(9) if active else px(5),
            )
        self.tab_bar.configure(bg=theme.INK)
        self.tab_body.configure(bg=theme.PANEL)

    def _lock_tab_size(self):
        """Freeze the page area to the largest page.

        Each tab needs a different amount of room, so without this the window
        jumps size every time you switch - which is disorienting and moves the
        buttons out from under the pointer. Measuring each page and holding the
        container at the maximum keeps the window still.
        """
        heights, widths = [], []
        for page in self.tab_pages:
            page.pack(fill="both", expand=True)
            self.win.update_idletasks()
            heights.append(page.winfo_reqheight())
            widths.append(page.winfo_reqwidth())
            page.pack_forget()
        if heights:
            self.tab_body.configure(width=max(widths), height=max(heights))
            self.tab_body.pack_propagate(False)
        self._select_page(self.active_tab)

    def _tab(self):
        holder = ttk.Frame(self.tab_body, style="Card.TFrame")
        inner = ttk.Frame(holder, style="Card.TFrame")
        inner.pack(fill="both", expand=True,
                   padx=self.app.ui.px(14), pady=self.app.ui.px(13))
        return holder, inner

    def _note(self, parent, text, pady=(0, 0)):
        label = ttk.Label(parent, text=text, style="Hint.TLabel",
                          justify="left", wraplength=self.app.ui.px(430))
        label.pack(anchor="w", fill="x", pady=pady)
        return label

    def restyle(self):
        """Follow a live theme change."""
        try:
            self.win.configure(bg=theme.INK)
            self._restyle_tabs()
            self.theme_tab.restyle()
            # Condition swatches hold their own colours, so the editor redraws
            # them rather than trying to recolour each canvas in place.
            if self.conditions.editor is not None:
                self.conditions.editor.rebuild()
            set_frame_mode(self.win)
        except tk.TclError:
            pass

    def _centre_on_parent(self):
        # winfo_width is 1 until a window is mapped, so the requested size is
        # what to centre against while it is still hidden.
        try:
            parent = self.app.root
            width = max(self.win.winfo_reqwidth(), self.win.winfo_width())
            x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
            y = parent.winfo_rooty() + self.app.ui.px(40)
            self.win.geometry("+%d+%d" % (max(0, x), max(0, y)))
        except tk.TclError:
            pass

    def close(self):
        self.app.settings_window = None
        self.win.destroy()
