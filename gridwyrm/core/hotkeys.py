"""System-wide hotkeys: the key tables and the registration."""

import ctypes
import tkinter as tk

from .win32 import IS_WINDOWS, WNDCLASSW, WNDPROC


HOTKEY_OFF = "(off)"


MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 1, 2, 4, 8, 0x4000


MODIFIER_CHOICES = {
    "Ctrl + Alt": MOD_CONTROL | MOD_ALT,
    "Ctrl + Shift": MOD_CONTROL | MOD_SHIFT,
    "Alt + Shift": MOD_ALT | MOD_SHIFT,
    "Ctrl + Alt + Shift": MOD_CONTROL | MOD_ALT | MOD_SHIFT,
    "Ctrl + Win": MOD_CONTROL | MOD_WIN,
    "Win + Alt": MOD_WIN | MOD_ALT,
    "Win + Shift": MOD_WIN | MOD_SHIFT,
}


MODIFIER_ORDER = [HOTKEY_OFF] + list(MODIFIER_CHOICES)


def _build_vk_map():
    keys = {}
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        keys[letter] = ord(letter)
    for digit in "0123456789":
        keys[digit] = ord(digit)
    for n in range(1, 13):
        keys["F%d" % n] = 0x70 + n - 1
    keys.update({
        "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
        "Space": 0x20, "Insert": 0x2D, "Home": 0x24, "End": 0x23,
        "Page Up": 0x21, "Page Down": 0x22,
        "Comma": 0xBC, "Period": 0xBE, "Minus": 0xBD, "Equals": 0xBB,
        "[": 0xDB, "]": 0xDD, "Semicolon": 0xBA, "Slash": 0xBF,
        "Numpad +": 0x6B, "Numpad -": 0x6D, "Numpad *": 0x6A, "Numpad /": 0x6F,
    })
    return keys


VK_MAP = _build_vk_map()


