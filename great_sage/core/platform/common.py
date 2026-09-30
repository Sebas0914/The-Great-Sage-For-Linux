"""Desktop-independent Linux helpers shared by X11 and Wayland."""

import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Dict

from platformdirs import user_data_dir

from .base import AppLauncher, DataPaths


def desktop_apps() -> Dict[str, str]:
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


def launch(args):
    return subprocess.Popen(
        args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )


class LinuxLauncher(AppLauncher):
    def open_application(self, name: str) -> str:
        query = (name or "").strip().casefold()
        if not query:
            raise RuntimeError("No application name given.")
        apps = desktop_apps()
        desktop = apps.get(query)
        if not desktop:
            matches = [(k, p) for k, p in apps.items() if query in k]
            if not matches:
                raise RuntimeError(f"No installed application matches {name!r}.")
            _, desktop = sorted(matches, key=lambda x: len(x[0]))[0]
        if shutil_which("gio"):
            launch(["gio", "launch", desktop])
        else:
            launch(["gtk-launch", Path(desktop).stem])
        return f"Launched {Path(desktop).stem}."

    def open_path(self, path: str) -> str:
        target = Path(os.path.expandvars(os.path.expanduser((path or "").strip())))
        if not target.exists():
            raise RuntimeError(f"Path does not exist: {target}")
        launch(["xdg-open", str(target)])
        return f"Opened {target}."

    def open_url(self, url: str) -> str:
        value = (url or "").strip()
        if not value:
            raise RuntimeError("No URL given.")
        if "://" not in value:
            value = "https://" + value
        if urllib.parse.urlparse(value).scheme not in {"http", "https"}:
            raise RuntimeError("Only http and https URLs are allowed.")
        launch(["xdg-open", value])
        return f"Opened {value}."


def shutil_which(command: str):
    import shutil
    return shutil.which(command)


class LinuxDataPaths(DataPaths):
    def data_dir(self) -> str:
        override = os.environ.get("GREAT_SAGE_DATA_DIR")
        if override:
            return os.path.abspath(os.path.expanduser(override))
        return user_data_dir("GreatSage", "GreatSage")
