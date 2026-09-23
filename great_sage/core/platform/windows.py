"""Windows platform adapter.

Keeps the existing Windows-specific behaviour behind the platform boundary.
"""

import os
import webbrowser
from typing import Optional

from platformdirs import user_data_dir

from .base import AppLauncher, DataPaths, Hotkey, WindowInfo


class WindowsLauncher(AppLauncher):
    def open_application(self, name: str) -> str:
        from great_sage.core import tools
        target = tools._resolve_app(name)
        if not target:
            raise RuntimeError(
                "No installed application matches %r. It is not in the Start "
                "Menu, so there is nothing to launch." % name
            )
        try:
            os.startfile(target)
        except Exception as exc:
            raise RuntimeError("Could not launch %s: %s" % (name, exc)) from exc
        return "Launched %s." % os.path.splitext(os.path.basename(target))[0]

    def open_path(self, path: str) -> str:
        p = os.path.expandvars(os.path.expanduser((path or "").strip()))
        if not p:
            raise RuntimeError("No folder given.")
        if not os.path.exists(p):
            leaf = os.path.basename(p.rstrip("/" + chr(92))) or p
            candidate = os.path.join(os.path.expanduser("~"), leaf)
            if os.path.isdir(candidate):
                p = candidate
            else:
                raise RuntimeError(
                    "No folder called %r was found in your user folder." % leaf
                )
        try:
            os.startfile(p if os.path.isdir(p) else os.path.dirname(p))
        except Exception as exc:
            raise RuntimeError("Could not open %s" % p) from exc
        return "Opened %s." % p

    def open_url(self, url: str) -> str:
        value = (url or "").strip()
        if not value:
            raise RuntimeError("No URL given.")
        low = value.lower()
        if not low.startswith(("http://", "https://")):
            if "://" in value:
                raise RuntimeError("Refused: only http and https can be opened.")
            value = "https://" + value
        if not webbrowser.open(value):
            raise RuntimeError("No browser available to open %s." % value)
        return "Opened %s." % value


class WindowsWindowInfo(WindowInfo):
    def focused_window_title(self) -> Optional[str]:
        try:
            import ctypes
            import ctypes.wintypes as wt
            u = ctypes.windll.user32
            length = u.GetWindowTextLengthW(u.GetForegroundWindow())
            buf = ctypes.create_unicode_buffer(length + 1)
            u.GetWindowTextW(u.GetForegroundWindow(), buf, length + 1)
            return buf.value.strip() or None
        except Exception:
            return None


class WindowsDataPaths(DataPaths):
    def data_dir(self) -> str:
        override = os.environ.get("GREAT_SAGE_DATA_DIR")
        if override:
            return os.path.abspath(os.path.expanduser(override))
        return user_data_dir("GreatSage", "GreatSage")


class WindowsPlatform:
    def __init__(self, hotkey):
        self._hotkey = hotkey

    @property
    def hotkey(self):
        return self._hotkey

    @property
    def launcher(self):
        return WindowsLauncher()

    @property
    def windows(self):
        return WindowsWindowInfo()

    @property
    def paths(self):
        return WindowsDataPaths()
