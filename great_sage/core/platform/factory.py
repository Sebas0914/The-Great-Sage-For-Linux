"""Select the platform adapter from the current OS/session.

The factory deliberately does not assume KDE. Linux is split by display
server (Wayland/X11), while the desktop environment is only a capability
hint for optional integrations such as KWin.
"""

import atexit
import os

from .detector import display_server, os_name

_PLATFORM = None
_PLATFORM_KIND = None


def _kind():
    system = os_name()
    if system == "windows":
        return "windows"
    if system == "linux":
        display = display_server()
        if display == "x11":
            return "linux-x11"
        if display == "wayland":
            return "linux-wayland"
        return "linux-unknown"
    return system


def get_platform(binding="", on_press=None, on_release=None):
    global _PLATFORM, _PLATFORM_KIND
    kind = _kind()

    if _PLATFORM is None or _PLATFORM_KIND != kind:
        if kind == "windows":
            from .windows import WindowsPlatform
            from great_sage.core.global_hotkey import GlobalHotkey
            _PLATFORM = WindowsPlatform(GlobalHotkey(binding, on_press, on_release))
        elif kind == "linux-x11":
            from .linux_x11 import LinuxX11Platform
            _PLATFORM = LinuxX11Platform(binding)
        elif kind == "linux-wayland":
            from .linux_wayland import LinuxWaylandPlatform
            _PLATFORM = LinuxWaylandPlatform(binding)
        elif kind == "linux-unknown":
            # A Linux process without a desktop session can still use
            # headless-safe tools and file access. No fake X11/Wayland APIs.
            from .linux_x11 import LinuxX11Platform
            _PLATFORM = LinuxX11Platform(binding)
            _PLATFORM_KIND = kind
            _PLATFORM.hotkey.active = False
            _PLATFORM.hotkey.start = lambda: False
        else:
            raise RuntimeError(f"Unsupported Great Sage platform: {kind}")

        _PLATFORM_KIND = kind

    _PLATFORM.hotkey.on_press = on_press
    _PLATFORM.hotkey.on_release = on_release
    return _PLATFORM


def close_platform():
    global _PLATFORM, _PLATFORM_KIND
    platform = _PLATFORM
    _PLATFORM = None
    _PLATFORM_KIND = None
    if platform is None:
        return
    try:
        platform.hotkey.stop()
    except Exception:
        pass
    try:
        windows = platform.windows
        stop = getattr(windows, "stop", None)
        if stop:
            stop()
    except Exception:
        pass


atexit.register(close_platform)
