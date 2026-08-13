"""Windows plumbing: handles, monitors, DPI, autostart."""

import ctypes
import os
import sys

from . import theme
from .theme import luminance


IS_WINDOWS = sys.platform.startswith("win")


if IS_WINDOWS:
    import winreg
    from ctypes import wintypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor v2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


if IS_WINDOWS:
    LRESULT = ctypes.c_ssize_t
    WPARAM_T = ctypes.c_size_t
    LPARAM_T = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                 WPARAM_T, LPARAM_T)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    def _prepare_win32():
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32

        # Every call below returns or accepts a pointer-sized handle. Left
        # undeclared, ctypes assumes a 32-bit int, which silently truncates
        # handles on 64-bit Windows - the kind of fault that takes the process
        # down with no Python traceback to show for it.
        k32.GetModuleHandleW.restype = wintypes.HMODULE
        k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k32.GetConsoleWindow.restype = wintypes.HWND
        k32.GetConsoleWindow.argtypes = []
        k32.GetCurrentProcessId.restype = wintypes.DWORD
        k32.GetCurrentProcessId.argtypes = []

        u32.GetParent.restype = wintypes.HWND
        u32.GetParent.argtypes = [wintypes.HWND]
        u32.GetWindowThreadProcessId.restype = wintypes.DWORD
        u32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u32.ShowWindow.restype = wintypes.BOOL
        u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.SetWindowPos.restype = wintypes.BOOL
        u32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u32.EnumDisplayMonitors.restype = wintypes.BOOL
        # A registered hotkey reports its press but never its release, so
        # hold-to-reveal has to watch the key directly.
        u32.GetAsyncKeyState.restype = ctypes.c_short
        u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        if hasattr(u32, "GetDpiForWindow"):
            u32.GetDpiForWindow.restype = wintypes.UINT
            u32.GetDpiForWindow.argtypes = [wintypes.HWND]

        try:
            dwm = ctypes.windll.dwmapi
            dwm.DwmSetWindowAttribute.restype = ctypes.c_long   # HRESULT
            dwm.DwmSetWindowAttribute.argtypes = [
                wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        except Exception:
            pass

        u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        u32.RegisterClassW.restype = wintypes.WORD
        u32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        u32.CreateWindowExW.restype = wintypes.HWND
        u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                       WPARAM_T, LPARAM_T]
        u32.DefWindowProcW.restype = LRESULT
        u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                       wintypes.UINT, wintypes.UINT]
        u32.RegisterHotKey.restype = wintypes.BOOL
        u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.UnregisterHotKey.restype = wintypes.BOOL
        u32.DestroyWindow.argtypes = [wintypes.HWND]
        # Without explicit types these default to a 32-bit int return, which
        # truncates a window's extended style on 64-bit Windows.
        for name in ("GetWindowLongPtrW", "SetWindowLongPtrW"):
            function = getattr(u32, name, None)
            if function is not None:
                function.restype = LRESULT
                function.argtypes = ([wintypes.HWND, ctypes.c_int]
                                     + ([LPARAM_T] if "Set" in name else []))
        u32.GetWindowLongW.restype = wintypes.LONG
        u32.SetWindowLongW.restype = wintypes.LONG

    try:
        _prepare_win32()
    except Exception:
        pass
else:
    # Named either way, so other modules can import them without each
    # guarding its own import statement. Nothing that touches them runs
    # unless IS_WINDOWS is true.
    LRESULT = WPARAM_T = LPARAM_T = WNDPROC = WNDCLASSW = None


def hwnd_of(window):
    handle = ctypes.windll.user32.GetParent(window.winfo_id())
    return handle or window.winfo_id()


