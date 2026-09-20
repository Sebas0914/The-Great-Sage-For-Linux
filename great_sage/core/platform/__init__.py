"""Platform abstractions for Great Sage."""
from .base import AppLauncher, DataPaths, Hotkey, WindowInfo
from .linux_wayland import LinuxWaylandPlatform
from .linux_x11 import LinuxX11Platform
from .windows import WindowsPlatform

__all__ = ["AppLauncher", "DataPaths", "Hotkey", "WindowInfo",
           "LinuxWaylandPlatform", "LinuxX11Platform", "WindowsPlatform"]

from .factory import get_platform
