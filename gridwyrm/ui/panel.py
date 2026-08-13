"""Building the control panel, and keeping it a usable size."""

import tkinter as tk

from tkinter import ttk

from ..core import theme
from ..core.bands import RANGE_MODES
from ..core.win32 import IS_WINDOWS
from ..core.geometry import PANEL_GEOMETRY_RE
from ..core.measuring import DIAGONAL_RULES, UNIT_CHOICES

class Panel:
    """Building the control panel, and keeping it a usable size.
    The panel can be dragged to any size at all: below a certain
    width the value rows fold onto two lines, and when it is shorter
    than its contents a scrollbar appears. The header and footer stay
    put outside the scrolling region so the status lamp and the Quit
    button are always reachable.
    
    Widgets are assigned onto the application rather than held here,
    because the features that drive them already reach through it.
    What moved out of App is the four hundred lines of construction.

    Given the application, which is where the shared state and the overlay
    live. Nothing here reaches into another feature.
    """

    def __init__(self, app):
        self.app = app


    def _build_ui(self, saved_screen):
        outer = ttk.Frame(self.app.root, style="Shell.TFrame")
        outer.pack(fill="both", expand=True)

        # header: stays put, never scrolls -------------------------------
        head = ttk.Frame(outer, style="Shell.TFrame")
        head.pack(fill="x", padx=self.app.ui.px(14), pady=self.app.ui.px(12))
        ttk.Label(head, text="Gridwyrm", style="App.TLabel").pack(side="left")
        self.app.lamp = tk.Canvas(head, width=self.app.ui.px(8), height=self.app.ui.px(8),
                              bg=theme.INK, highlightthickness=0, bd=0)
        self.app.lamp.pack(side="right", padx=(self.app.ui.px(6), 0))
        ttk.Label(head, textvariable=self.app.status, style="Status.TLabel").pack(
            side="right"
        )
        ttk.Separator(outer, orient="horizontal").pack(fill="x")

        # scrolling middle -----------------------------------------------
        shell = self._build_scroll_area(outer)

        # actual-size preview: the signature element ---------------------
        preview_card = self.app.ui.card(shell, "PREVIEW  (ACTUAL SIZE)", grow=True)
        self.app.preview = tk.Canvas(preview_card, height=self.app.ui.px(98), bg=theme.INK,
                                 highlightthickness=1, highlightbackground=theme.LINE,
                                 bd=0, takefocus=0)
        self.app.preview.pack(fill="both", expand=True)
        # A bigger window shows more grid, so repaint on every resize.
        self.app.preview.bind("<Configure>", lambda e: self.app.schedule_draw())
        self.app.ui.wrapping(ttk.Label(
            preview_card,
            text="The grid at actual size over a sample map, so you can judge "
                 "the colour against grass, stone and timber rather than "
                 "against a flat swatch. Drag the window bigger to see more.",
            style="Hint.TLabel", justify="left",
        )).pack(anchor="w", fill="x", pady=(self.app.ui.px(5), 0))

        backdrop = ttk.Frame(preview_card, style="Card.TFrame")
        backdrop.pack(fill="x", pady=(self.app.ui.px(7), 0))
        ttk.Button(backdrop, text="Use my map\u2026",
                   command=self.app.preview_painter.choose_preview_image).pack(side="left")
        ttk.Button(backdrop, text="Sample",
                   command=self.app.preview_painter.clear_preview_image).pack(side="left",
                                                          padx=(self.app.ui.px(6), 0))
        ttk.Label(backdrop, textvariable=self.app.backdrop_label,
                  style="Hint.TLabel").pack(side="left",
                                            padx=(self.app.ui.px(8), 0))

        # screen ---------------------------------------------------------
        screen = self.app.ui.card(shell, "SCREEN")
        self.app.screen_labels = [
            f"Monitor {i + 1}  \u2014  {w}\u00d7{h} at {x:+d}{y:+d}"
            for i, (x, y, w, h) in enumerate(self.app.monitors)
        ]
        self.app.screen_labels.append("Custom region\u2026")
        self.app.screen_choice.set(
            saved_screen if saved_screen in self.app.screen_labels
            else self.app.screen_labels[0]
        )
        self.app.screen_box = self.app.ui.register_combo(ttk.Combobox(
            screen, values=self.app.screen_labels, textvariable=self.app.screen_choice,
            state="readonly",
        ))
        self.app.screen_box.pack(fill="x")
        self.app.screen_box.bind("<<ComboboxSelected>>", lambda *_: self.app.apply_screen())

        region_row = ttk.Frame(screen, style="Card.TFrame")
        region_row.pack(fill="x", pady=(self.app.ui.px(7), 0))
        self.app.region_entry = ttk.Entry(region_row, textvariable=self.app.region,
                                      font=self.app.ui.f_num)
        self.app.region_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(region_row, text="Apply", command=self.app.apply_screen).pack(
            side="left", padx=(self.app.ui.px(6), 0)
        )
        ttk.Label(screen, text="width \u00d7 height + x + y",
                  style="Hint.TLabel").pack(anchor="w", pady=(self.app.ui.px(4), 0))

        # grid -----------------------------------------------------------
        grid_card = self.app.ui.card(shell, "GRID")
        self.app.ui.register_combo(ttk.Combobox(
            grid_card, values=self.app.GRID_TYPES, textvariable=self.app.grid_type,
            state="readonly")).pack(fill="x")

        # alignment ------------------------------------------------------
        align = self.app.ui.card(shell, "ALIGNMENT")
        self.app.ui.value_row(align, "Cell size", self.app.cell, 8, 400, 0.5, "px")
        self.app.ui.value_row(align, "Offset X", self.app.off_x, -400, 400, 0.5, "px")
        self.app.ui.value_row(align, "Offset Y", self.app.off_y, -400, 400, 0.5, "px")

        # scale ----------------------------------------------------------
        scale_card = self.app.ui.card(shell, "SCALE")

        per_row = ttk.Frame(scale_card, style="Card.TFrame")
        per_row.pack(fill="x")
        ttk.Label(per_row, text="1 square =", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        ttk.Entry(per_row, textvariable=self.app.per_square, font=self.app.ui.f_num,
                  width=6, justify="right").pack(side="left",
                                                 padx=(self.app.ui.px(6), 0))
        self.app.ui.register_combo(ttk.Combobox(
            per_row, values=list(UNIT_CHOICES), textvariable=self.app.unit,
            state="readonly", width=8)).pack(side="left",
                                             padx=(self.app.ui.px(6), 0))

        diag_row = ttk.Frame(scale_card, style="Card.TFrame")
        diag_row.pack(fill="x", pady=(self.app.ui.px(6), 0))
        ttk.Label(diag_row, text="Diagonals", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        self.app.ui.register_combo(ttk.Combobox(
            diag_row, values=list(DIAGONAL_RULES),
            textvariable=self.app.diagonal_rule, state="readonly")).pack(
            side="left", fill="x", expand=True, padx=(self.app.ui.px(6), 0))

        measure_row = ttk.Frame(scale_card, style="Card.TFrame")
        measure_row.pack(fill="x", pady=(self.app.ui.px(8), 0))
        self.app.measure_button = ttk.Button(measure_row, text="Measure\u2026",
                                        command=self.app.measure_feature.toggle_measure)
        self.app.measure_button.pack(side="left")
        self.app.ui.wrapping(ttk.Label(
            measure_row, textvariable=self.app.measure_readout, style="Hint.TLabel",
            justify="left",
        ), reserve=self.app.ui.px(96)).pack(side="left", fill="x", expand=True,
                                      padx=(self.app.ui.px(8), 0))

        # Only shown once a span has been measured.
        self.app.span_row = ttk.Frame(scale_card, style="Card.TFrame")
        ttk.Label(self.app.span_row, text="That span was", style="TLabel").pack(
            side="left")
        ttk.Entry(self.app.span_row, textvariable=self.app.span_squares,
                  font=self.app.ui.f_num, width=5, justify="right").pack(
            side="left", padx=(self.app.ui.px(6), self.app.ui.px(6)))
        ttk.Label(self.app.span_row, text="squares", style="TLabel").pack(
            side="left")
        ttk.Button(self.app.span_row, text="Set cell size",
                   command=self.app.measure_feature.apply_span_as_cell_size).pack(
            side="right")

        self.app.ui.wrapping(ttk.Label(
            scale_card,
            text="Click two points on the map, then say how many squares they "
                 "were apart. Hold Shift while measuring to lock the line to "
                 "horizontal or vertical, which is worth doing when setting the "
                 "cell size. The screen dims while measuring, because the "
                 "overlay has to hold the mouse; right-click to cancel.",
            style="Hint.TLabel", justify="left",
        )).pack(anchor="w", fill="x", pady=(self.app.ui.px(6), 0))

        # range bands ----------------------------------------------------
        range_card = self.app.ui.card(shell, "RANGE BANDS")

        mode_row = ttk.Frame(range_card, style="Card.TFrame")
        mode_row.pack(fill="x")
        ttk.Label(mode_row, text="Show", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        self.app.ui.register_combo(ttk.Combobox(
            mode_row, values=list(RANGE_MODES), textvariable=self.app.range_mode,
            state="readonly")).pack(side="left", fill="x", expand=True,
                                    padx=(self.app.ui.px(6), 0))

        band_colour_row = ttk.Frame(range_card, style="Card.TFrame")
        band_colour_row.pack(fill="x", pady=(self.app.ui.px(8), 0))
        ttk.Label(band_colour_row, text="Colour", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        ttk.Button(band_colour_row, text="Pick\u2026",
                   command=self.app.ranges_feature.pick_band_colour).pack(side="right")
        self.app.ui.swatch_strip(band_colour_row, self.app.band_colour,
                              self.app.ranges_feature.pick_band_colour).pack(
            side="left", fill="x", expand=True,
            padx=(self.app.ui.px(6), self.app.ui.px(6)))

        band_buttons = ttk.Frame(range_card, style="Card.TFrame")
        band_buttons.pack(fill="x", pady=(self.app.ui.px(8), 0))
        self.app.range_button = ttk.Button(band_buttons, text="Place bands\u2026",
                                      command=self.app.ranges_feature.toggle_place_ranges)
        self.app.range_button.pack(side="left")
        ttk.Button(band_buttons, text="Clear",
                   command=self.app.ranges_feature.clear_ranges).pack(side="left",
                                                   padx=(self.app.ui.px(6), 0))
        # The hotkey can be refused by Windows if another program owns the
        # combination, so revealing is reachable from the panel too.
        reveal = ttk.Button(band_buttons, text="Reveal")
        reveal.pack(side="left", padx=(self.app.ui.px(6), 0))
        reveal.bind("<ButtonPress-1>", lambda e: self.app.ranges_feature.hold_reveal(True))
        reveal.bind("<ButtonRelease-1>", lambda e: self.app.ranges_feature.hold_reveal(False))
        self.app.ui.wrapping(ttk.Label(
            band_buttons, textvariable=self.app.range_readout, style="Hint.TLabel",
            justify="left",
        ), reserve=self.app.ui.px(150)).pack(side="left", fill="x", expand=True,
                                      padx=(self.app.ui.px(8), 0))

        self.app.ui.wrapping(ttk.Label(
            range_card, textvariable=self.app.band_summary, style="TLabel",
            justify="left",
        )).pack(anchor="w", fill="x", pady=(self.app.ui.px(8), 0))

        self.app.ui.wrapping(ttk.Label(
            range_card,
            text="Click a creature and thin rings appear around it, unlabelled. "
                 "The distances are listed above, for you. Hold the reveal key "
                 "and the rings thicken and take names, for the table. Rings "
                 "scale with the cell size, and any that would be wider than "
                 "the screen are left out. Edit the bands under Settings.",
            style="Hint.TLabel", justify="left",
        )).pack(anchor="w", fill="x", pady=(self.app.ui.px(6), 0))

        # conditions -----------------------------------------------------
        cond_card = self.app.ui.card(shell, "CONDITIONS")

        pick_row = ttk.Frame(cond_card, style="Card.TFrame")
        pick_row.pack(fill="x")
        ttk.Label(pick_row, text="Mark as", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        self.app.condition_box = self.app.ui.register_combo(ttk.Combobox(
            pick_row, values=[name for name, _c in self.app.conditions],
            textvariable=self.app.condition_choice, state="readonly"))
        self.app.condition_box.pack(side="left", fill="x", expand=True,
                                padx=(self.app.ui.px(6), 0))

        self.app.ui.value_row(cond_card, "Size", self.app.marker_size, 20, 250, 5, "%")

        cond_buttons = ttk.Frame(cond_card, style="Card.TFrame")
        cond_buttons.pack(fill="x", pady=(self.app.ui.px(8), 0))
        self.app.condition_button = ttk.Button(cond_buttons, text="Mark\u2026",
                                         command=self.app.markers_feature.toggle_place_condition)
        self.app.condition_button.pack(side="left")
        ttk.Button(cond_buttons, text="Undo",
                   command=self.app.markers_feature.undo_condition).pack(side="left",
                                                     padx=(self.app.ui.px(6), 0))
        ttk.Button(cond_buttons, text="Clear all",
                   command=self.app.markers_feature.clear_conditions).pack(side="left",
                                                       padx=(self.app.ui.px(6), 0))

        self.app.ui.wrapping(ttk.Label(
            cond_card,
            text="A coloured ring on a creature saying what is happening to it. "
                 "Keep clicking to mark a whole group, then right-click when "
                 "done. Size is a share of one square, so rings stay "
                 "proportionate, and they hold their place on the grid if you "
                 "rescale or nudge it. Edit the list under Settings.",
            style="Hint.TLabel", justify="left",
        )).pack(anchor="w", fill="x", pady=(self.app.ui.px(6), 0))

        # lines ----------------------------------------------------------
        lines = self.app.ui.card(shell, "LINES")
        swatch_row = ttk.Frame(lines, style="Card.TFrame")
        swatch_row.pack(fill="x", pady=(0, self.app.ui.px(8)))
        ttk.Label(swatch_row, text="Colour", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        ttk.Button(swatch_row, text="Pick\u2026",
                   command=self.app.pick_colour).pack(side="right")
        self.app.ui.swatch_strip(swatch_row, self.app.colour, self.app.pick_colour).pack(
            side="left", fill="x", expand=True,
            padx=(self.app.ui.px(6), self.app.ui.px(6)))
        ttk.Label(lines, text="First swatch is the colour in use \u2014 click it "
                              "to change. The rest are presets.",
                  style="Hint.TLabel").pack(anchor="w", pady=(self.app.ui.px(4), 0))

        weight_row = ttk.Frame(lines, style="Card.TFrame")
        weight_row.pack(fill="x", pady=self.app.ui.px(3))
        ttk.Label(weight_row, text="Weight", style="TLabel", width=9,
                  anchor="w").pack(side="left")
        ttk.Spinbox(weight_row, from_=1, to=8, textvariable=self.app.line_w,
                    width=4, font=self.app.ui.f_num).pack(side="left")
        ttk.Label(weight_row, text="px", style="Hint.TLabel").pack(
            side="left", padx=(self.app.ui.px(4), 0)
        )
        self.app.ui.value_row(lines, "Opacity", self.app.opacity, 10, 100, 1, "%")

        # switches -------------------------------------------------------
        switches = self.app.ui.card(shell)
        ttk.Checkbutton(switches, text="Show overlay", variable=self.app.visible,
                        command=self.app.apply_visibility).pack(anchor="w")
        self.app.pass_check = ttk.Checkbutton(
            switches, text="Let clicks pass through to the map underneath",
            variable=self.app.click_through, command=self.app.apply_click_through,
        )
        self.app.pass_check.pack(anchor="w", pady=(self.app.ui.px(4), 0))
        if not IS_WINDOWS:
            self.app.pass_check.state(["disabled"])
            self.app.ui.wrapping(ttk.Label(
                switches,
                text="Click-through and full transparency need Windows. "
                     "Elsewhere the overlay shows as a faint tint.",
                style="Hint.TLabel", justify="left",
            )).pack(anchor="w", fill="x", pady=(self.app.ui.px(4), 0))

        # footer: stays put, never scrolls -------------------------------
        ttk.Separator(outer, orient="horizontal").pack(fill="x")

        # Only packed when there is actually something to say, so it costs no
        # space and never nags.
        self.app.update_row = ttk.Frame(outer, style="Shell.TFrame")
        ttk.Button(self.app.update_row, textvariable=self.app.update_action,
                   command=self.app.updater.update_button_pressed).pack(side="right")
        ttk.Button(self.app.update_row, text="Later",
                   command=self.app.updater.dismiss_update).pack(side="right",
                                                     padx=(0, self.app.ui.px(6)))
        self.app.ui.wrapping(ttk.Label(
            self.app.update_row, textvariable=self.app.update_notice,
            style="Shell.TLabel", justify="left",
        ), reserve=self.app.ui.px(120)).pack(side="left", fill="x", expand=True,
                                       pady=(self.app.ui.px(8), 0))

        foot = ttk.Frame(outer, style="Shell.TFrame")
        foot.pack(fill="x", padx=self.app.ui.px(14), pady=self.app.ui.px(10))
        ttk.Button(foot, text="Quit", command=self.app.quit).pack(side="right")
        ttk.Button(foot, text="Settings\u2026",
                   command=self.app.open_settings).pack(side="right",
                                                    padx=(0, self.app.ui.px(6)))
        hints = ttk.Frame(foot, style="Shell.TFrame")
        hints.pack(side="left", fill="x", expand=True)
        self.app.ui.wrapping(ttk.Label(
            hints,
            text="Arrows nudge  \u00b7  Shift+arrows \u00d710  \u00b7  "
                 "+ / \u2212 cell size  \u00b7  [ ] fine",
            style="Shell.TLabel", justify="left",
        ), reserve=self.app.ui.px(160)).pack(anchor="w", fill="x")
        self.app.ui.wrapping(ttk.Label(
            hints, textvariable=self.app.hotkey_hint, style="Shell.TLabel",
            justify="left",
        ), reserve=self.app.ui.px(160)).pack(anchor="w", fill="x",
                                       pady=(self.app.ui.px(3), 0))

        self.app._paint_lamp()
        self.app.preview_painter._update_backdrop_label()
        self.app.ranges_feature._refresh_band_summary()

    def _build_scroll_area(self, parent):
        """A scrolling viewport that only shows its bar when needed."""
        wrap = ttk.Frame(parent, style="Shell.TFrame")
        wrap.pack(fill="both", expand=True)

        self.app.viewport = tk.Canvas(wrap, bg=theme.INK, highlightthickness=0, bd=0,
                                  takefocus=0)
        self.app.viewport.pack(side="left", fill="both", expand=True)
        self.app.scrollbar = ttk.Scrollbar(
            wrap, orient="vertical", command=self.app.viewport.yview,
            style="Panel.Vertical.TScrollbar",
        )
        self.app.viewport.configure(yscrollcommand=self._on_scroll_set)

        body = ttk.Frame(self.app.viewport, style="Shell.TFrame")
        self.app.body_id = self.app.viewport.create_window((0, 0), window=body,
                                                   anchor="nw")
        self.app.body = body
        body.bind("<Configure>", lambda e: self._sync_scroll())
        self.app.viewport.bind("<Configure>", lambda e: self._sync_scroll())
        return body

    def _on_scroll_set(self, first, last):
        """Show the scrollbar only when the content actually overflows."""
        self.app.scrollbar.set(first, last)
        needed = float(first) > 0.0 or float(last) < 1.0
        mapped = bool(self.app.scrollbar.winfo_ismapped())
        if needed and not mapped:
            self.app.scrollbar.pack(side="right", fill="y")
        elif not needed and mapped:
            self.app.scrollbar.pack_forget()

    def _sync_scroll(self):
        """Keep the body as wide as the viewport, and as tall as it needs."""
        view_w = self.app.viewport.winfo_width()
        view_h = self.app.viewport.winfo_height()
        if view_w <= 1:
            return
        natural = self.app.body.winfo_reqheight()
        # Taller viewport than content: stretch, so the preview card grows.
        # Shorter: keep natural height and let the scrollbar handle it.
        height = max(natural, view_h)
        self.app.viewport.itemconfigure(self.app.body_id, width=view_w, height=height)
        self.app.viewport.configure(scrollregion=(0, 0, view_w, height))

    def _wheel_scroll(self, steps):
        if self.app.scrollbar.winfo_ismapped():
            self.app.viewport.yview_scroll(steps, "units")

    def _setup_sizing(self, saved_geometry):
        """Any size at all: a small floor, reflow narrow, scroll when short."""
        self.app.root.update_idletasks()

        # Natural size = what the layout wants before anything is squeezed.
        natural_w = max(self.app.ui.px(self.app.NARROW_AT + 40),
                        self.app.body.winfo_reqwidth() + self.app.ui.px(4))
        self.app.viewport.configure(height=self.app.body.winfo_reqheight())
        self.app.root.update_idletasks()
        natural_h = self.app.root.winfo_reqheight()

        # Then let the viewport shrink freely, or it would set the floor.
        self.app.viewport.configure(height=self.app.ui.px(50), width=self.app.ui.px(50))

        self.app.root.minsize(self.app.ui.px(240), self.app.ui.px(170))

        screen_h = self.app.root.winfo_screenheight()
        natural_h = min(natural_h, max(self.app.ui.px(300), screen_h - self.app.ui.px(90)))

        applied = False
        match = PANEL_GEOMETRY_RE.match(saved_geometry or "")
        if match:
            w, h, x, y = (int(g) for g in match.groups())
            # Only restore a position that still lands on a real screen, so a
            # changed monitor layout cannot strand the panel out of sight.
            on_screen = any(
                mx <= x < mx + mw and my <= y < my + mh
                for mx, my, mw, mh in self.app.monitors
            )
            self.app.root.geometry(f"{w}x{h}{x:+d}{y:+d}" if on_screen else f"{w}x{h}")
            applied = True
        if not applied:
            self.app.root.geometry(f"{natural_w}x{natural_h}")

        self.app.root.bind("<Configure>", self._on_resize)
        self.app.root.bind_all("<MouseWheel>",
                           lambda e: self._wheel_scroll(-1 if e.delta > 0 else 1))
        self.app.root.bind_all("<Button-4>", lambda e: self._wheel_scroll(-1))
        self.app.root.bind_all("<Button-5>", lambda e: self._wheel_scroll(1))

        self.app.ui.apply_layout_mode(force=True)
        self.app.ui.rewrap()

    def _on_resize(self, event):
        if event.widget is not self.app.root:
            return
        self.app.ui.apply_layout_mode()
        self.app.ui.rewrap()
