"""Wayland/KDE platform adapter.

Uses XDG GlobalShortcuts for global hotkeys and a small KWin bridge for
focused-window information. No global keyboard hooks are used on Wayland.
"""

import asyncio
import os
import subprocess
import shutil
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

    def capture_screen(self, output_path: str) -> str:
        """Capture the Wayland desktop through KDE Spectacle."""
        path = str(Path(output_path).expanduser())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if not shutil.which("spectacle"):
            raise RuntimeError(
                "KDE Spectacle is not installed; Wayland screen capture is unavailable."
            )
        _desktop_command([
            "spectacle", "--background", "--nonotify",
            "--fullscreen", "--output", path,
        ])
        if not Path(path).is_file():
            raise RuntimeError("Spectacle did not create the screenshot.")
        return path


class _KWinBridge:
    """Small D-Bus service receiving active-window updates from KWin."""

    SERVICE = "org.greatsage.KWinBridge"
    PATH = "/org/greatsage/KWinBridge"
    INTERFACE = "org.greatsage.KWinBridge"

    def __init__(self, window_info):
        self.window_info = window_info
        self._thread = None
        self._stop = None
        self._ready = None
        self.error = None

    def start(self) -> bool:
        import threading
        if self._thread and self._thread.is_alive():
            return self.error is None
        self.error = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="great-sage-kwin-bridge"
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return self.error is None

    def _run(self):
        try:
            asyncio.run(self._serve())
        except Exception as exc:
            self.error = exc
            if self._ready:
                self._ready.set()

    async def _serve(self):
        from dbus_fast.aio import MessageBus
        from dbus_fast.service import ServiceInterface, method

        owner = self

        class BridgeInterface(ServiceInterface):
            def __init__(self):
                super().__init__(owner.INTERFACE)

            @method()
            def SetActiveWindow(self, title: "s", pid: "i") -> None:
                owner.window_info.set_title(title)
                owner.window_info.set_pid(pid)

        bus = await MessageBus().connect()
        await bus.request_name(self.SERVICE)
        bus.export(self.PATH, BridgeInterface())
        if self._ready:
            self._ready.set()
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self._stop.wait
            )
        finally:
            bus.unexport(self.PATH)
            bus.disconnect()

    def stop(self):
        if self._stop:
            self._stop.set()


class LinuxWaylandWindowInfo(WindowInfo):
    def __init__(self):
        self._title = None
        self._pid = None
        self._bridge = _KWinBridge(self)
        self._bridge.start()

    def focused_window_title(self) -> Optional[str]:
        return self._title

    def set_title(self, title: Optional[str]):
        self._title = title.strip() if isinstance(title, str) and title.strip() else None

    def set_pid(self, pid: int):
        try:
            self._pid = int(pid)
        except (TypeError, ValueError):
            self._pid = None

    @property
    def bridge_error(self):
        return self._bridge.error

    def stop(self):
        self._bridge.stop()


class LinuxWaylandDataPaths(DataPaths):
    def data_dir(self) -> str:
        override = os.environ.get("GREAT_SAGE_DATA_DIR")
        if override:
            return os.path.abspath(os.path.expanduser(override))
        return user_data_dir("GreatSage", "GreatSage")


class PortalHotkey(Hotkey):
    """XDG GlobalShortcuts portal adapter.

    Portal requests return Request object paths. Their actual results arrive
    through org.freedesktop.portal.Request::Response; the request handle is
    never treated as the session handle.
    """

    def __init__(self, binding="", on_press=None, on_release=None):
        self.binding = binding or "CTRL+ALT+SPACE"
        self.on_press = on_press
        self.on_release = on_release
        self.active = False
        self._thread = None
        self._stop_event = None
        self._session = None
        self._bus = None
        self._error = None
        self._ready_event = None

    @staticmethod
    def _request_path(bus, token: str) -> str:
        sender = (bus.unique_name or "").lstrip(":").replace(".", "_")
        return f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

    async def _wait_response(self, bus, request_path):
        intro = await bus.introspect(
            "org.freedesktop.portal.Desktop", request_path
        )
        proxy = bus.get_proxy_object(
            "org.freedesktop.portal.Desktop", request_path, intro
        )
        iface = proxy.get_interface("org.freedesktop.portal.Request")
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def response(code, results):
            if not future.done():
                future.set_result((code, results))

        iface.on_response(response)
        return future

    async def _create_session(self, bus, iface, Variant):
        token = f"great_sage_{id(self)}"
        request_path = await iface.call_create_session({
            "handle_token": Variant("s", token),
            "session_handle_token": Variant(
                "s", f"great_sage_session_{id(self)}"
            ),
        })
        future = await self._wait_response(bus, request_path)
        code, results = await future
        if code != 0:
            raise RuntimeError(
                f"Global shortcut session request failed with response {code}."
            )
        session = results.get("session_handle")
        if not session:
            raise RuntimeError(
                "Global shortcut portal returned no session handle."
            )
        return session

    async def _bind_shortcuts(self, bus, iface, Variant, session):
        token = f"great_sage_bind_{id(self)}"
        shortcuts = [{
            "id": "activate",
            "description": "Activate Great Sage",
            "preferred_trigger": Variant(
                "s", self.binding.replace(" ", "+")
            ),
        }]
        request_path = await iface.call_bind_shortcuts(
            session, shortcuts, "",
            {"handle_token": Variant("s", token)}
        )
        future = await self._wait_response(bus, request_path)
        code, results = await future
        if code != 0:
            raise RuntimeError(
                f"Global shortcut binding request failed with response {code}."
            )
        return results

    async def _worker(self):
        from dbus_fast import Variant
        from dbus_fast.aio import MessageBus

        bus = await MessageBus().connect()
        self._bus = bus
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

        self._session = await self._create_session(bus, iface, Variant)
        await self._bind_shortcuts(bus, iface, Variant, self._session)

        def activated(session_handle, shortcut_id, timestamp, options):
            if session_handle == self._session and shortcut_id == "activate":
                if self.on_press:
                    self.on_press()

        def deactivated(session_handle, shortcut_id, timestamp, options):
            if session_handle == self._session and shortcut_id == "activate":
                if self.on_release:
                    self.on_release()

        iface.on_activated(activated)
        iface.on_deactivated(deactivated)
        self.active = True
        if self._ready_event:
            self._ready_event.set()
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, self._stop_event.wait
            )
        finally:
            try:
                session_intro = await bus.introspect(
                    "org.freedesktop.portal.Desktop", self._session
                )
                session_proxy = bus.get_proxy_object(
                    "org.freedesktop.portal.Desktop",
                    self._session,
                    session_intro,
                )
                session_iface = session_proxy.get_interface(
                    "org.freedesktop.portal.Session"
                )
                await session_iface.call_close()
            except Exception:
                pass
            self._session = None
            self._bus = None
            bus.disconnect()

    def _run(self):
        try:
            asyncio.run(self._worker())
        except Exception as exc:
            self.active = False
            self._error = exc
            if self._ready_event:
                self._ready_event.set()

    def start(self) -> bool:
        if self.active:
            return True
        import threading
        self._error = None
        self._ready_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="great-sage-shortcuts"
        )
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
