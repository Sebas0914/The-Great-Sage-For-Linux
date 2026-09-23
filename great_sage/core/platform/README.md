# Platform layer

This package isolates desktop-specific behavior from Great Sage core.

Phase 1:
- Windows keeps its existing behavior through a thin adapter.
- Wayland uses xdg-open/gio and .desktop application discovery.
- Wayland global shortcuts use the XDG GlobalShortcuts portal; there is no keyboard-hook fallback.
- Wayland focused-window information uses the KDE KWin D-Bus bridge.
- KDE Spectacle provides the Wayland screenshot path used by vision tools.
- X11 uses xdg-open plus _NET_ACTIVE_WINDOW/_NET_WM_NAME for focused-window information.
- X11 global shortcuts use a single XGrabKey for the configured combination; arbitrary keyboard input is never monitored.
- GREAT_SAGE_DATA_DIR remains an override for XDG data paths.
- The platform factory reuses the process-wide adapter so D-Bus sessions, hotkeys, and focused-window state are not recreated per tool call.

Runtime-specific integrations remain behind this boundary; core tools do not import
Windows APIs or X11/Wayland APIs directly.
