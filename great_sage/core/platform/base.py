"""Small interfaces shared by Windows and Linux implementations."""
from abc import ABC, abstractmethod
from typing import Optional

from .capabilities import PlatformCapabilities

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

class Platform(ABC):
    """Common platform contract used by the server and tools."""
    @property
    @abstractmethod
    def hotkey(self): ...
    @property
    @abstractmethod
    def launcher(self): ...
    @property
    @abstractmethod
    def windows(self): ...
    @property
    @abstractmethod
    def paths(self): ...
    @property
    @abstractmethod
    def capabilities(self) -> PlatformCapabilities: ...


class DataPaths(ABC):
    @abstractmethod
    def data_dir(self) -> str: ...
