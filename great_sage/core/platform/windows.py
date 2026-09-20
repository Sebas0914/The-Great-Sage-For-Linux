"""Thin Windows adapter around the existing Windows-specific code."""
import os
from typing import Optional
from platformdirs import user_data_dir
from .base import AppLauncher, DataPaths, Hotkey, WindowInfo

class WindowsLauncher(AppLauncher):
    def open_application(self, name): 
        from great_sage.core import tools
        return tools._open_application(name)
    def open_path(self, path):
        from great_sage.core import tools
        return tools._open_folder(path)
    def open_url(self, url):
        from great_sage.core import tools
        return tools._open_url(url)

class WindowsWindowInfo(WindowInfo):
    def focused_window_title(self) -> Optional[str]:
        from great_sage.core import tools
        return tools._focused_window()

class WindowsDataPaths(DataPaths):
    def data_dir(self) -> str:
        override=os.environ.get("GREAT_SAGE_DATA_DIR")
        if override: return os.path.abspath(os.path.expanduser(override))
        return user_data_dir("GreatSage","GreatSage")

class WindowsPlatform:
    def __init__(self, hotkey):
        self._hotkey=hotkey
    @property
    def hotkey(self): return self._hotkey
    @property
    def launcher(self): return WindowsLauncher()
    @property
    def windows(self): return WindowsWindowInfo()
    @property
    def paths(self): return WindowsDataPaths()
