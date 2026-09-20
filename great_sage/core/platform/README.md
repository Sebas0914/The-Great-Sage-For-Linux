# Platform layer

This package isolates desktop-specific behavior from Great Sage core.

Phase 1:
- Windows keeps its existing behavior through a thin adapter.
- Wayland uses xdg-open/gio and .desktop application discovery.
- X11 uses the same launcher plus _NET_ACTIVE_WINDOW when python-xlib exists.
- Wayland focused-window information fails soft until the KWin bridge is integrated.
- Global shortcuts have an explicit portal boundary; there is no keyboard-hook fallback.
- GREAT_SAGE_DATA_DIR remains an override for XDG data paths.
