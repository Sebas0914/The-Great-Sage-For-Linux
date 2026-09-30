"""Runtime detection for Linux/Windows desktop environments.

Detection is capability-oriented: desktop environment and display server are
hints used to select adapters, never hard requirements.
"""

import os
import platform as _platform


def os_name() -> str:
    if os.name == "nt":
        return "windows"
    if _platform.system().lower() == "linux":
        return "linux"
    return _platform.system().lower() or "unknown"


def display_server() -> str:
    value = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if value in {"wayland", "x11"}:
        return value
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def desktop_environment() -> str:
    value = (
        os.environ.get("XDG_CURRENT_DESKTOP")
        or os.environ.get("XDG_SESSION_DESKTOP")
        or os.environ.get("DESKTOP_SESSION")
        or ""
    )
    value = value.strip().lower()
    if ":" in value:
        value = value.split(":", 1)[0]
    aliases = {
        "kde": "kde",
        "plasma": "kde",
        "gnome": "gnome",
        "ubuntu": "gnome",
        "xfce": "xfce",
        "x-cinnamon": "cinnamon",
        "cinnamon": "cinnamon",
        "mate": "mate",
        "lxqt": "lxqt",
        "lxde": "lxde",
        "budgie": "budgie",
        "deepin": "deepin",
    }
    return aliases.get(value, value or "unknown")


def is_kde() -> bool:
    return desktop_environment() == "kde"


def summary() -> dict:
    return {
        "os": os_name(),
        "display_server": display_server(),
        "desktop_environment": desktop_environment(),
    }
