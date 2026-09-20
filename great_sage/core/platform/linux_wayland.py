"""Wayland/KDE platform implementation.

Phase 1 keeps Wayland behavior conservative: standard desktop launchers are
used for apps, paths and URLs; focused-window information is optional.
Global shortcuts have a dedicated boundary and never fall back to a
keyboard hook.
"""
import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Dict, Optional
from platformdirs import user_data_dir
from .base import AppLauncher, DataPaths, Hotkey, WindowInfo

def _desktop_command(args):
    return subprocess.Popen(args, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True)

class LinuxWaylandLauncher(AppLauncher):
    def _desktop_apps(self) -> Dict[str, str]:
        found = {}
        roots = [Path.home()/".local/share/applications",
                 Path("/usr/local/share/applications"),
                 Path("/usr/share/applications")]
        for root in roots:
            if not root.is_dir():
                continue
            for desktop in root.glob("*.desktop"):
                try:
                    text = desktop.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                name = None
                hidden = no_display = False
                for line in text.splitlines():
                    if line.startswith("Name="):
                        name = line[5:].strip()
                    elif line == "Hidden=true":
                        hidden = True
                    elif line == "NoDisplay=true":
                        no_display = True
                if name and not hidden and not no_display:
                    found.setdefault(name.casefold(), str(desktop))
        return found

    def open_application(self, name: str) -> str:
        query = (name or "").strip().casefold()
        if not query:
            raise RuntimeError("No application name given.")
        apps = self._desktop_apps()
        if query in apps:
            desktop = apps[query]
        else:
            matches = [(k,p) for k,p in apps.items() if query in k]
            if not matches:
                raise RuntimeError(f"No installed application matches {name!r}.")
            _, desktop = sorted(matches, key=lambda x: len(x[0]))[0]
        _desktop_command(["gio", "launch", desktop])
        return f"Launched {Path(desktop).stem}."

    def open_path(self, path: str) -> str:
        target = Path(os.path.expandvars(os.path.expanduser((path or "").strip())))
        if not target.exists():
            leaf = target.name
            candidate = Path.home()/leaf
            if candidate.is_dir():
                target = candidate
            else:
                raise RuntimeError(f"Path does not exist: {target}")
        _desktop_command(["xdg-open", str(target)])
        return f"Opened {target}."

    def open_url(self, url: str) -> str:
        value = (url or "").strip()
        if not value:
            raise RuntimeError("No URL given.")
        if "://" not in value:
            value = "https://" + value
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError("Only http and https URLs are allowed.")
        _desktop_command(["xdg-open", value])
        return f"Opened {value}."

class LinuxWaylandWindowInfo(WindowInfo):
    def focused_window_title(self) -> Optional[str]:
        return None

class LinuxWaylandDataPaths(DataPaths):
    def data_dir(self) -> str:
        override = os.environ.get("GREAT_SAGE_DATA_DIR")
        if override:
            return os.path.abspath(os.path.expanduser(override))
        return user_data_dir("GreatSage", "GreatSage")

class PortalHotkey(Hotkey):
    """Explicit boundary for XDG GlobalShortcuts.

    It intentionally does not fall back to a keyboard hook. The portal
    binding is integrated after the rest of the Linux port is stable.
    """
    def __init__(self, binding="", on_press=None, on_release=None):
        self.binding = binding
        self.on_press = on_press
        self.on_release = on_release
        self.active = False
    def start(self) -> bool:
        raise RuntimeError("Wayland GlobalShortcuts portal is not initialized.")
    def stop(self) -> None:
        self.active = False
    def rebind(self, binding: str) -> bool:
        self.binding = binding
        return self.start()

class LinuxWaylandPlatform:
    def __init__(self, binding=""):
        self._hotkey = PortalHotkey(binding)
    @property
    def hotkey(self): return self._hotkey
    @property
    def launcher(self): return LinuxWaylandLauncher()
    @property
    def windows(self): return LinuxWaylandWindowInfo()
    @property
    def paths(self): return LinuxWaylandDataPaths()
