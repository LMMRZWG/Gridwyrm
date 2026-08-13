"""Where settings and logs live, and how they are read."""

import faulthandler
import json
import os
import time

from .win32 import IS_WINDOWS


def settings_path():
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Gridwyrm", "settings.json")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "gridwyrm", "settings.json")


def load_settings():
    try:
        with open(settings_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data):
    try:
        path = settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except Exception:
        pass                                     # never block shutdown


def log_path(name):
    return os.path.join(os.path.dirname(settings_path()), name)


def log_event(message):
    try:
        path = log_path("session.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "a"
        try:
            if os.path.getsize(path) > 256 * 1024:
                mode = "w"                       # keep it from growing forever
        except OSError:
            pass
        with open(path, mode, encoding="utf-8") as handle:
            handle.write("%s  %s\n" % (time.strftime("%H:%M:%S"), message))
    except Exception:
        pass


def enable_fault_log():
    """Catch hard faults, which never reach Python's exception handling."""
    try:
        path = log_path("crash.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handle = open(path, "a", encoding="utf-8", buffering=1)
        handle.write("\n=== session started %s ===\n"
                     % time.strftime("%Y-%m-%d %H:%M:%S"))
        faulthandler.enable(file=handle)
        return handle          # must outlive the process, so it is returned
    except Exception:
        return None
