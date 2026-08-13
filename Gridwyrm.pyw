#!/usr/bin/env pythonw
"""
Gridwyrm: a transparent grid overlay for tabletop maps.

Double-click this file to run it. It is the only file here that starts the
program; everything else lives in the gridwyrm package beside it.

    Gridwyrm.pyw        <- double-click this
    gridwyrm/           <- the code
      core/             everything that does not touch the screen
      ui/               the windows
      app.py            the wiring

Running gridwyrm/app.py, or any other file inside the package, cannot work:
those use relative imports and are not entry points.

To watch for errors, run this from a terminal you already have open:

    python Gridwyrm.pyw

This file goes to some trouble to make a failure visible. A .pyw has nowhere to
print, and a console opened by a double-click closes the instant the process
ends, so anything that goes wrong is written to a file and shown in a dialog too.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def crash_report(details):
    """Record a failure everywhere it might be found.

    Deliberately independent of the package, because the reason for the failure
    may be that the package could not be imported at all.
    """
    written = []
    for folder in (HERE, os.environ.get("APPDATA", ""),
                   os.environ.get("TEMP", "")):
        if not folder:
            continue
        try:
            path = os.path.join(folder, "gridwyrm-startup-error.txt")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(details)
            written.append(path)
        except Exception:
            continue

    message = details
    if written:
        message += "\n\nWritten to:\n" + "\n".join(written)

    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message,
                                         "Gridwyrm could not start", 0x10)
    except Exception:
        pass
    try:
        sys.stderr.write(message + "\n")
        sys.stderr.flush()
    except Exception:
        pass
    # A console opened by double-clicking closes the moment this returns, so
    # hold it open long enough to be read.
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input("\nPress Enter to close. ")
    except Exception:
        pass


def describe_folder():
    """What is actually in the folder, which is usually the answer."""
    lines = ["Looked for the package in:", "  " + HERE, "", "Found:"]
    try:
        for name in sorted(os.listdir(HERE))[:40]:
            kind = "folder" if os.path.isdir(os.path.join(HERE, name)) else "file"
            lines.append("  %-28s %s" % (name, kind))
    except Exception as error:
        lines.append("  could not list the folder: %s" % error)

    package = os.path.join(HERE, "gridwyrm")
    lines.append("")
    if not os.path.isdir(package):
        lines.append("The gridwyrm folder is missing. Extract the whole zip and")
        lines.append("keep Gridwyrm.pyw and the gridwyrm folder side by side.")
    else:
        for needed in ("__init__.py", "app.py",
                       os.path.join("core", "theme.py"),
                       os.path.join("ui", "overlay.py")):
            if not os.path.exists(os.path.join(package, needed)):
                lines.append("Missing: gridwyrm%s%s" % (os.sep, needed))
    return "\n".join(lines)


def main():
    try:
        from gridwyrm.app import App
    except BaseException:
        crash_report("Gridwyrm could not load its own code.\n\n"
                     + traceback.format_exc() + "\n" + describe_folder())
        return 1
    try:
        App().run()
    except BaseException:
        crash_report("Gridwyrm started loading and then failed.\n\n"
                     + traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
