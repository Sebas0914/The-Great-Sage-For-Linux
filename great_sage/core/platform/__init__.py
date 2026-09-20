"""Platform abstractions for Great Sage.

OS-specific implementations are loaded lazily. This keeps importing the
platform package safe on Linux even when Windows-only dependencies are not
available, and keeps the platform factory as the normal entry point.
"""

from .base import AppLauncher, DataPaths, Hotkey, WindowInfo
from .factory import get_platform

__all__ = [
    "AppLauncher",
    "DataPaths",
    "Hotkey",
    "WindowInfo",
    "LinuxWaylandPlatform",
    "LinuxX11Platform",
    "WindowsPlatform",
    "get_platform",
]


def __getattr__(name):
    """Load an OS-specific implementation only when it is actually requested."""
    if name == "LinuxWaylandPlatform":
        from .linux_wayland import LinuxWaylandPlatform
        return LinuxWaylandPlatform
    if name == "LinuxX11Platform":
        from .linux_x11 import LinuxX11Platform
        return LinuxX11Platform
    if name == "WindowsPlatform":
        from .windows import WindowsPlatform
        return WindowsPlatform
    raise AttributeError(name)