KEY_ORDER = (
    [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    + [str(d) for d in range(10)]
    + ["F%d" % n for n in range(1, 13)]
    + ["Left", "Right", "Up", "Down", "Space", "Insert", "Home", "End",
       "Page Up", "Page Down", "Comma", "Period", "Minus", "Equals",
       "[", "]", "Semicolon", "Slash",
       "Numpad +", "Numpad -", "Numpad *", "Numpad /"]
)


ACTIONS = (
    ("toggle", "Show / hide the overlay", False),
    ("nudge_left", "Nudge grid left", True),
    ("nudge_right", "Nudge grid right", True),
    ("nudge_up", "Nudge grid up", True),
    ("nudge_down", "Nudge grid down", True),
    ("cell_down", "Cell size smaller", True),
    ("cell_up", "Cell size larger", True),
    ("cycle_shape", "Next grid shape", False),
    ("focus_panel", "Bring this panel to the front", False),
    ("reveal_ranges", "Hold to show range bands to players", False),
)


DEFAULT_HOTKEYS = {
    "toggle": ["Ctrl + Alt + Shift", "G"],
    "nudge_left": ["Ctrl + Alt + Shift", "Left"],
    "nudge_right": ["Ctrl + Alt + Shift", "Right"],
    "nudge_up": ["Ctrl + Alt + Shift", "Up"],
    "nudge_down": ["Ctrl + Alt + Shift", "Down"],
    "cell_down": ["Ctrl + Alt + Shift", "J"],
    "cell_up": ["Ctrl + Alt + Shift", "K"],
    "cycle_shape": ["Ctrl + Alt + Shift", "B"],
    "focus_panel": ["Ctrl + Alt + Shift", "P"],
    "reveal_ranges": ["Ctrl + Alt + Shift", "R"],
}


HOTKEY_DEFAULTS_VERSION = 2


SUPERSEDED_DEFAULTS = {
    "toggle": [["Ctrl + Alt", "G"]],          # Ctrl+Alt+G belongs to Google Drive
    "cell_down": [["Ctrl + Alt", "J"]],
    "cell_up": [["Ctrl + Alt", "K"]],
    "cycle_shape": [["Ctrl + Alt", "B"]],
    "focus_panel": [["Ctrl + Alt", "P"]],
}


def normalise_hotkeys(saved, version=0):
    """Take whatever is in the settings file and return a usable mapping.

    `version` is the defaults generation the file was written against. When it
    lags behind, any binding still sitting on a superseded default is moved to
    the current one; anything else the user set is kept exactly as it is.
    """
    result = {}
    outdated = version < HOTKEY_DEFAULTS_VERSION
    for action, _label, _repeat in ACTIONS:
        pair = saved.get(action) if isinstance(saved, dict) else None
        if (isinstance(pair, (list, tuple)) and len(pair) == 2
                and pair[0] in MODIFIER_ORDER
                and (pair[0] == HOTKEY_OFF or pair[1] in VK_MAP)):
            if outdated and list(pair) in SUPERSEDED_DEFAULTS.get(action, []):
                result[action] = list(DEFAULT_HOTKEYS[action])
            else:
                result[action] = [pair[0], pair[1]]
        else:
            result[action] = list(DEFAULT_HOTKEYS[action])
    return result


def hotkey_text(pair):
    if not pair or pair[0] == HOTKEY_OFF:
        return "not set"
    return "%s + %s" % (pair[0], pair[1])


class HotkeyManager:
    """System-wide hotkeys, delivered through a hidden native window.

    Windows posts WM_HOTKEY to a window, not to tkinter. Rather than fight
    tkinter's event loop, this creates its own tiny never-shown window with a
    real window procedure. Tk's loop pumps the thread's messages either way,
    and dispatch routes WM_HOTKEY to that procedure, which then hands the work
    back to the Tk thread through after_idle.
    """

    WM_HOTKEY = 0x0312
    CLASS_NAME = "GridwyrmHotkeyHost"
    POLL_MS = 40
    MAX_PENDING = 40

    def __init__(self, root):
        self.root = root
        self.hwnd = None
        self.available = False
        self._proc = None
        self._handlers = {}
        self._ids = []
        self._next_id = 1
        self._pending = []
        self._polling = False
        if IS_WINDOWS:
            self._create_host()

    def _create_host(self):
        try:
            u32 = ctypes.windll.user32
            self._proc = WNDPROC(self._on_message)
            spec = WNDCLASSW()
            spec.lpfnWndProc = self._proc
            spec.lpszClassName = self.CLASS_NAME
            spec.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
            # A second instance finds the class already registered, which is
            # harmless, so the return value is deliberately not checked.
            u32.RegisterClassW(ctypes.byref(spec))
            self.hwnd = u32.CreateWindowExW(
                0, self.CLASS_NAME, "Gridwyrm", 0, 0, 0, 0, 0,
                None, None, spec.hInstance, None,
            )
            self.available = bool(self.hwnd)
        except Exception:
            self.hwnd = None
            self.available = False

    def _on_message(self, hwnd, msg, wparam, lparam):
        """The window procedure. Does no Tk work at all, on purpose.

        This runs inside Tcl's own message dispatch, so calling back into the
        interpreter from here - even something as small as after_idle - re-enters
        Tcl while it is already mid-dispatch. Tkinter is not re-entrant, and the
        result is a process that dies with no Python exception and no fault
        trace. The hotkey id is queued instead, and a timer running on the Tk
        thread picks it up a moment later.
        """
        if msg == self.WM_HOTKEY:
            try:
                if len(self._pending) < self.MAX_PENDING:
                    self._pending.append(int(wparam))
            except Exception:
                pass
            return 0
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def start_polling(self):
        """Begin draining queued hotkeys on the Tk thread."""
        if self._polling:
            return
        self._polling = True
        self._poll()

    def _poll(self):
        while self._pending:
            hk_id = self._pending.pop(0)
            handler = self._handlers.get(hk_id)
            if handler:
                handler()                        # already wrapped by App._guard
        try:
            self.root.after(self.POLL_MS, self._poll)
        except tk.TclError:
            self._polling = False

    def clear(self):
        if not (IS_WINDOWS and self.hwnd):
            self._handlers, self._ids = {}, []
            return
        u32 = ctypes.windll.user32
        for hk_id in self._ids:
            try:
                u32.UnregisterHotKey(self.hwnd, hk_id)
            except Exception:
                pass
        self._handlers, self._ids = {}, []

    def apply(self, bindings, handlers):
        """Register the given bindings. Returns {action: reason} for failures."""
        self.clear()
        wanted = {
            action: bindings.get(action, [HOTKEY_OFF, ""])
            for action, _label, _repeat in ACTIONS
        }
        if not self.available:
            return {a: "needs Windows" for a, pair in wanted.items()
                    if pair[0] != HOTKEY_OFF}

        u32 = ctypes.windll.user32
        failures = {}
        for action, _label, repeat in ACTIONS:
            mods_label, key_label = wanted[action]
            if mods_label == HOTKEY_OFF:
                continue
            mods = MODIFIER_CHOICES.get(mods_label)
            vk = VK_MAP.get(key_label)
            if mods is None or vk is None:
                failures[action] = "unknown key"
                continue
            flags = mods if repeat else mods | MOD_NOREPEAT
            hk_id = self._next_id
            self._next_id += 1
            try:
                ok = u32.RegisterHotKey(self.hwnd, hk_id, flags, vk)
            except Exception:
                ok = False
            if ok:
                self._ids.append(hk_id)
                self._handlers[hk_id] = handlers[action]
            else:
                failures[action] = "already taken"
        return failures

    def destroy(self):
        self._polling = False
        self._pending = []
        self.clear()
        if IS_WINDOWS and self.hwnd:
            try:
                ctypes.windll.user32.DestroyWindow(self.hwnd)
            except Exception:
                pass
        self.hwnd = None
