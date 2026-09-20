"""X11 platform implementation."""
import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Optional
from platformdirs import user_data_dir
from .base import AppLauncher, DataPaths, Hotkey, WindowInfo

class LinuxX11Launcher(AppLauncher):
    def open_application(self, name: str) -> str:
        from .linux_wayland import LinuxWaylandLauncher
        return LinuxWaylandLauncher().open_application(name)
    def open_path(self, path: str) -> str:
        target = Path(os.path.expandvars(os.path.expanduser((path or "").strip())))
        if not target.exists():
            raise RuntimeError(f"Path does not exist: {target}")
        subprocess.Popen(["xdg-open", str(target)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return f"Opened {target}."
    def open_url(self, url: str) -> str:
        value = (url or "").strip()
        if "://" not in value: value = "https://" + value
        if urllib.parse.urlparse(value).scheme not in {"http","https"}:
            raise RuntimeError("Only http and https URLs are allowed.")
        subprocess.Popen(["xdg-open", value], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return f"Opened {value}."

class LinuxX11WindowInfo(WindowInfo):
    def focused_window_title(self) -> Optional[str]:
        try:
            from Xlib import X, display
            d = display.Display()
            root = d.screen().root
            prop = root.get_full_property(d.intern_atom("_NET_ACTIVE_WINDOW"),
                                          X.AnyPropertyType)
            if not prop or not prop.value: return None
            w = d.create_resource_object("window", prop.value[0])
            name = w.get_full_property(d.intern_atom("_NET_WM_NAME"),
                                       X.AnyPropertyType)
            return (name.value.decode("utf-8", errors="replace").strip()
                    if name and name.value else None)
        except Exception:
            return None

class LinuxX11DataPaths(DataPaths):
    def data_dir(self) -> str:
        override = os.environ.get("GREAT_SAGE_DATA_DIR")
        if override: return os.path.abspath(os.path.expanduser(override))
        return user_data_dir("GreatSage", "GreatSage")

class X11Hotkey(Hotkey):
    def __init__(self, binding="", on_press=None, on_release=None):
        self.binding=binding; self.on_press=on_press; self.on_release=on_release
        self.active=False
    def start(self) -> bool:
        raise RuntimeError("X11 hotkey integration is not enabled in Phase 1.")
    def stop(self) -> None: self.active=False
    def rebind(self, binding: str) -> bool:
        self.binding=binding
        return self.start()

class LinuxX11Platform:
    def __init__(self, binding=""):
        self._hotkey=X11Hotkey(binding)
    @property
    def hotkey(self): return self._hotkey
    @property
    def launcher(self): return LinuxX11Launcher()
    @property
    def windows(self): return LinuxX11WindowInfo()
    @property
    def paths(self): return LinuxX11DataPaths()
