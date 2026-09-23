"""X11 platform implementation.

The X11 hotkey grabs exactly one configured key combination through XGrabKey.
It does not inspect arbitrary keyboard input.
"""

import os
import select
import subprocess
import threading
import urllib.parse
from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir

from .base import AppLauncher, DataPaths, Hotkey, WindowInfo


class LinuxX11Launcher(AppLauncher):
    def open_application(self, name: str) -> str:
        from .linux_wayland import LinuxWaylandLauncher
        return LinuxWaylandLauncher().open_application(name)

    def open_path(self, path: str) -> str:
        target = Path(os.path.expandvars(os.path.expanduser((path or "").strip())))
        if not target.exists():
            raise RuntimeError(f"Path does not exist: {target}")
        subprocess.Popen(
            ["xdg-open", str(target)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"Opened {target}."

    def open_url(self, url: str) -> str:
        value = (url or "").strip()
        if not value:
            raise RuntimeError("No URL given.")
        if "://" not in value:
            value = "https://" + value
        if urllib.parse.urlparse(value).scheme not in {"http", "https"}:
            raise RuntimeError("Only http and https URLs are allowed.")
        subprocess.Popen(
            ["xdg-open", value],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"Opened {value}."


class LinuxX11WindowInfo(WindowInfo):
    def focused_window_title(self) -> Optional[str]:
        try:
            from Xlib import X, display

            d = display.Display()
            try:
                root = d.screen().root
                prop = root.get_full_property(
                    d.intern_atom("_NET_ACTIVE_WINDOW"),
                    X.AnyPropertyType,
                )
                if not prop or not prop.value:
                    return None
                window = d.create_resource_object("window", prop.value[0])
                name = window.get_full_property(
                    d.intern_atom("_NET_WM_NAME"),
                    X.AnyPropertyType,
                )
                if name and name.value:
                    value = name.value
                    if isinstance(value, bytes):
                        return value.decode("utf-8", errors="replace").strip() or None
                    return str(value).strip() or None

                # Older X11 clients may expose only the legacy title property.
                legacy = window.get_full_property(
                    d.intern_atom("WM_NAME"),
                    X.AnyPropertyType,
                )
                if legacy and legacy.value:
                    value = legacy.value
                    if isinstance(value, bytes):
                        return value.decode("utf-8", errors="replace").strip() or None
                    return str(value).strip() or None
                return None
            finally:
                d.close()
        except Exception:
            return None


class LinuxX11DataPaths(DataPaths):
    def data_dir(self) -> str:
        override = os.environ.get("GREAT_SAGE_DATA_DIR")
        if override:
            return os.path.abspath(os.path.expanduser(override))
        return user_data_dir("GreatSage", "GreatSage")


class X11Hotkey(Hotkey):
    """Single-combination global hotkey using XGrabKey.

    Only the configured key combination is intercepted. The implementation
    never installs a global key hook and never records arbitrary keystrokes.
    """

    _MODIFIERS = {
        "ctrl": 0x04,
        "control": 0x04,
        "shift": 0x01,
        "alt": 0x08,
        "meta": 0x40,
        "super": 0x40,
        "win": 0x40,
    }

    def __init__(self, binding="", on_press=None, on_release=None):
        self.binding = binding or "CTRL+ALT+SPACE"
        self.on_press = on_press
        self.on_release = on_release
        self.active = False
        self._thread = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._ok = False
        self._display = None
        self._root = None
        self._keycode = None
        self._mods = None
        self._grab_masks = ()

    @classmethod
    def _parse(cls, binding, X, XK, display):
        parts = [p.strip().lower() for p in (binding or "").split("+") if p.strip()]
        if not parts:
            return None

        mods = 0
        key_name = None
        for part in parts:
            if part in cls._MODIFIERS:
                mods |= cls._MODIFIERS[part]
            elif key_name is None:
                key_name = part
            else:
                return None
        if key_name is None:
            return None

        aliases = {
            "space": "space",
            "enter": "Return",
            "return": "Return",
            "escape": "Escape",
            "esc": "Escape",
            "tab": "Tab",
            "backspace": "BackSpace",
            "delete": "Delete",
            "insert": "Insert",
            "home": "Home",
            "end": "End",
            "pageup": "Page_Up",
            "pagedown": "Page_Down",
            "up": "Up",
            "down": "Down",
            "left": "Left",
            "right": "Right",
        }
        keysym_name = aliases.get(key_name, key_name.upper() if len(key_name) == 1 else key_name)
        if len(key_name) == 1:
            keysym_name = key_name
        keysym = XK.string_to_keysym(keysym_name)
        if not keysym:
            return None
        keycode = display.keysym_to_keycode(keysym)
        if not keycode:
            return None
        return mods, keycode

    def start(self) -> bool:
        if self.active:
            return True
        self.stop()
        self._stop.clear()
        self._ready.clear()
        self._ok = False
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="great-sage-x11-hotkey",
        )
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return self._ok

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.active = False

    def rebind(self, binding: str) -> bool:
        previous = self.binding
        if (binding or "").strip().lower() == (previous or "").strip().lower():
            return True
        self.stop()
        self.binding = binding
        if self.start():
            return True
        self.binding = previous
        self.start()
        return False

    def _run(self):
        try:
            from Xlib import X, XK, display

            d = display.Display()
            root = d.screen().root
            parsed = self._parse(self.binding, X, XK, d)
            if parsed is None:
                raise RuntimeError(f"Unsupported X11 hotkey binding: {self.binding!r}")

            mods, keycode = parsed
            # Caps Lock and Num Lock can add modifier bits while the user
            # presses the same intended shortcut. Grab all lock-state
            # combinations so the configured shortcut remains usable.
            num_lock = 0
            try:
                num_lock_code = d.keysym_to_keycode(XK.string_to_keysym("Num_Lock"))
                mapping = d.get_modifier_mapping()
                for index, keycodes in enumerate(mapping):
                    if num_lock_code in keycodes:
                        num_lock = 1 << index
                        break
            except Exception:
                pass

            grab_masks = []
            for lock in (0, X.LockMask):
                for num in (0, num_lock):
                    mask = mods | lock | num
                    if mask not in grab_masks:
                        grab_masks.append(mask)

            for mask in grab_masks:
                root.grab_key(
                    keycode,
                    mask,
                    True,
                    X.GrabModeAsync,
                    X.GrabModeAsync,
                )
            d.flush()

            self._display = d
            self._root = root
            self._keycode = keycode
            self._mods = mods
            self._grab_masks = tuple(grab_masks)
            self.active = True
            self._ok = True
            self._ready.set()

            held = False
            while not self._stop.is_set():
                readable, _, _ = select.select([d.fileno()], [], [], 0.1)
                if not readable:
                    continue
                while d.pending_events():
                    event = d.next_event()
                    if event.type == X.KeyPress and event.detail == keycode:
                        if not held:
                            held = True
                            if self.on_press:
                                self.on_press()
                    elif event.type == X.KeyRelease and event.detail == keycode:
                        if held:
                            held = False
                            if self.on_release:
                                self.on_release()
            if held and self.on_release:
                self.on_release()
        except Exception:
            self._ok = False
            self.active = False
            if not self._ready.is_set():
                self._ready.set()
        finally:
            if self._root is not None and self._keycode is not None:
                for mask in self._grab_masks:
                    try:
                        self._root.ungrab_key(self._keycode, mask)
                    except Exception:
                        pass
                try:
                    self._display.flush()
                except Exception:
                    pass
            try:
                if self._display is not None:
                    self._display.close()
            except Exception:
                pass
            self._display = None
            self._root = None
            self._grab_masks = ()
            self.active = False


class LinuxX11Platform:
    def __init__(self, binding=""):
        self._hotkey = X11Hotkey(binding)
        self._windows = LinuxX11WindowInfo()

    @property
    def hotkey(self):
        return self._hotkey

    @property
    def launcher(self):
        return LinuxX11Launcher()

    @property
    def windows(self):
        return self._windows

    @property
    def paths(self):
        return LinuxX11DataPaths()
