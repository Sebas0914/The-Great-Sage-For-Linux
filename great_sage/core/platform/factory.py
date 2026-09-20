"""Select the desktop platform without importing OS-specific APIs elsewhere."""

import atexit
import os

_PLATFORM = None
_PLATFORM_KIND = None


def get_platform(binding="", on_press=None, on_release=None):
    """Return the process-wide platform adapter for the current desktop session."""
    global _PLATFORM, _PLATFORM_KIND

    if os.name == "nt":
        kind = "windows"
        if _PLATFORM is None or _PLATFORM_KIND != kind:
            from .windows import WindowsPlatform
            from great_sage.core.global_hotkey import GlobalHotkey
            hotkey = GlobalHotkey(binding, on_press, on_release)
            _PLATFORM = WindowsPlatform(hotkey)
            _PLATFORM_KIND = kind
    else:
        session = os.environ.get("XDG_SESSION_TYPE", "").lower()
        kind = "linux-x11" if session == "x11" else "linux-wayland"
        if _PLATFORM is None or _PLATFORM_KIND != kind:
            if kind == "linux-x11":
                from .linux_x11 import LinuxX11Platform
                _PLATFORM = LinuxX11Platform(binding)
            else:
                from .linux_wayland import LinuxWaylandPlatform
                _PLATFORM = LinuxWaylandPlatform(binding)
            _PLATFORM_KIND = kind

    _PLATFORM.hotkey.on_press = on_press
    _PLATFORM.hotkey.on_release = on_release
    return _PLATFORM


def close_platform():
    """Release process-wide desktop resources during normal shutdown."""
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
