"""The application: state, wiring, and the control panel."""
# Placed above the imports on purpose. Double-clicking this file cannot
# work: it is part of a package and its imports are relative, so Python
# fails on the first one. Checking here means a person gets an instruction
# rather than a message about relative imports.
if __name__ == "__main__":
    _message = ("Gridwyrm cannot be started from this file.\n\n"
                "Double-click Gridwyrm.pyw in the folder above instead, "
                "or run 'python -m gridwyrm'.")
    try:
        # A console opened by a double-click closes before anyone can read a
        # printed message, so show it in a dialog as well.
        import ctypes as _ctypes
        _ctypes.windll.user32.MessageBoxW(None, _message,
                                          "Gridwyrm", 0x40)
    except Exception:
        pass
    raise SystemExit(_message)

import base64
import os
import sys
import tempfile
import time
import tkinter as tk
import traceback
from tkinter import ttk

from .core import theme
from .ui.panel import Panel
from .ui.pointer import PointerSession
from .features.preview import Preview
from .features.markers import Markers
from .features.measure import Measure
from .features.ranges import Ranges
from .features.updates import Updates
from .ui.styling import Styling
from .core.artwork import ICON_ICO, ICON_PNG_16, ICON_PNG_32, ICON_PNG_64
from .core.bands import DEFAULT_BANDS, RANGE_MODES, format_bands, parse_bands
from .core.conditions import CONDITION_DEFAULTS_VERSION, format_conditions, normalise_conditions
from .core.geometry import parse_geometry, safe_float
from .core.hotkeys import HOTKEY_DEFAULTS_VERSION, HOTKEY_OFF, HotkeyManager, hotkey_text, normalise_hotkeys
from .core.measuring import DIAGONAL_RULES, UNIT_CHOICES
from .core.storage import enable_fault_log, load_settings, log_event, save_settings, settings_path
from .core.theme import HEX_RE, ROLE_KEYS, THEME_ORDER, apply_palette, resolve_theme
from .core.updates import RELEASES_PAGE, VERSION, is_newer
from .core.win32 import IS_WINDOWS, claim_taskbar_identity, hide_own_console, list_monitors, refresh_autostart_path, screen_dpi, set_frame_mode
from .ui.colour_picker import ColourPicker
from .ui.overlay import Overlay
from .ui.settings.window import SettingsWindow


