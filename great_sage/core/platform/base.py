"""Small interfaces shared by Windows and Linux implementations."""
from abc import ABC, abstractmethod
from typing import Optional

class Hotkey(ABC):
    @abstractmethod
    def start(self) -> bool: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def rebind(self, binding: str) -> bool: ...

class AppLauncher(ABC):
    @abstractmethod
    def open_application(self, name: str) -> str: ...
    @abstractmethod
    def open_path(self, path: str) -> str: ...
    @abstractmethod
    def open_url(self, url: str) -> str: ...

class WindowInfo(ABC):
    @abstractmethod
    def focused_window_title(self) -> Optional[str]: ...

class DataPaths(ABC):
    @abstractmethod
    def data_dir(self) -> str: ...
