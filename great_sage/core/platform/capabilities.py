"""Best-effort capability discovery.

Capabilities describe what the current session can safely provide. A missing
capability is normal on Linux, especially under Wayland; callers should fall
back instead of assuming KDE/X11 APIs exist.
"""

from dataclasses import dataclass
import shutil

from .detector import display_server, desktop_environment, os_name


@dataclass(frozen=True)
class PlatformCapabilities:
    global_hotkey: bool
    screen_capture: bool
    focused_window: bool
    window_management: bool
    always_on_top: bool
    desktop: str
    display_server: str
    os: str


def detect_capabilities() -> PlatformCapabilities:
    os_kind = os_name()
    display = display_server()
    desktop = desktop_environment()

    if os_kind == "windows":
        return PlatformCapabilities(True, True, True, True, True, desktop, display, os_kind)

    if os_kind == "linux":
        capture = bool(shutil.which("grim") or shutil.which("spectacle"))
        if display == "x11":
            return PlatformCapabilities(
                True, capture, True, True, True, desktop, display, os_kind
            )
        if display == "wayland":
            # GlobalShortcuts is portal/desktop dependent. The adapter will
            # verify it at runtime; this flag means it is potentially usable.
            portal_hotkey = bool(shutil.which("dbus-send") or shutil.which("gdbus"))
            return PlatformCapabilities(
                portal_hotkey, capture, desktop == "kde", False, False,
                desktop, display, os_kind
            )

    return PlatformCapabilities(False, False, False, False, False, desktop, display, os_kind)
