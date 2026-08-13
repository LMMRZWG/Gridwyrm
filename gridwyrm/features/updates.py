"""Checking for a newer release, and installing one."""

import os
import subprocess
import sys
import threading
import time
import webbrowser

from ..core.storage import log_event
from ..core.updates import (RELEASES_PAGE, VERSION,
                           download_is_trusted,
                           download_release_asset, is_newer,
                           read_latest_release, swap_script,
                           update_check_due)
from ..core.win32 import IS_WINDOWS

class Updates:
    """Checking for a newer release, and installing one.
    The network call runs on its own thread, because an unreachable
    connection would otherwise freeze the interface for the length of
    the timeout. That thread touches nothing but a list: handing a
    reply back through Tk from another thread is the mistake that made
    the hotkeys crash, and it is not worth repeating.

    Given the application, which is where the shared state and the overlay
    live. Nothing here reaches into another feature.
    """

    def __init__(self, app):
        self.app = app
        self.asset = None
        self.reply = []
        self.worker = None
        self.download_reply = []
        self.download_worker = None
        self.pending = ""
        self.state = "idle"

    def check_for_update(self, manual=False):
        """Ask GitHub whether there is a newer release.

        The request runs on a separate thread, because a slow or unreachable
        network would otherwise freeze the whole interface for the length of the
        timeout. That thread touches nothing but a plain list: handing a reply
        back through Tk from another thread is the same mistake that made the
        hotkeys crash, and it is not worth repeating.
        """
        if self.worker is not None and self.worker.is_alive():
            return
        if not manual:
            if not self.app.check_updates.get():
                return
            if not update_check_due(self.app.last_update_check):
                return

        self.reply = []
        if manual:
            self.app.update_notice.set("Checking\u2026")

        def work():
            try:
                self.reply.append(read_latest_release())
            except Exception as error:                # noqa: BLE001
                self.reply.append(error)

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.app.last_update_check = time.time()
        self._await_update(manual, 0)

    def _await_update(self, manual, waited):
        if not self.reply:
            if waited > 15000:
                if manual:
                    self.app.update_notice.set("GitHub did not answer in time.")
                return
            self.app.root.after(250,
                            lambda: self._await_update(manual, waited + 250))
            return

        reply = self.reply[0]
        if isinstance(reply, Exception):
            # No network, a rate limit, or a changed reply. Say nothing unless
            # the check was asked for by hand.
            log_event("update check failed: %s" % reply)
            if manual:
                self.app.update_notice.set("Could not reach GitHub just now.")
            return

        tag = reply.get("tag", "")
        if is_newer(tag, VERSION):
            self.app.latest_seen = tag
            self.app.update_url = reply.get("page") or RELEASES_PAGE
            self.asset = reply.get("asset")
            self.announce_update(tag)
            log_event("update available: %s" % tag)
        else:
            self.app.latest_seen = ""
            self.app.update_notice.set("Up to date. You have %s." % VERSION)
            log_event("up to date at %s" % VERSION)

    def announce_update(self, tag):
        """Show the notice, and label the button for what it can actually do."""
        self.state = "idle"
        if self.can_install():
            self.app.update_notice.set(
                "%s is out. You have %s." % (tag, VERSION))
            self.app.update_action.set("Update now")
        else:
            self.app.update_notice.set(
                "%s is out. You have %s." % (tag, VERSION))
            self.app.update_action.set("Open page")
        self.app.update_row.pack(fill="x", padx=self.app.ui.px(14),
                             pady=(0, self.app.ui.px(8)))

    def can_install(self):
        """Whether Gridwyrm is able to replace itself in place.

        Only a packaged build can: replacing a .pyw would mean guessing what
        someone did with their copy of the source. The folder also has to be
        writable, which rules out a copy sitting in Program Files.
        """
        if not IS_WINDOWS or not getattr(sys, "frozen", False):
            return False
        if not self.asset:
            return False
        folder = os.path.dirname(os.path.abspath(sys.executable))
        probe = os.path.join(folder, ".gridwyrm-write-test")
        try:
            with open(probe, "wb") as handle:
                handle.write(b"x")
            os.remove(probe)
            return True
        except Exception:
            return False

    def update_button_pressed(self):
        """One button, three jobs, depending on where the update has got to."""
        if self.state == "installing":
            return
        if self.state == "ready":
            self.install_update()
            return
        if self.can_install():
            self.start_download()
        else:
            self.open_release_page()

    def start_download(self):
        """Fetch the new program to a file beside the current one."""
        asset = self.asset
        if not asset or not download_is_trusted(asset.get("url", "")):
            self.open_release_page()
            return
        folder = os.path.dirname(os.path.abspath(sys.executable))
        incoming = os.path.join(folder, "Gridwyrm.update.exe")

        self.state = "installing"
        self.app.update_action.set("Downloading\u2026")
        self.app.update_notice.set("Fetching %s\u2026" % asset.get("name", "update"))
        self.download_reply = []

        def work():
            # Off the Tk thread, so it appends to a list and nothing more.
            try:
                download_release_asset(asset["url"], incoming,
                                       asset.get("size", 0))
                self.download_reply.append(incoming)
            except Exception as error:                # noqa: BLE001
                self.download_reply.append(error)

        self.download_worker = threading.Thread(target=work, daemon=True)
        self.download_worker.start()
        self._await_download(0)

    def _await_download(self, waited):
        if not self.download_reply:
            if waited > 300000:                       # five minutes is plenty
                self.state = "idle"
                self.app.update_action.set("Open page")
                self.app.update_notice.set("The download stalled. Try the page.")
                return
            self.app.root.after(300, lambda: self._await_download(waited + 300))
            return

        reply = self.download_reply[0]
        if isinstance(reply, Exception):
            log_event("update download failed: %s" % reply)
            self.state = "idle"
            self.app.update_action.set("Open page")
            self.app.update_notice.set("Download failed. Try the page instead.")
            return

        self.pending = reply
        self.state = "ready"
        self.app.update_action.set("Restart now")
        self.app.update_notice.set(
            "Downloaded. Gridwyrm will close and reopen updated.")
        log_event("update downloaded to %s" % reply)

    def install_update(self):
        """Hand the swap to a script that outlives this process, then quit."""
        incoming = getattr(self, "pending_update", "")
        if not incoming or not os.path.exists(incoming):
            self.state = "idle"
            self.app.update_action.set("Open page")
            return

        current = os.path.abspath(sys.executable)
        folder = os.path.dirname(current)
        backup = os.path.join(folder, "Gridwyrm.previous.exe")
        script = os.path.join(folder, "gridwyrm-update.bat")

        try:
            # cmd.exe reads a batch file in the system code page, so that is
            # what it gets. A folder with an accent in its name would fail to
            # encode as plain ASCII.
            with open(script, "w", encoding="mbcs", errors="strict") as handle:
                handle.write(swap_script(current, incoming, backup,
                                         os.getpid()))
            creation = 0x00000008 | 0x08000000        # detached, no window
            subprocess.Popen(["cmd", "/c", script], close_fds=True,
                             creationflags=creation, cwd=folder)
        except Exception as error:                    # noqa: BLE001
            log_event("update install failed: %s" % error)
            self.state = "idle"
            self.app.update_action.set("Open page")
            self.app.update_notice.set(
                "Could not start the update. Try the page instead.")
            return

        log_event("update handed to %s, exiting" % script)
        self.app.quit()

    def open_release_page(self):
        try:
            webbrowser.open(self.app.update_url or RELEASES_PAGE)
        except Exception:
            self.app.update_notice.set(RELEASES_PAGE)   # at least show the address

    def dismiss_update(self):
        self.app.update_row.pack_forget()
