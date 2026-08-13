"""Asking GitHub about newer releases, and installing one."""

import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request


VERSION = "2.1"


UPDATE_API = "https://api.github.com/repos/LMMRZWG/Gridwyrm/releases/latest"


RELEASES_PAGE = "https://github.com/LMMRZWG/Gridwyrm/releases/latest"


UPDATE_INTERVAL_HOURS = 20


TRUSTED_DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com",
                          "release-assets.githubusercontent.com")


def download_is_trusted(url):
    """Whether a URL is somewhere we are willing to fetch a program from."""
    try:
        parts = urllib.parse.urlsplit(str(url))
    except Exception:
        return False
    if parts.scheme != "https":
        return False
    host = (parts.hostname or "").lower()
    return (host in TRUSTED_DOWNLOAD_HOSTS
            or host.endswith(".githubusercontent.com"))


def parse_version(text):
    """'v2.1.3' becomes (2, 1, 3). None when it cannot be read.

    Tolerates a leading v, a trailing suffix such as -beta, and any number of
    parts, because a tag is typed by hand and will not always be tidy.
    """
    if not text:
        return None
    cleaned = str(text).strip().lstrip("vV").split("+")[0].split("-")[0]
    parts = cleaned.split(".")
    numbers = []
    for part in parts:
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            return None
        numbers.append(int(digits))
    return tuple(numbers) if numbers else None


def is_newer(candidate, current):
    """True when candidate names a later version than current.

    Missing parts count as zero, so 2.1 beats 2.0.9 and matches 2.1.0. An
    unreadable version is never treated as newer: better to miss an update than
    to nag about one that does not exist.
    """
    left, right = parse_version(candidate), parse_version(current)
    if left is None or right is None:
        return False
    length = max(len(left), len(right))
    left += (0,) * (length - len(left))
    right += (0,) * (length - len(right))
    return left > right


def read_latest_release(url=UPDATE_API, timeout=6.0):
    """Ask GitHub for the newest release.

    Returns a dict with the tag, the page, and the .exe asset if the release has
    one. Raises on any failure, which the caller swallows: an update check that
    complains when the network is down is worse than no update check.
    """
    request = urllib.request.Request(url, headers={
        # GitHub refuses requests without one of these.
        "User-Agent": "Gridwyrm/%s" % VERSION,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))

    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("no tag_name in the reply")

    asset = None
    for item in payload.get("assets") or []:
        name = str(item.get("name") or "")
        link = str(item.get("browser_download_url") or "")
        if name.lower().endswith(".exe") and download_is_trusted(link):
            asset = {"name": name, "url": link,
                     "size": int(item.get("size") or 0)}
            break

    return {"tag": tag,
            "page": str(payload.get("html_url") or RELEASES_PAGE),
            "asset": asset}


def download_release_asset(url, destination, expected_size=0, timeout=120.0):
    """Fetch the new program to a file beside the current one.

    The declared size is checked afterwards, because a download cut short by a
    dropped connection would otherwise be installed as though it were whole.
    """
    if not download_is_trusted(url):
        raise ValueError("refusing to download from %s" % url)
    request = urllib.request.Request(
        url, headers={"User-Agent": "Gridwyrm/%s" % VERSION})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with open(destination, "wb") as handle:
            shutil.copyfileobj(response, handle, 128 * 1024)
    size = os.path.getsize(destination)
    if expected_size and size != expected_size:
        os.remove(destination)
        raise ValueError("got %d bytes, expected %d" % (size, expected_size))
    if size < 1024:
        os.remove(destination)
        raise ValueError("the download was empty")
    return size


def swap_script(current, incoming, backup, pid):
    """A batch file that replaces the program once this copy has exited.

    Windows will not let a running executable overwrite itself, so the swap has
    to outlive the process doing it. The old copy is kept as a backup and put
    straight back if the replacement fails, so a bad moment cannot leave someone
    with nothing that runs.
    """
    return "\r\n".join([
        "@echo off",
        "rem Written by Gridwyrm to finish an update. Safe to delete.",
        ":wait",
        'tasklist /fi "PID eq %d" 2>nul | find "%d" >nul' % (pid, pid),
        "if not errorlevel 1 (",
        "  ping -n 2 127.0.0.1 >nul",
        "  goto wait",
        ")",
        'if exist "%s" del /q "%s"' % (backup, backup),
        'move /y "%s" "%s" >nul' % (current, backup),
        'move /y "%s" "%s" >nul' % (incoming, current),
        'if not exist "%s" move /y "%s" "%s" >nul' % (current, backup, current),
        'start "" "%s"' % current,
        'del /q "%~f0"',
        "",
    ])


def update_check_due(last_checked, now=None, hours=UPDATE_INTERVAL_HOURS):
    """Whether enough time has passed. Also guards against a clock that moved."""
    now = time.time() if now is None else now
    try:
        last = float(last_checked)
    except (TypeError, ValueError):
        return True
    if last > now:
        return True                              # clock changed, so check again
    return (now - last) >= hours * 3600