class App:
    GRID_TYPES = ("Square", "Hex (pointy top)", "Hex (flat top)")

    # Below this panel width, value rows stack onto two lines.
    NARROW_AT = 380

    def __init__(self):
        hide_own_console()
        # Before any window exists, or the taskbar groups this under whatever
        # launched it and shows that program's icon.
        claim_taskbar_identity()
        self._fault_log = enable_fault_log()
        log_event("---- start  pid=%s  frozen=%s  python=%s"
                  % (os.getpid(), bool(getattr(sys, "frozen", False)),
                     sys.version.split()[0]))

        self.root = tk.Tk()
        self.root.title("Gridwyrm")
        self.root.configure(bg=theme.INK)
        self.root.resizable(True, True)

        dpi = screen_dpi(self.root)
        self.s = min(2.0, max(1.0, dpi / 96.0))
        self.root.tk.call("tk", "scaling", dpi / 72.0)
        # Appearance lives in Styling. It is handed the nudge callback because
        # the plus and minus buttons on a value row have to change something,
        # and what they change belongs to whoever owns the value.
        self.ui = Styling(self.root, self.s, self.bump)

        self.monitors = list_monitors() or [
            (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        ]
        saved = load_settings()

        # Theme first: everything built afterwards reads these colours.
        self.theme_name = saved.get("theme", "Dark")
        if self.theme_name not in THEME_ORDER:
            self.theme_name = "Dark"
        self.custom_theme = {
            key: value
            for key, value in (saved.get("custom_theme") or {}).items()
            if key in ROLE_KEYS and HEX_RE.match(str(value))
        }
        apply_palette(resolve_theme(self.theme_name, self.custom_theme))
        self.root.configure(bg=theme.INK)
        self.ui._combos = []
        self.ui._swatch_strips = []
        self.start_minimised = tk.BooleanVar(
            value=bool(saved.get("start_minimised", False))
        )
        refresh_autostart_path()

        self.screen_choice = tk.StringVar()
        self.region = tk.StringVar(value=saved.get("region", ""))
        self.grid_type = tk.StringVar(value=saved.get("grid_type", "Square"))
        self.cell = tk.DoubleVar(value=saved.get("cell", 64.0))
        self.off_x = tk.DoubleVar(value=saved.get("off_x", 0.0))
        self.off_y = tk.DoubleVar(value=saved.get("off_y", 0.0))
        self.line_w = tk.IntVar(value=saved.get("line_w", 1))
        self.opacity = tk.IntVar(value=saved.get("opacity", 70))
        self.colour = tk.StringVar(value=saved.get("colour", "#FFFFFF"))
        self.preview_image_path = saved.get("preview_image", "") or ""
        self.preview_photo = None
        self._photo_key = None
        self.backdrop_label = tk.StringVar(value="Built-in sample map")
        self.overlay_on_start = tk.BooleanVar(
            value=bool(saved.get("overlay_on_start", True))
        )
        self.visible = tk.BooleanVar(value=bool(self.overlay_on_start.get()))
        self.click_through = tk.BooleanVar(value=saved.get("click_through", True))
        self.per_square = tk.DoubleVar(value=saved.get("per_square", 5.0))
        self.unit = tk.StringVar(value=saved.get("unit", "ft"))
        self.diagonal_rule = tk.StringVar(
            value=saved.get("diagonal_rule", DIAGONAL_RULES[0]))
        if self.diagonal_rule.get() not in DIAGONAL_RULES:
            self.diagonal_rule.set(DIAGONAL_RULES[0])
        if self.unit.get() not in UNIT_CHOICES:
            self.unit.set("ft")
        self.measure_readout = tk.StringVar(value="")
        self.span_squares = tk.StringVar(value="")
        self.bands, _error = parse_bands(saved.get("bands", "")) or (None, "")
        if not self.bands:
            self.bands = [list(pair) for pair in DEFAULT_BANDS]
        self.range_mode = tk.StringVar(value=saved.get("range_mode", "DM only"))
        if self.range_mode.get() not in RANGE_MODES:
            self.range_mode.set("DM only")
        self.band_colour = tk.StringVar(
            value=saved.get("band_colour", "#F5C542"))
        self.range_readout = tk.StringVar(value="")
        self.band_summary = tk.StringVar(value="")
        self.range_origin = None
        self.placing_ranges = False
        self.revealing = False
        self.conditions = normalise_conditions(
            saved.get("conditions", ""), saved.get("conditions_version", 0))
        self.condition_choice = tk.StringVar(value=self.conditions[0][0])
        # Markers are held in grid coordinates, not pixels. A marker sits on a
        # creature standing in a square, so when the grid is rescaled or nudged
        # into alignment the marker has to travel with its square rather than
        # staying at a pixel the square has moved away from.
        self.markers = []
        self.marker_size = tk.IntVar(value=saved.get("marker_size", 84))
        self.placing_condition = False

        self.check_updates = tk.BooleanVar(
            value=bool(saved.get("check_updates", True)))
        self.last_update_check = saved.get("last_update_check", 0)
        # Remembered, so a known update is announced at the next startup without
        # waiting on the network, and keeps being announced until it is taken.
        self.latest_seen = str(saved.get("latest_seen", "") or "")
        self.update_notice = tk.StringVar(value="")
        self.update_action = tk.StringVar(value="Open page")
        self.update_url = RELEASES_PAGE

        self.status = tk.StringVar(value="Overlay live")
        self.hotkey_hint = tk.StringVar(value="")

        if self.grid_type.get() not in self.GRID_TYPES:
            self.grid_type.set("Square")

        self.overlay = Overlay(self.root)
        self.pointer = PointerSession(self.root, self.overlay)
        self.preview_painter = Preview(self)
        self.updater = Updates(self)
        self.markers_feature = Markers(self)
        self.ranges_feature = Ranges(self)
        self.measure_feature = Measure(self)
        self.panel = Panel(self)
        self._pending = False
        self._draw_handle = None
        self.ui._wrap_labels = []
        self.ui._value_rows = []
        self._narrow = None
        self.hotkeys = normalise_hotkeys(saved.get("hotkeys", {}),
                                         saved.get("hotkeys_version", 0))
        self.hotkey_manager = HotkeyManager(self.root)
        self.settings_window = None

        self._install_error_guard()
        self._set_window_icon()
        self.panel._build_ui(saved.get("screen", ""))
        self._bind_keys()

        set_frame_mode(self.root)
        self.panel._setup_sizing(saved.get("panel_geometry", ""))

        for var in (self.grid_type, self.cell, self.off_x, self.off_y,
                    self.line_w, self.colour):
            var.trace_add("write", lambda *_: self.schedule_draw())
        for var in (self.per_square, self.unit, self.diagonal_rule):
            var.trace_add("write", lambda *_: self.measure_readout.set(""))
        for var in (self.per_square, self.diagonal_rule, self.cell,
                    self.range_mode, self.band_colour):
            var.trace_add("write", lambda *_: self.ranges_feature._paint_ranges())
        for var in (self.cell, self.off_x, self.off_y, self.marker_size,
                    self.grid_type):
            var.trace_add("write", lambda *_: self.markers_feature._paint_conditions())
        self.band_colour.trace_add("write", lambda *_: self.ui.paint_swatches())
        self.unit.trace_add("write", lambda *_: self.ranges_feature._refresh_band_summary())
        self.opacity.trace_add("write", lambda *_: self.apply_opacity())

        self.apply_screen()
        self.apply_opacity()
        self.apply_visibility()
        self.apply_click_through()
        self.ui.style_dropdown_lists()
        self._register_hotkeys(announce=True)
        self.hotkey_manager.start_polling()
        self._hold_top()

        # A previously seen update is announced straight away. Waiting on the
        # network for something already known would mean saying nothing at all
        # on the days the throttle skips the check.
        if self.latest_seen and is_newer(self.latest_seen, VERSION):
            # The button offers the page for now. The check a moment later
            # fetches the asset details and upgrades it to a real install.
            self.updater.announce_update(self.latest_seen)

        # Delayed, so a slow network cannot hold up the window appearing.
        self.root.after(3000, self.updater.check_for_update)

        if self.start_minimised.get():
            self.root.iconify()

        self.root.protocol("WM_DELETE_WINDOW", self._close_button)

    # -- typography --------------------------------------------------------


    # -- theme -------------------------------------------------------------






    # -- layout scaffolding ------------------------------------------------





    # -- value rows --------------------------------------------------------



    # -- the panel ---------------------------------------------------------


    # -- scrolling ---------------------------------------------------------





    # -- sizing ------------------------------------------------------------




    # -- measuring ---------------------------------------------------------


    def _take_pointer(self, mode, hint, on_click, on_move, label_button=None,
                      label="Cancel"):
        """Borrow the mouse for one interaction.

        The three flows that need it - measuring, placing bands, marking
        creatures - used to do these steps by hand, which was three chances to
        forget the release and leave the screen unclickable. PointerSession owns
        that now; this only sets up what differs.
        """
        if not self.visible.get():
            self.visible.set(True)
            self.apply_visibility()
        self.pointer.take(mode, hint, self.ui.f_num, on_click, on_move,
                          lambda: self.measure_feature.cancel_measure(""),
                          self.click_through.get(),
                          on_release=self._pointer_released)
        if label_button is not None:
            label_button.configure(text=label)
        self.schedule_draw()                     # redraw the grid on the wash

    def _pointer_released(self):
        """Put the panel back the way it was. The mouse is already returned."""
        self.measure = None
        self.placing_ranges = False
        self.placing_condition = False
        self.apply_opacity()
        self.schedule_draw()
        for button, label in ((getattr(self, "measure_button", None),
                               "Measure\u2026"),
                              (getattr(self, "range_button", None),
                               "Place bands\u2026"),
                              (getattr(self, "condition_button", None),
                               "Mark\u2026")):
            if button is None:
                continue
            try:
                button.configure(text=label)
            except tk.TclError:
                pass









    def _release_measure(self):
        self.pointer.release()

    def _arm_measure_timeout(self):
        self.pointer.arm()


    # -- range bands -------------------------------------------------------








    # -- conditions --------------------------------------------------------














    # -- hold to reveal ----------------------------------------------------






    # -- update check ------------------------------------------------------











    # -- window icon -------------------------------------------------------

    def _set_window_icon(self):
        """Put the Gridwyrm mark on every surface Windows draws it on.

        There are three, and they are fed separately, which is why getting one
        right does not get the others:

          the .exe file      PyInstaller's --icon, at build time
          the title bar      iconphoto, from images held in memory
          the taskbar button iconbitmap, which insists on a real file path

        So the embedded PNGs are reassembled into an .ico in the temporary
        folder and pointed at. Together with an explicit application identity,
        set before any window exists, that covers all three.
        """
        try:
            images = [tk.PhotoImage(data=blob) for blob in
                      (ICON_PNG_64, ICON_PNG_32, ICON_PNG_16)]
            # Tk discards images it holds no reference to, so keep them.
            self._icon_images = images
            # True makes it the default for the settings and picker windows too.
            self.root.iconphoto(True, *images)
        except Exception:
            pass                                 # a missing icon is not fatal

        if not IS_WINDOWS:
            return
        try:
            data = base64.b64decode(ICON_ICO)
            path = os.path.join(tempfile.gettempdir(), "gridwyrm-taskbar.ico")
            if not os.path.exists(path) or os.path.getsize(path) != len(data):
                with open(path, "wb") as handle:
                    handle.write(data)
            # Both calls: default sets it for windows opened later, the plain
            # one applies it to this window, which already exists.
            self.root.iconbitmap(default=path)
            self.root.iconbitmap(path)
        except Exception:
            pass

    # -- error containment -------------------------------------------------

    def _install_error_guard(self):
        """Stop any single callback from taking the whole app down.

        A .pyw process has no stderr. Tkinter's default error reporter writes
        to it, so the reporter itself raises and the interpreter aborts - the
        window simply vanishes, with nothing on screen to explain why. This
        replaces the reporter: the message goes to the header and to a log file
        next to the settings, and the app keeps running.
        """
        def report(exc_type, value, tb):
            summary = "%s: %s" % (getattr(exc_type, "__name__", exc_type), value)
            log_event("EXCEPTION %s" % summary[:120])
            try:
                self.status.set("Error: %s" % summary[:70])
            except Exception:
                pass
            try:
                path = os.path.join(os.path.dirname(settings_path()),
                                    "errors.log")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "a", encoding="utf-8") as handle:
                    handle.write("\n%s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                    traceback.print_exception(exc_type, value, tb, file=handle)
            except Exception:
                pass

        self.root.report_callback_exception = report

    def _guard(self, function):
        """Wrap a hotkey handler so a failure reports instead of vanishing."""
        name = getattr(function, "__name__", "handler")

        def guarded():
            log_event("hotkey picked up: %s" % name)
            try:
                function()
            except Exception:
                log_event("hotkey raised: %s" % name)
                self.root.report_callback_exception(*sys.exc_info())
            else:
                log_event("hotkey done: %s" % name)
        return guarded

    # -- hotkeys -----------------------------------------------------------

    def _hotkey_handlers(self):
        raw = {
            "toggle": self.toggle_visible,
            "nudge_left": lambda: self.bump(self.off_x, -1, force=True),
            "nudge_right": lambda: self.bump(self.off_x, 1, force=True),
            "nudge_up": lambda: self.bump(self.off_y, -1, force=True),
            "nudge_down": lambda: self.bump(self.off_y, 1, force=True),
            "cell_down": lambda: self.bump(self.cell, -1, force=True),
            "cell_up": lambda: self.bump(self.cell, 1, force=True),
            "cycle_shape": self.cycle_shape,
            "focus_panel": self.focus_panel,
            "reveal_ranges": self.ranges_feature.reveal_ranges,
        }
        return {name: self._guard(function) for name, function in raw.items()}

    def _register_hotkeys(self, announce=False):
        failures = self.hotkey_manager.apply(self.hotkeys, self._hotkey_handlers())
        log_event("hotkeys: %d requested, %d refused%s"
                  % (sum(1 for p in self.hotkeys.values()
                         if p[0] != HOTKEY_OFF),
                     len(failures),
                     (" (" + ", ".join(sorted(failures)) + ")")
                     if failures else ""))
        if announce and failures and IS_WINDOWS:
            self.status.set("%d hotkey%s unavailable" % (
                len(failures), "" if len(failures) == 1 else "s"))
        self._refresh_hotkey_hint()
        return failures

    def apply_hotkeys(self, bindings):
        """Called by the settings window. Returns {action: reason} failures."""
        self.hotkeys = dict(bindings)
        return self._register_hotkeys()

    def _refresh_hotkey_hint(self):
        toggle = hotkey_text(self.hotkeys.get("toggle"))
        if IS_WINDOWS and toggle != "not set":
            self.hotkey_hint.set("%s shows or hides the grid from anywhere"
                                 % toggle)
        else:
            self.hotkey_hint.set("Global hotkeys need Windows")

    def open_settings(self):
        if self.settings_window is not None:
            try:
                self.settings_window.win.lift()
                self.settings_window.win.focus_set()
                return
            except tk.TclError:
                self.settings_window = None
        self.settings_window = SettingsWindow(self)

    def cycle_shape(self):
        try:
            index = self.GRID_TYPES.index(self.grid_type.get())
        except ValueError:
            index = -1
        self.grid_type.set(self.GRID_TYPES[(index + 1) % len(self.GRID_TYPES)])

    def focus_panel(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    # -- themes ------------------------------------------------------------

    def apply_theme(self, name, custom=None):
        """Switch themes without a restart.

        ttk styles update themselves once reconfigured, but the canvases we
        draw by hand hold their own colours, so those are refreshed here.
        """
        if name not in THEME_ORDER:
            name = "Dark"
        self.theme_name = name
        if custom is not None:
            self.custom_theme = dict(custom)
        apply_palette(resolve_theme(name, self.custom_theme))

        self.ui.rebuild()
        self.ui.style_dropdown_lists()

        self.root.configure(bg=theme.INK)
        self.lamp.configure(bg=theme.INK)
        self.viewport.configure(bg=theme.INK)
        self.preview.configure(bg=theme.INK, highlightbackground=theme.LINE)
        self._map_size = None                    # chip colours follow the theme
        for strip in self.ui._swatch_strips:
            strip["canvas"].configure(bg=theme.PANEL)
        set_frame_mode(self.root)
        if self.settings_window is not None:
            self.settings_window.restyle()

        self._paint_lamp()
        self.schedule_draw()

    # -- painted bits ------------------------------------------------------

    def _paint_lamp(self):
        self.lamp.delete("all")
        size = self.ui.px(8)
        on = bool(self.visible.get())
        self.lamp.create_oval(0, 0, size - 1, size - 1,
                              fill=theme.HILITE if on else theme.FIELD,
                              outline="" if on else theme.LINE)






    # -- preview backdrop --------------------------------------------------










    # -- keys --------------------------------------------------------------

    def _bind_keys(self):
        r = self.root
        pairs = (
            ("<Left>", self.off_x, -1), ("<Right>", self.off_x, 1),
            ("<Up>", self.off_y, -1), ("<Down>", self.off_y, 1),
            ("<Shift-Left>", self.off_x, -10), ("<Shift-Right>", self.off_x, 10),
            ("<Shift-Up>", self.off_y, -10), ("<Shift-Down>", self.off_y, 10),
            ("<plus>", self.cell, 1), ("<KP_Add>", self.cell, 1),
            ("<minus>", self.cell, -1), ("<KP_Subtract>", self.cell, -1),
            ("<bracketleft>", self.cell, -0.5), ("<bracketright>", self.cell, 0.5),
        )
        for sequence, var, delta in pairs:
            r.bind(sequence, lambda e, v=var, d=delta: self.bump(v, d))

        # There is deliberately no bare-letter shortcut here. A plain "h" used
        # to hide the overlay, but a key binding on the window catches the
        # keystroke wherever the focus is, so typing a band name containing an
        # h - Reach, for one - toggled the grid mid-word. The global hotkey
        # already does the job and works whether this panel has focus or not,
        # which made the local one redundant as well as hazardous. The bindings
        # above are safe because bump ignores them while a field has focus.
        # Escape deliberately does nothing here. Closing a tool that sits open
        # all session on a single stray keypress is too easy to do by accident;
        # dialogs still use Escape to dismiss themselves.

    # -- behaviour ---------------------------------------------------------

    def bump(self, var, delta, force=False):
        if not force:
            try:
                focused = self.root.focus_get()
            except (tk.TclError, KeyError):
                focused = None                   # focus is on a foreign window
            if isinstance(focused, (ttk.Entry, tk.Entry, ttk.Spinbox)):
                return                           # typing in a field
        value = round(safe_float(var) + delta, 2)
        if var is self.cell:
            value = max(8.0, value)
        if var is self.opacity:
            value = min(100.0, max(10.0, value))
        var.set(int(round(value)) if isinstance(var, tk.IntVar) else value)

    def pick_colour(self):
        chosen = ColourPicker(self, self.root, self.colour.get(),
                              "Grid line colour").show()
        if chosen:
            self.colour.set(chosen)



    def apply_screen(self):
        choice = self.screen_choice.get()
        if choice.startswith("Custom"):
            rect = parse_geometry(self.region.get())
            if rect is None:
                self.region_entry.focus_set()
                self.status.set("Region needs the form 1920x1080+0+0")
                return
        else:
            index = self.screen_box.current()
            if index < 0 or index >= len(self.monitors):
                index = 0
            rect = self.monitors[index]
        x, y, w, h = rect
        self.region.set(f"{w}x{h}{x:+d}{y:+d}")
        self.overlay.place_on(x, y, w, h)
        self.status.set("Overlay live" if self.visible.get() else "Overlay hidden")
        self.schedule_draw()

    def apply_opacity(self):
        try:
            self.overlay.set_opacity(self.opacity.get())
        except tk.TclError:
            pass
        self.schedule_draw()

    def apply_visibility(self):
        if self.visible.get():
            self.status.set("Overlay live")
            self.overlay.show()
            self.apply_click_through()
            self.schedule_draw()
        else:
            self.status.set("Overlay hidden")
            self.overlay.hide()
        self._paint_lamp()

    def apply_click_through(self):
        self.overlay.set_click_through(bool(self.click_through.get()))

    def toggle_visible(self):
        self.visible.set(not self.visible.get())
        self.apply_visibility()

    def schedule_draw(self):
        if self._pending:
            return
        self._pending = True
        # The handle is kept so it can be cancelled on the way out. A redraw
        # firing after the window has gone makes Tcl complain about an unknown
        # command, which is harmless and looks alarming in a log.
        self._draw_handle = self.root.after(25, self._draw)

    def _draw(self):
        self._pending = False
        self._draw_handle = None
        colour = str(self.colour.get())
        if not colour.startswith("#"):
            return
        kind = self.grid_type.get()
        size = max(8.0, safe_float(self.cell, 64.0))
        off_x, off_y = safe_float(self.off_x), safe_float(self.off_y)
        weight = max(1, int(safe_float(self.line_w, 1)))
        opacity = max(10, min(100, int(safe_float(self.opacity, 70))))

        self.ui.paint_swatches()
        self.preview_painter._paint_preview(kind, size, off_x, off_y, colour, weight, opacity)
        if self.visible.get():
            self.overlay.draw(kind, size, off_x, off_y, colour, weight)

    def _close_button(self):
        log_event("window close button pressed")
        self.quit()

    def _hold_top(self):
        if self.visible.get():
            self.overlay.raise_above()
        self.root.after(2000, self._hold_top)

    def quit(self):
        # The single most useful breadcrumb: if the app disappears and this
        # line is absent from the log, nothing asked it to close - it died.
        caller = "".join(traceback.format_stack(limit=4)[:-1]).strip()
        log_event("quit() called\n    %s" % caller.replace("\n", "\n    "))
        try:
            panel_geometry = self.root.geometry()
        except tk.TclError:
            panel_geometry = ""
        save_settings({
            "panel_geometry": panel_geometry,
            "screen": self.screen_choice.get(),
            "region": self.region.get(),
            "grid_type": self.grid_type.get(),
            "cell": safe_float(self.cell, 64.0),
            "off_x": safe_float(self.off_x),
            "off_y": safe_float(self.off_y),
            "line_w": int(safe_float(self.line_w, 1)),
            "opacity": int(safe_float(self.opacity, 70)),
            "colour": self.colour.get(),
            "click_through": bool(self.click_through.get()),
            "overlay_on_start": bool(self.overlay_on_start.get()),
            "preview_image": self.preview_image_path,
            "per_square": safe_float(self.per_square, 5.0),
            "unit": self.unit.get(),
            "diagonal_rule": self.diagonal_rule.get(),
            "bands": format_bands(self.bands),
            "range_mode": self.range_mode.get(),
            "band_colour": self.band_colour.get(),
            "conditions": format_conditions(self.conditions),
            "conditions_version": CONDITION_DEFAULTS_VERSION,
            "marker_size": int(safe_float(self.marker_size, 84)),
            "check_updates": bool(self.check_updates.get()),
            "last_update_check": self.last_update_check,
            "latest_seen": self.latest_seen,
            "hotkeys": self.hotkeys,
            "hotkeys_version": HOTKEY_DEFAULTS_VERSION,
            "theme": self.theme_name,
            "custom_theme": self.custom_theme,
            "start_minimised": bool(self.start_minimised.get()),
        })
        self.hotkey_manager.destroy()
        self.pointer.release()                   # never exit holding the mouse
        for handle in (getattr(self, "_draw_handle", None),):
            if handle is not None:
                try:
                    self.root.after_cancel(handle)
                except Exception:
                    pass
        log_event("---- clean exit")
        self.root.destroy()

    def run(self):
        self.root.mainloop()