def set_frame_mode(window, dark=None):
    """Match a window's native title bar to the current theme.

    Applies to every window we open, not just the main panel - a light title
    bar over a dark dialog is the most obvious way for a Tk program to look
    unfinished. The repaint is forced through SetWindowPos rather than by
    hiding and reshowing the window, which would blink and, for the main
    window, briefly take the overlay down with it.
    """
    if not IS_WINDOWS:
        return
    if dark is None:
        dark = luminance(theme.INK) < 0.5
    try:
        window.update_idletasks()
        hwnd = hwnd_of(window)
        flag = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):               # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(flag), ctypes.sizeof(flag)
            )
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_FRAMECHANGED = 1, 2, 4, 0x20
        ctypes.windll.user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )
    except Exception:
        pass


def screen_dpi(window):
    if IS_WINDOWS:
        try:
            return float(ctypes.windll.user32.GetDpiForWindow(hwnd_of(window)))
        except Exception:
            pass
    try:
        return float(window.winfo_fpixels("1i"))
    except Exception:
        return 96.0


def list_monitors():
    """[(x, y, w, h), ...] per display, in virtual-desktop coordinates."""
    if not IS_WINDOWS:
        return []
    rects = []
    enum_proc = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(wintypes.RECT), ctypes.c_void_p,
    )

    def callback(_mon, _dc, lprect, _data):
        r = lprect.contents
        rects.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return 1

    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, enum_proc(callback), None)
    except Exception:
        return []
    return rects


def hide_own_console():
    """Hide the console window, but only if this process owns it.

    Double-clicking the .pyw means no console exists and this does nothing at
    all. It matters if the file is ever renamed to .py and double-clicked,
    where python.exe opens a console of its own.

    The ownership check is the important part: a terminal you opened yourself
    belongs to that terminal, not to Gridwyrm, so it is left alone. That is
    what makes "python gridwyrm.pyw" a usable way to watch for errors.
    """
    if not IS_WINDOWS:
        return
    try:
        kernel32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
        console = kernel32.GetConsoleWindow()
        if not console:
            return
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(console, ctypes.byref(owner))
        if owner.value == kernel32.GetCurrentProcessId():
            user32.ShowWindow(console, 0)        # SW_HIDE
    except Exception:
        pass


def claim_taskbar_identity():
    """Tell Windows this program is its own application.

    Without an explicit identity, a Python program can be grouped under the
    interpreter or the toolkit, and the taskbar shows their icon instead of
    ours. This has to run before any window exists.
    """
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "LMMRZWG.Gridwyrm")
    except Exception:
        pass


RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


RUN_VALUE_NAME = "Gridwyrm"


def autostart_command():
    """The command line that relaunches this program."""
    if getattr(sys, "frozen", False):
        return '"%s"' % os.path.abspath(sys.executable)
    # __file__ is the real module path; argv[0] can be a stub or empty
    # depending on how the interpreter was invoked.
    script = None
    try:
        script = os.path.abspath(__file__)
    except NameError:
        pass
    if not script or not os.path.exists(script):
        candidate = sys.argv[0] if sys.argv else ""
        script = os.path.abspath(candidate) if candidate else ""
    launcher = sys.executable
    # pythonw.exe keeps the console from flashing up at every login.
    windowless = os.path.join(os.path.dirname(launcher), "pythonw.exe")
    if os.path.exists(windowless):
        launcher = windowless
    return '"%s" "%s"' % (launcher, script)


def autostart_state():
    """Returns (enabled, command currently recorded in the registry)."""
    if not IS_WINDOWS:
        return False, ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            value, _kind = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return True, str(value)
    except OSError:
        return False, ""


def set_autostart(enabled):
    """Returns (ok, message)."""
    if not IS_WINDOWS:
        return False, "needs Windows"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ,
                                  autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True, ""
    except OSError as error:
        return False, str(error)


def refresh_autostart_path():
    """Repair the recorded command if the program has since been moved."""
    enabled, recorded = autostart_state()
    if enabled and recorded != autostart_command():
        set_autostart(True)


SHIFT_HELD = 0x0001                          # the Shift bit in a Tk event state
