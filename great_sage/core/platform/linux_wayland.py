"""Wayland/KDE platform adapter.

Uses XDG GlobalShortcuts for global hotkeys and a small KWin bridge for
focused-window information. No global keyboard hooks are used on Wayland.
"""

import asyncio
import logging
import os
import subprocess
import shutil
import sys
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

    def capture_screen(self, output_path: str, region: str = "screen") -> str:
        """Capture the Wayland desktop through KDE Spectacle synchronously."""
        path = str(Path(output_path).expanduser())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        spectacle = shutil.which("spectacle")
        if not spectacle:
            raise RuntimeError(
                "KDE Spectacle is not installed; Wayland screen capture is unavailable."
            )

        mode = (region or "screen").strip().lower()
        capture_mode = "--activewindow" if mode in {"window", "focused", "active"} else "--fullscreen"
        try:
            result = subprocess.run(
                [
                    spectacle, "--background", "--nonotify",
                    capture_mode, "--output", path,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Spectacle timed out while capturing the screen.") from exc

        if result.returncode != 0:
            detail = (result.stderr or "").strip()
            raise RuntimeError(
                "Spectacle failed to capture the screen%s"
                % (f": {detail}" if detail else ".")
            )
        if not Path(path).is_file() or Path(path).stat().st_size == 0:
            raise RuntimeError("Spectacle completed but did not create the screenshot.")
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

    APP_ID = "com.greatsage.GreatSage"

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
        # dbus-fast exposes values of a{sv} dictionaries as Variant objects.
        # The portal declares session_handle as an object path string, so
        # unwrap it before passing it to BindShortcuts.
        if hasattr(session, "value"):
            session = session.value
        if not isinstance(session, str) or not session:
            raise RuntimeError(
                "Global shortcut portal returned no valid session handle."
            )
        return session

    @staticmethod
    def _portal_trigger(binding: str) -> str:
        """Convert the saved HUD combo to XDG shortcut-spec syntax."""
        parts = [p.strip() for p in str(binding or "").replace(" ", "+").split("+") if p.strip()]
        if not parts:
            return ""
        modifiers = {
            "ctrl": "CTRL",
            "control": "CTRL",
            "alt": "ALT",
            "shift": "SHIFT",
            "meta": "LOGO",
            "super": "LOGO",
            "logo": "LOGO",
            "num": "NUM",
        }
        out = []
        for part in parts[:-1]:
            out.append(modifiers.get(part.casefold(), part.upper()))
        return "+".join([*out, parts[-1]])

    async def _bind_shortcuts(self, bus, iface, Variant, session):
        token = f"great_sage_bind_{id(self)}"
        trigger = self._portal_trigger(self.binding)
        if not trigger:
            raise RuntimeError("Push-to-talk binding is empty.")
        # BindShortcuts expects an array of (id, vardict) tuples.
        # Using a dict here makes dbus-fast serialize the tuple's first
        # field incorrectly; with a real tuple the nested a{sv} values
        # are the Variants expected by the portal signature.
        shortcuts = [(
            "activate",
            {
                "description": Variant("s", "Activate Great Sage"),
                "preferred_trigger": Variant("s", trigger),
            },
        )]
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
        bound = results.get("shortcuts") or []
        # dbus-fast exposes a{sv} response values as Variant objects.
        if hasattr(bound, "value"):
            bound = bound.value
        ids = {item[0] for item in bound if item}
        if "activate" not in ids:
            raise RuntimeError(
                f"Global shortcut was not accepted by the desktop portal (requested {trigger!r})."
            )
        return results
    @staticmethod
    def _desktop_field_quote(value: str) -> str:
        # Desktop-entry quoting is not shell quoting.
        return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'

    @classmethod
    def _ensure_host_desktop_entry(cls) -> None:
        """Install a lightweight .desktop identity for the portal registry."""
        apps_dir = Path.home() / ".local" / "share" / "applications"
        apps_dir.mkdir(parents=True, exist_ok=True)
        desktop_path = apps_dir / f"{cls.APP_ID}.desktop"
        repo_root = Path(__file__).resolve().parents[3]
        launcher = repo_root / "run_hud.py"
        exec_line = (
            f"{cls._desktop_field_quote(sys.executable)} "
            f"{cls._desktop_field_quote(launcher)}"
        )
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Great Sage\n"
            f"Exec={exec_line}\n"
            "Terminal=false\n"
            "Categories=Utility;Accessibility;\n"
        )
        try:
            current = desktop_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = None
        if current != content:
            try:
                desktop_path.write_text(content, encoding="utf-8")
            except OSError as exc:
                raise RuntimeError(
                    f"Could not create the Great Sage desktop identity: {exc}"
                ) from exc

    async def _register_host_app(self, bus):
        """Register this unsandboxed process with the XDG portal when supported."""
        try:
            intro = await bus.introspect(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
            )
            proxy = bus.get_proxy_object(
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                intro,
            )
            registry = proxy.get_interface(
                "org.freedesktop.host.portal.Registry"
            )
        except Exception:
            # Older portals may not expose the host registry at all.
            return False

        self._ensure_host_desktop_entry()
        await registry.call_register(self.APP_ID, {})
        return True

    async def _worker(self):
        from dbus_fast import Variant
        from dbus_fast.aio import MessageBus

        bus = await MessageBus().connect()
        try:
            await self._register_host_app(bus)
        except Exception as exc:
            bus.disconnect()
            raise RuntimeError(
                f"Could not register Great Sage with the XDG portal: {exc}"
            ) from exc

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
            if session_handle != self._session or shortcut_id != "activate":
                return
            log.info("Wayland global hotkey ACTIVATED: %s", self.binding)
            if self.on_press:
                try:
                    self.on_press()
                except Exception:
                    log.exception("Voice-key press callback failed")

        def deactivated(session_handle, shortcut_id, timestamp, options):
            if session_handle != self._session or shortcut_id != "activate":
                return
            log.info("Wayland global hotkey DEACTIVATED: %s", self.binding)
            if self.on_release:
                try:
                    self.on_release()
                except Exception:
                    log.exception("Voice-key release callback failed")

        iface.on_activated(activated)
        iface.on_deactivated(deactivated)
        self.active = True
        log.info("Wayland global hotkey ACTIVE: %s", self.binding)
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
            log.exception("Wayland global hotkey worker failed for %s", self.binding)
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
        if not self._ready_event.wait(timeout=10.0):
            self._error = TimeoutError(
                "XDG GlobalShortcuts portal did not finish registering "
                "within 10 seconds; it may be waiting for a desktop shortcut dialog."
            )
            log.error("Wayland global hotkey registration timed out for %s", self.binding)
            return False
        ok = self.active and self._error is None
        if not ok:
            log.error(
                "Wayland global hotkey registration FAILED for %s: %s",
                self.binding,
                self._error,
            )
        return ok

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
