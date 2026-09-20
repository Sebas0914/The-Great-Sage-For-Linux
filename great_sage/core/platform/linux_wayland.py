"""Wayland/KDE platform adapter.

Uses XDG GlobalShortcuts for global hotkeys and a small KWin bridge for
focused-window information. No global keyboard hooks are used on Wayland.
"""
import asyncio
import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Dict, Optional

from platformdirs import user_data_dir

from .base import AppLauncher, DataPaths, Hotkey, WindowInfo


def _desktop_command(args):
    return subprocess.Popen(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True
    )


class LinuxWaylandLauncher(AppLauncher):
    def _desktop_apps(self) -> Dict[str, str]:
        found = {}
        roots = [
            Path.home() / ".local/share/applications",
            Path("/usr/local/share/applications"),
            Path("/usr/share/applications"),
        ]
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
        desktop = apps.get(query)
        if not desktop:
            matches = [(k, p) for k, p in apps.items() if query in k]
            if not matches:
                raise RuntimeError(f"No installed application matches {name!r}.")
            _, desktop = sorted(matches, key=lambda x: len(x[0]))[0]
        _desktop_command(["gio", "launch", desktop])
        return f"Launched {Path(desktop).stem}."

    def open_path(self, path: str) -> str:
        target = Path(os.path.expandvars(os.path.expanduser((path or "").strip())))
        if not target.exists():
            raise RuntimeError(f"Path does not exist: {target}")
        _desktop_command(["xdg-open", str(target)])
        return f"Opened {target}."

    def open_url(self, url: str) -> str:
        value = (url or "").strip()
        if not value:
            raise RuntimeError("No URL given.")
        if "://" not in value:
            value = "https://" + value
        if urllib.parse.urlparse(value).scheme not in {"http", "https"}:
            raise RuntimeError("Only http and https URLs are allowed.")
        _desktop_command(["xdg-open", value])
        return f"Opened {value}."


class LinuxWaylandWindowInfo(WindowInfo):
    def __init__(self):
        self._title = None

    def focused_window_title(self) -> Optional[str]:
        # The KWin bridge is intentionally optional. If it is not active,
        # callers receive None rather than pretending to know the window.
        return self._title

    def set_title(self, title: Optional[str]):
        self._title = title.strip() if isinstance(title, str) and title.strip() else None


class LinuxWaylandDataPaths(DataPaths):
    def data_dir(self) -> str:
        override = os.environ.get("GREAT_SAGE_DATA_DIR")
        if override:
            return os.path.abspath(os.path.expanduser(override))
        return user_data_dir("GreatSage", "GreatSage")


class PortalHotkey(Hotkey):
    """XDG GlobalShortcuts portal adapter.

    The portal owns the actual global shortcut registration. This class keeps
    the D-Bus work on its own event loop thread so the GUI remains responsive.
    """

    def __init__(self, binding="", on_press=None, on_release=None):
        self.binding = binding or "CTRL+ALT+SPACE"
        self.on_press = on_press
        self.on_release = on_release
        self.active = False
        self._loop = None
        self._thread = None
        self._stop_event = None
        self._session = None

    def _run(self):
        try:
            from dbus_fast.aio import MessageBus
            from dbus_fast import Variant
        except ImportError as exc:
            raise RuntimeError("dbus-fast is required for Wayland global shortcuts.") from exc

        async def worker():
            bus = await MessageBus().connect()
            intro = await bus.introspect(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
            )
            proxy = bus.get_proxy_object(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                intro,
            )
            iface = proxy.get_interface("org.freedesktop.portal.GlobalShortcuts")

            handle = f"/com/greatsage/GlobalShortcuts/{id(self)}"
            options = {
                "handle_token": Variant("s", f"great_sage_{id(self)}"),
                "session_handle_token": Variant("s", f"great_sage_session_{id(self)}"),
            }
            result = await iface.call_create_session(options)
            self._session = result
            trigger = self.binding.replace(" ", "+")
            shortcuts = [{
                "id": "activate",
                "description": "Activate Great Sage",
                "preferred_trigger": Variant("s", trigger),
            }]
            # The portal's BindShortcuts request takes a parent window handle
            # followed by shortcut definitions and options. An empty parent is
            # valid for a desktop background utility.
            await iface.call_bind_shortcuts(self._session, shortcuts, "", {})
            self.active = True

            def activated(session_handle, shortcut_id, timestamp, options):
                if session_handle != self._session or shortcut_id != "activate":
                    return
                if self.on_press:
                    self.on_press()

            def deactivated(session_handle, shortcut_id, timestamp, options):
                if session_handle != self._session or shortcut_id != "activate":
                    return
                if self.on_release:
                    self.on_release()

            iface.on_activated(activated)
            iface.on_deactivated(deactivated)
            await asyncio.get_running_loop().run_in_executor(None, self._stop_event.wait)

        asyncio.run(worker())

    def start(self) -> bool:
        if self.active:
            return True
        import threading
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="great-sage-shortcuts")
        self._thread.start()
        return True

    def stop(self) -> None:
        self.active = False
        if self._stop_event:
            self._stop_event.set()
        self._session = None

    def rebind(self, binding: str) -> bool:
        self.stop()
        self.binding = binding
        return self.start()


class LinuxWaylandPlatform:
    def __init__(self, binding=""):
        self._hotkey = PortalHotkey(binding)
        self._windows = LinuxWaylandWindowInfo()

    @property
    def hotkey(self):
        return self._hotkey

    @property
    def launcher(self):
        return LinuxWaylandLauncher()

    @property
    def windows(self):
        return self._windows

    @property
    def paths(self):
        return LinuxWaylandDataPaths()
