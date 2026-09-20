"""Select the desktop platform without importing OS-specific APIs elsewhere."""

import os


def get_platform(binding="", on_press=None, on_release=None):
    """Return the platform adapter for the current desktop session."""
    if os.name == "nt":
        from .windows import WindowsPlatform
        from great_sage.core.global_hotkey import GlobalHotkey

        hotkey = GlobalHotkey(
            binding,
            on_press=on_press,
            on_release=on_release,
        )
        return WindowsPlatform(hotkey)

    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session == "x11":
        from .linux_x11 import LinuxX11Platform

        platform = LinuxX11Platform(binding)
    else:
        from .linux_wayland import LinuxWaylandPlatform

        platform = LinuxWaylandPlatform(binding)

    platform.hotkey.on_press = on_press
    platform.hotkey.on_release = on_release
    return platform
