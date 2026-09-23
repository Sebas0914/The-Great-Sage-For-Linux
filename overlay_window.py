"""Transparent desktop overlay host, run as its own process.

Great Sage's main window is pywebview + WinForms + WebView2, and that
stack CANNOT produce a transparent window: WebView2 renders into a child
HWND, and per-pixel alpha needs a composited TOP-LEVEL window. Measured
against a magenta backdrop, seven approaches all came back opaque -
transparent=True, WebView2's DefaultBackgroundColor, AllowTransparency
plus TransparencyKey, disabling GPU compositing, DWM blur-behind, and
re-parenting the render HWND.

Qt can. QWebEngineView is the same Chromium engine, so the Three.js
scene, the shaders and the WebGL context are all unchanged - only the
window hosting it differs. Verified before this file existed: over a
magenta backdrop, a WebGL canvas rendered correctly AND the backdrop
showed through the empty areas.

Run as a SEPARATE PROCESS on purpose. The main HUD keeps running exactly
as it does today, on the stack that already works; if this host has
trouble, the app it was launched from is untouched. It is also the only
way to have both, since Qt and WinForms each want to own the process's
GUI event loop.

    py overlay_window.py [--size 340] [--url http://...]

VERSION: PySide6 6.4.3, from the .overlay-venv (Python 3.11). This is
what FIXED the flicker, confirmed in use.

Qt 6.5.1 moved QtWebEngine to the ANGLE backend and translucent windows
have flickered on it since; 6.4.3 predates that. It cannot be installed
on Python 3.14 (PySide6 supports 3.14 only from 6.10), which is why the
overlay runs under its own interpreter - possible only because it is
already a separate process. run_hud.py prefers .overlay-venv when present.

Do NOT try to dodge the flicker by selecting a different graphics
backend: ANGLE is also what makes the window transparent here, and every
alternative either lost the transparency or stopped rendering entirely.

Also applied, both from the same investigation: WS_BORDER after show()
(QTBUG-51093) and AA_ShareOpenGLContexts + an alpha buffer in the default
surface format.
"""

import argparse
import ctypes
import os
import signal
import sys

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QRegion, QCursor, QGuiApplication, QSurfaceFormat
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

# Frozen, the overlay is its OWN exe (see overlay.spec) - built on Python
# 3.11 so it can carry PySide6 6.4.3, while the main app stays on 3.14.
# PyInstaller unpacks the bundled hud_prototype.html and vendor/ next to
# _MEIPASS, which is not where __file__ points once the module is inside
# the archive, so ask PyInstaller rather than infer.
FROZEN = getattr(sys, "frozen", False)
HERE = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))

# The page checks for this and starts in overlay mode, so the host does
# not have to inject script or wait for the scene to build.
MINI_QUERY = "?mini=1&desktop=1" if os.name != "nt" else "?mini=1"

# The page sets document.title to this when its exit control is used.
# titleChanged is the simplest reliable page->host signal that needs no
# QWebChannel plumbing, and the title is invisible on a frameless window.
EXIT_SENTINEL = "GS_EXIT_OVERLAY"
HIDE_SENTINEL = "GS_HIDE_OVERLAY"
OVERLAY_PID_FILE = "/tmp/great-sage-overlay.pid"
OVERLAY_LOCK_FILE = "/tmp/great-sage-overlay.lock"
_overlay_lock_handle = None

# The page sets this once it has switched to overlay visuals. The
# window stays HIDDEN until then: shown immediately, it displays the
# full-size HUD - test controls, window buttons, chat bar - for the
# second or so it takes the scene to build and mini mode to apply,
# which flashes a completely wrong window every time the overlay opens.
READY_SENTINEL = "GS_OVERLAY_READY"

# The overlay asks for a settings/history window with this prefix followed
# by the section name. Same title channel as the other two signals.
OPEN_PANEL_PREFIX = "GS_OPEN_PANEL:"

# Panel windows are ordinary opaque windows - they show forms and lists,
# not a floating visual, so transparency would only hurt readability.
PANEL_SIZE = (560, 640)

# Tight to the corner. The overlay is meant to tuck out of the way, and
# 24px read as floating loose beside the edge.
MARGIN = 8


# The drag handle's box, in window coordinates. The page draws a matching
# affordance at the same spot (see #mini-drag in hud_prototype.html) that
# fades in on hover; this is the half that decides whether a press starts
# a drag.
#
# Measured from the window's TOP-RIGHT corner, so it sits immediately
# left of the exit control and the two read as one pair of buttons.
# #mini-drag-handle in hud_prototype.html draws the visible affordance at
# the same spot - these must agree, or the handle points somewhere the
# host does not accept a drag.
HANDLE_INSET_RIGHT, HANDLE_TOP, HANDLE_W, HANDLE_H = 48, 2, 26, 26

# ---- click-through -------------------------------------------------
# The overlay is a 340px SQUARE, but almost all of it is transparent - the
# visual inside is a core with a wireframe around it. Krazaa could not
# click the browser tabs underneath, because an always-on-top window eats
# every click that lands anywhere in its rectangle, visible or not.
#
# So the window is click-through EXCEPT where there is something to hit.
# WS_EX_TRANSPARENT does that at the OS level: clicks fall through to
# whatever is behind.
#
# It has to be POLLED rather than driven by mouse events, and that is not
# laziness: a click-through window receives no mouse events at all, so
# once it is transparent nothing would ever tell it the cursor had come
# back. The cursor position is global, so a timer can see it regardless.
CLICK_THROUGH_POLL_MS = 50
WS_EX_TRANSPARENT = 0x00000020
GWL_EXSTYLE = -20
# Fraction of the window's width, from the centre, that counts as the
# core. Big enough to click without aiming, small enough that the corners
# - which is where the tabs and buttons underneath are - stay usable.
CORE_HIT_FRACTION = 0.26
# The page says when the whole window must be live: the radial menu is
# open, or the speech bubble is showing. Both extend well past the core.
HIT_ALL_SENTINEL = "GS_HIT_ALL"
HIT_CORE_SENTINEL = "GS_HIT_CORE"

WAYLAND_SESSION = (
    sys.platform.startswith("linux")
    and os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
)

_WL_LAYER = None
_WL_INPUT = None


def _load_wayland_native():
    global _WL_LAYER, _WL_INPUT

    if not WAYLAND_SESSION:
        return None, None

    if _WL_LAYER is not None or _WL_INPUT is not None:
        return _WL_LAYER, _WL_INPUT

    native_dir = os.path.join(HERE, "native")
    layer_path = os.path.join(native_dir, "libgs_layer_config.so")
    input_path = os.path.join(native_dir, "libgs_input_region.so")

    try:
        if os.path.isfile(layer_path):
            _WL_LAYER = ctypes.CDLL(layer_path)
            _WL_LAYER.gs_configure_layer.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
            ]
            _WL_LAYER.gs_configure_layer.restype = ctypes.c_int
            _WL_LAYER.gs_position_layer.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.c_int
            ]
            _WL_LAYER.gs_position_layer.restype = ctypes.c_int

        if os.path.isfile(input_path):
            _WL_INPUT = ctypes.CDLL(input_path)
            _WL_INPUT.gs_set_input_region.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
            ]
            _WL_INPUT.gs_set_input_region.restype = ctypes.c_int

            _WL_INPUT.gs_set_input_regions.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_int),
                ctypes.c_int,
            ]
            _WL_INPUT.gs_set_input_regions.restype = ctypes.c_int

    except Exception as exc:
        print(f"[overlay] Wayland native load failed: {exc}", flush=True)
        _WL_LAYER = None
        _WL_INPUT = None

    return _WL_LAYER, _WL_INPUT


def _qwindow_cpp_pointer(widget):
    qwindow = widget.windowHandle()
    if qwindow is None:
        widget.createWinId()
        qwindow = widget.windowHandle()

    if qwindow is None:
        return None

    try:
        import shiboken6
        ptr = int(shiboken6.getCppPointer(qwindow)[0])
        return ctypes.c_void_p(ptr)
    except Exception as exc:
        print(f"[overlay] Could not get QWindow pointer: {exc}", flush=True)
        return None


class OverlayView(QWebEngineView):
    """Frameless, always-on-top, transparent, dragged by its handle."""

    def __init__(self, size: int):
        super().__init__()
        self._drag_from = None

        # The three settings that make it genuinely see-through. All are
        # required: dropping any one leaves an opaque window.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        flags = (
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        if WAYLAND_SESSION:
            flags |= Qt.WindowDoesNotAcceptFocus
        self.setWindowFlags(flags)
        self.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self.setStyleSheet("background: transparent; border: 0;")
        # Qt must not paint its own background before Chromium draws. On a
        # translucent window that pre-paint is a candidate for the visible
        # flicker, since it briefly shows a frame the web content has not
        # filled yet.
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

        # En Wayland usamos una superficie transparente de pantalla completa.
        # La región de entrada real se limita posteriormente a Raphael.
        if WAYLAND_SESSION:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                screen_geo = screen.geometry()
                self.setGeometry(screen_geo)
                effective_size = min(
                    screen_geo.width(),
                    screen_geo.height(),
                )
            else:
                self.resize(size, size)
                effective_size = size
        else:
            self.resize(size, size)
            effective_size = size

        self._filtered = None
        self._wayland_layer = False
        self._wayland_window_ptr = None
        self._wayland_layer_lib = None
        self._wayland_input = None
        self._wayland_interactive_rects = []
        self._input_mask_generation = 0
        self._drag_press_pos = None
        self._dragging = False
        self._drag_offset = None
        self._drag_window_offset = None
        self.titleChanged.connect(self._on_title)
        # The render widget does not exist yet at construction time, so the
        # filter is installed once the page has loaded (and again on show).
        self.loadFinished.connect(lambda _ok: self._install_mouse_filter())

        # Click-through state. Starts None so the first poll always
        # applies a style rather than assuming one.
        self._hit_all = False
        # Linux/Wayland: keep only Raphael's circular visual area interactive.
        # En pantalla completa el radio debe basarse en el tamaño real.
        self._mask_radius = max(1, int(effective_size * 0.30))
        self._placed = False
        self._click_through = None
        self._ct_timer = QTimer(self)
        self._ct_timer.timeout.connect(self._update_click_through)
        self._ct_timer.start(CLICK_THROUGH_POLL_MS)

        self._desktop = os.name != "nt"
        self._desktop_hover_timer = None
        if self._desktop:
            # The fullscreen surface is deliberately click-through so VS Code,
            # browsers and games underneath remain usable. Cursor position is
            # global, so hover is polled without consuming mouse events.
            # Wayland: el click-through global de Qt no permite interacción selectiva.
            self._desktop_hover_timer = QTimer(self)
            self._desktop_hover_timer.timeout.connect(self._poll_desktop_hover)
            self._desktop_hover_timer.start(60)


    # ---- click-through --------------------------------------------
    def _interactive_at(self, gpos) -> bool:
        """Is there anything to hit at this screen position?"""
        if self._hit_all:
            return True
        top = self.frameGeometry().topLeft()
        x, y = gpos.x() - top.x(), gpos.y() - top.y()
        w, h = self.width(), self.height()
        if not (0 <= x <= w and 0 <= y <= h):
            return False
        # The drag handle and the exit cross, both top-right.
        hx = w - HANDLE_INSET_RIGHT
        if hx <= x <= hx + HANDLE_W and HANDLE_TOP <= y <= HANDLE_TOP + HANDLE_H:
            return True
        if x >= w - 24 and y <= 24:
            return True
        # The core itself.
        dx, dy = x - w / 2.0, y - h / 2.0
        r = w * CORE_HIT_FRACTION
        return (dx * dx + dy * dy) <= r * r

    def _apply_wayland_input_region(self, x, y, width, height):
        if not (
            WAYLAND_SESSION
            and self._wayland_window_ptr
            and self._wayland_input
        ):
            return

        w = max(1, self.width())
        h = max(1, self.height())

        x = max(0, min(int(x), w - 1))
        y = max(0, min(int(y), h - 1))
        width = max(1, min(int(width), w - x))
        height = max(1, min(int(height), h - y))

        self._wayland_interactive_rects = [(x, y, width, height)]

        try:
            result = self._wayland_input.gs_set_input_region(
                self._wayland_window_ptr,
                x,
                y,
                width,
                height,
            )

            if result != 0:
                print(
                    f"[overlay] gs_set_input_region returned {result}",
                    flush=True,
                )

        except Exception as exc:
            print(
                f"[overlay] Wayland native input-region update failed: {exc}",
                flush=True,
            )

    def _apply_wayland_input_regions(self, rects):
        """Apply multiple independent interactive rectangles to Wayland."""
        if not (
            WAYLAND_SESSION
            and self._wayland_window_ptr
            and self._wayland_input
        ):
            return

        w = max(1, self.width())
        h = max(1, self.height())

        clean_rects = []

        for rect in rects:
            try:
                x, y, width, height = rect

                x = max(0, min(int(x), w - 1))
                y = max(0, min(int(y), h - 1))
                width = max(1, min(int(width), w - x))
                height = max(1, min(int(height), h - y))

                clean_rects.append((x, y, width, height))
            except Exception:
                continue

        self._wayland_interactive_rects = clean_rects

        try:
            values = []

            for x, y, width, height in clean_rects:
                values.extend([x, y, width, height])

            array_type = ctypes.c_int * len(values)
            rect_array = array_type(*values)

            result = self._wayland_input.gs_set_input_regions(
                self._wayland_window_ptr,
                rect_array,
                len(clean_rects),
            )

            if result != 0:
                print(
                    f"[overlay] gs_set_input_regions returned {result}",
                    flush=True,
                )

        except Exception as exc:
            print(
                f"[overlay] Wayland native input-regions update failed: {exc}",
                flush=True,
            )

    def _update_input_mask(self):

        if WAYLAND_SESSION:
            self._input_mask_generation += 1
            generation = self._input_mask_generation
            w, h = self.width(), self.height()

            # El menú radial necesita toda la superficie.
            # En modo desktop NO debemos capturar el fondo, ni siquiera
            # durante el arrastre de Raphael.
            if (
                self._hit_all
                and not (self._desktop and WAYLAND_SESSION)
            ):
                self._apply_wayland_input_region(0, 0, w, h)
                return

            # En modo desktop, preguntar al HTML por la posición real
            # de Raphael. Así la región de Wayland sigue al icono.
            if self._desktop:
                # Durante el arrastre necesitamos que el cursor pueda
                # seguir entrando en la superficie completa. El HTML
                # continúa moviendo únicamente Raphael.
                if self._dragging:
                    self._apply_wayland_input_region(0, 0, w, h)
                    return

                # Raphael y el cuadro de subtítulos son zonas
                # independientes dentro de la superficie Wayland.
                def got_rects(rects):
                    try:
                        # JavaScript callbacks can arrive out of order. Ignore
                        # a result from an older geometry query.
                        if generation != self._input_mask_generation or self._dragging:
                            return
                        if not isinstance(rects, list):
                            self._apply_wayland_input_regions([])
                            return

                        clean_rects = []

                        for rect in rects:
                            if not isinstance(rect, dict):
                                continue

                            x = float(rect.get("x", 0))
                            y = float(rect.get("y", 0))
                            rw = float(rect.get("width", 1))
                            rh = float(rect.get("height", 1))

                            # Clamp every rectangle to the actual Qt surface.
                            # A stale/partially off-screen DOM rect must never
                            # create an input region outside the LayerShell
                            # surface, and zero-sized rectangles are discarded.
                            x1 = max(0.0, min(float(w), x))
                            y1 = max(0.0, min(float(h), y))
                            x2 = max(x1, min(float(w), x + rw))
                            y2 = max(y1, min(float(h), y + rh))
                            if x2 > x1 and y2 > y1:
                                clean_rects.append((x1, y1, x2 - x1, y2 - y1))

                        self._apply_wayland_input_regions(clean_rects)

                    except Exception as exc:
                        print(
                            f"[overlay] invalid desktop input rects: {exc}",
                            flush=True,
                        )

                try:
                    self.page().runJavaScript(
                        "window.__desktopCoreInteractiveRect "
                        "? window.__desktopCoreInteractiveRect() : null",
                        got_rects,
                    )
                except Exception as exc:
                    print(
                        f"[overlay] desktop input rect query failed: {exc}",
                        flush=True,
                    )
                return

            r = min(self._mask_radius, w // 2, h // 2)
            cx, cy = w // 2, h // 2
            self._apply_wayland_input_region(
                cx - r, cy - r, r * 2, r * 2
            )
            return

        # X11 keeps the old Qt mask path.
        if os.name == "nt" or WAYLAND_SESSION:
            return

        w, h = self.width(), self.height()
        r = min(self._mask_radius, w // 2, h // 2)
        cx, cy = w // 2, h // 2
        self.setMask(QRegion(cx - r, cy - r, r * 2, r * 2))

    def _position_wayland_surface(self, point):
        if not (
            WAYLAND_SESSION
            and self._wayland_window_ptr
            and self._wayland_layer_lib
        ):
            return False

        try:
            screen = self.screen() or QGuiApplication.primaryScreen()
            area = screen.geometry()

            x = max(
                area.left(),
                min(
                    int(point.x()),
                    area.right() - self.width() + 1,
                ),
            )
            y = max(
                area.top(),
                min(
                    int(point.y()),
                    area.bottom() - self.height() + 1,
                ),
            )

            top = y - area.top()
            right = area.right() - (x + self.width()) + 1

            result = int(
                self._wayland_layer_lib.gs_position_layer(
                    self._wayland_window_ptr,
                    int(top),
                    int(right),
                )
            )

            if result != 0:
                print(
                    f"[overlay] gs_position_layer returned {result}",
                    flush=True,
                )
                return False

            return True
        except Exception as exc:
            print(
                f"[overlay] Wayland layer positioning failed: {exc}",
                flush=True,
            )
            return False

    def _place_wayland_top_right(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        area = screen.geometry()
        point = QPoint(
            area.right() - self.width() - MARGIN + 1,
            area.top() + MARGIN,
        )
        return self._position_wayland_surface(point)

    def _configure_wayland_layer(self):
        if not WAYLAND_SESSION:
            return False

        layer, input_region = _load_wayland_native()
        if layer is None:
            print(
                "[overlay] LayerShellQt bridge not available; "
                "falling back to normal Qt window",
                flush=True,
            )
            return False

        ptr = _qwindow_cpp_pointer(self)
        if ptr is None:
            return False

        self._wayland_window_ptr = ptr
        self._wayland_input = input_region
        self._wayland_layer_lib = layer

        try:
            result = int(
                layer.gs_configure_layer(
                    ptr,
                    int(self.width()),
                    int(self.height()),
                    int(MARGIN),
                    int(MARGIN),
                )
            )
            ok = result == 0
            if not ok:
                print(
                    f"[overlay] gs_configure_layer returned {result}",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[overlay] LayerShellQt configuration failed: {exc}",
                flush=True,
            )
            return False

        self._wayland_layer = ok

        if ok:
            # The LayerShell surface is fullscreen and fixed. Raphael's
            # position is controlled by the HTML scene, not by LayerShell.
            # Start with an EMPTY input region: the page may not have its
            # geometry ready yet, and an old/default region would otherwise
            # swallow clicks across the entire desktop.
            print(
                "[overlay] Wayland LayerShellQt overlay enabled",
                flush=True,
            )
            self._apply_wayland_input_regions([])
            self._update_input_mask()

        return ok

    def _set_click_through(self, on: bool):
        # Windows uses WS_EX_TRANSPARENT. KDE Wayland does not expose
        # that Win32 API, so leave the window unchanged here.
        if os.name != "nt":
            self._click_through = on
            return

        if on == self._click_through:
            return

        try:
            import ctypes
            hwnd = int(self.winId())
            u = ctypes.windll.user32
            get_l = getattr(u, "GetWindowLongPtrW", None) or u.GetWindowLongW
            set_l = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
            style = get_l(hwnd, GWL_EXSTYLE)
            style = (style | WS_EX_TRANSPARENT) if on else (style & ~WS_EX_TRANSPARENT)
            set_l(hwnd, GWL_EXSTYLE, style)
            self._click_through = on
        except Exception:
            pass

    def _update_click_through(self):
        if not self.isVisible():
            return
        self._update_input_mask()
        self._set_click_through(not self._interactive_at(QCursor.pos()))

    def _poll_desktop_hover(self):
        if not self._desktop or not self.isVisible():
            return

        # El caption puede aparecer/desaparecer o cambiar de tamaño
        # mientras Raphael permanece en el mismo sitio. Recalcular la
        # región nativa mantiene ambos elementos interactivos sin hacer
        # clickeable el fondo transparente.
        self._update_input_mask()

        p = QCursor.pos()

        def got_core(core):
            try:
                if not isinstance(core, dict) or "x" not in core or "y" not in core:
                    return
                dx = float(p.x()) - float(core["x"])
                dy = float(p.y()) - float(core["y"])
                hovered = (dx * dx + dy * dy) <= (105.0 * 105.0)
                self.page().runJavaScript(
                    "window.__desktopSetHoverFromHost && "
                    "window.__desktopSetHoverFromHost(%s);" %
                    ("true" if hovered else "false")
                )
            except Exception:
                pass

        try:
            self.page().runJavaScript(
                "window.__desktopCoreScreenPosition ? "
                "window.__desktopCoreScreenPosition() : null",
                got_core,
            )
        except Exception:
            pass

    # ---- page -> host ---------------------------------------------
    def _on_title(self, title: str):
        if title.strip() == READY_SENTINEL:
            # Placed and shown only now, so the first frame the user sees
            # is already the overlay.
            #
            # ONCE. This sentinel arrives again every time the page asks
            # for a panel window - requestPanelWindow restores the title to
            # it deliberately, so that asking for the same section twice
            # still registers as a change. Re-placing on those would snap
            # the overlay back to the top right corner every time Master
            # opened settings, throwing away wherever he had dragged it.
            if not self._placed:
                self._placed = True
                # LayerShellQt owns the position on Wayland.
                if not self._wayland_layer:
                    if not WAYLAND_SESSION:
                        place_top_right(self, self.width())
            self.show()
            if os.name == "nt":
                _apply_ws_border(self)
            self._install_mouse_filter()
            return
        if title.strip().startswith(OPEN_PANEL_PREFIX):
            section = title.strip()[len(OPEN_PANEL_PREFIX):].strip()
            if section:
                _spawn_panel(section)
            return
        if title.strip() == HIT_ALL_SENTINEL:
            self._hit_all = True
            self._update_input_mask()
            return
        if title.strip() == HIT_CORE_SENTINEL:
            self._hit_all = False
            self._update_input_mask()
            return
        if title.strip() == HIDE_SENTINEL:
            self.hide()
            return
        if title.strip() == EXIT_SENTINEL:
            QApplication.instance().exit(0)

    def closeEvent(self, event):
        if self._desktop:
            self.hide()
            event.ignore()
            return
        super().closeEvent(event)

    # ---- dragging --------------------------------------------------
    # Done here rather than in the page: Qt owns the frameless window, and
    # moving it from JS would need a bridge for something the host can do
    # in three lines.
    def _in_handle(self, pos) -> bool:
        """Is this press inside the drag handle?

        Measured from the RIGHT edge, so it stays put at any window size.
        """
        x0 = self.width() - HANDLE_INSET_RIGHT
        return (x0 <= pos.x() <= x0 + HANDLE_W
                and HANDLE_TOP <= pos.y() <= HANDLE_TOP + HANDLE_H)

    # QWebEngineView does NOT receive mouse events itself: they go to an
    # internal render widget it owns. Overriding mousePressEvent here was
    # dead code - never called - which is exactly why the handle refused to
    # drag. Watching the focus proxy is the supported way to see them.
    def _install_mouse_filter(self):
        proxy = self.focusProxy()
        if proxy is not None and proxy is not self._filtered:
            proxy.installEventFilter(self)
            self._filtered = proxy

    def _point_inside_wayland_rect(self, pos, rects=None):
        rects = self._wayland_interactive_rects if rects is None else rects

        if not rects:
            return False

        px, py = pos.x(), pos.y()

        for x, y, w, h in rects:
            if x <= px <= x + w and y <= py <= y + h:
                return True

        return False

    def eventFilter(self, obj, event):
        et = event.type()

        if WAYLAND_SESSION and self._desktop:
            if et == QEvent.MouseButtonPress:
                if event.button() == Qt.LeftButton:
                    pos = event.position().toPoint()

                    if self._point_inside_wayland_rect(pos):
                        # The second interactive rectangle is the caption.
                        # Its mouse events belong to the web page so the
                        # caption's own MOVE CAPTION gesture can run. Only
                        # presses on Raphael are promoted to host-side drag.
                        rects = self._wayland_interactive_rects
                        if (
                            len(rects) > 1
                            and self._point_inside_wayland_rect(pos, rects[1:2])
                        ):
                            return super().eventFilter(obj, event)

                        self._drag_press_pos = event.globalPosition().toPoint()
                        self._drag_offset = None
                        self._drag_window_offset = (
                            self._drag_press_pos - self.frameGeometry().topLeft()
                        )
                        self._dragging = False
                        try:
                            self.page().runJavaScript(
                                "window.__desktopBeginDrag "
                                "&& window.__desktopBeginDrag(%s,%s);"
                                % (pos.x(), pos.y())
                            )
                        except Exception:
                            pass
                        return False

            elif et == QEvent.MouseMove:
                if (
                    self._drag_press_pos is not None
                    and (event.buttons() & Qt.LeftButton)
                ):
                    current = event.globalPosition().toPoint()

                    dx = current.x() - self._drag_press_pos.x()
                    dy = current.y() - self._drag_press_pos.y()

                    if not self._dragging and (dx * dx + dy * dy) >= 36:
                        self._dragging = True
                        self._input_mask_generation += 1

                        # Temporarily make the whole fullscreen surface
                        # interactive so the pointer cannot leave the
                        # original Raphael region while dragging.
                        self._apply_wayland_input_region(
                            0, 0, self.width(), self.height()
                        )

                        try:
                            self.page().runJavaScript(
                                "window.__desktopSetHostDragging "
                                "&& window.__desktopSetHostDragging(true);"
                            )
                        except Exception:
                            pass

                    if self._dragging:
                        speed = (dx * dx + dy * dy) ** 0.5

                        # The Wayland surface stays fullscreen and fixed.
                        # Convert the global cursor position to coordinates
                        # inside that surface and let Three.js move Raphael.
                        try:
                            screen = self.screen() or QGuiApplication.primaryScreen()
                            area = screen.geometry() if screen is not None else None
                            if area is not None:
                                local_x = current.x() - area.left()
                                local_y = current.y() - area.top()
                            else:
                                local_x = current.x()
                                local_y = current.y()

                            self.page().runJavaScript(
                                "window.__desktopSetDragPosition "
                                "&& window.__desktopSetDragPosition(%s,%s,%s,%s,%s);"
                                % (
                                    local_x,
                                    local_y,
                                    dx,
                                    dy,
                                    speed,
                                )
                            )
                        except Exception as exc:
                            print(
                                f"[overlay] desktop drag JS failed: {exc}",
                                flush=True,
                            )

                        return True

            elif et == QEvent.MouseButtonRelease:
                if event.button() == Qt.LeftButton:
                    was_dragging = self._dragging

                    self._drag_press_pos = None
                    self._drag_offset = None
                    self._drag_window_offset = None
                    self._dragging = False

                    if was_dragging:
                        try:
                            self.page().runJavaScript(
                                "window.__desktopSetHostDragging "
                                "&& window.__desktopSetHostDragging(false);"
                            )
                        except Exception:
                            pass

                        self._update_input_mask()
                        return True

        # Panel/Windows/X11 handling.
        if et == QEvent.MouseButtonPress:
            if (
                event.button() == Qt.LeftButton
                and self._in_handle(event.position())
            ):
                self._drag_from = (
                    event.globalPosition().toPoint()
                    - self.frameGeometry().topLeft()
                )
                return True

        elif et == QEvent.MouseMove:
            if (
                self._drag_from is not None
                and (event.buttons() & Qt.LeftButton)
            ):
                self.move(
                    self._clamp_to_screen(
                        event.globalPosition().toPoint() - self._drag_from
                    )
                )
                return True

        elif et in (QEvent.MouseButtonRelease, QEvent.Leave):
            self._drag_from = None

        return super().eventFilter(obj, event)

    def _clamp_to_screen(self, point):
        """Keep the whole window on the monitor it is being dragged on.

        Without this the overlay can be pushed past the screen edge, and
        the core menu - which opens centred on the window - gets cut off by
        the monitor rather than fitting inside it. The menu already clamps
        itself to the WINDOW; keeping the window fully visible is what
        makes that clamp sufficient.
        """
        screen = self.screen() or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(point.x(), area.left()), area.right() - self.width() + 1)
        y = min(max(point.y(), area.top()), area.bottom() - self.height() + 1)
        return QPoint(x, y)


# Panel processes, kept so a second request for a section already open
# raises that window instead of stacking duplicates.
_panel_procs = {}

def _acquire_overlay_lock() -> bool:
    """Allow only one Linux desktop overlay instance at a time."""
    if os.name == "nt":
        return True

    import fcntl
    global _overlay_lock_handle
    try:
        handle = open(OVERLAY_LOCK_FILE, "a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            print(
                "[overlay] another overlay instance is already running; exiting",
                flush=True,
            )
            return False
        _overlay_lock_handle = handle
        return True
    except OSError as exc:
        print(f"[overlay] could not acquire overlay lock: {exc}", flush=True)
        return False

def _release_overlay_lock() -> None:
    if _overlay_lock_handle is None:
        return
    try:
        import fcntl
        fcntl.flock(_overlay_lock_handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        _overlay_lock_handle.close()
    except Exception:
        pass

def _panel_command(section: str):
    """How to re-invoke ourselves for a panel window.

    Frozen, this module IS the exe's entry point, so the exe re-invoked
    with --panel lands back in main(). Spawning the .py path would look
    right and fail in a build: there is no interpreter to run it with,
    and sys.executable is the overlay exe, not python.
    """
    if FROZEN:
        return [sys.executable, "--panel", section]
    return [sys.executable, os.path.abspath(__file__), "--panel", section]


def _spawn_panel(section: str):
    """Open (or re-focus) a settings/history window for `section`.

    A separate PROCESS rather than another window in this one: Qt wants a
    single GUI thread, and keeping panels out of the overlay's process
    means a panel that misbehaves cannot take the overlay down with it.
    """
    import subprocess
    proc = _panel_procs.get(section)
    if proc is not None and proc.poll() is None:
        return                       # already open
    try:
        proc = subprocess.Popen(
            _panel_command(section), cwd=HERE)
        _panel_procs[section] = proc
        print(f"[overlay] panel window opened: {section} (pid {proc.pid})",
              flush=True)
    except Exception as exc:
        print(f"[overlay] could not open panel {section}: {exc}", flush=True)


# The page draws its own title bar (#panel-window-chrome) because the
# window is frameless. That bar is 46px tall, and its minimise/close
# buttons sit at the right - pressing those must not also start a drag.
PANEL_BAR_H = 46
PANEL_BUTTONS_W = 96


class PanelView(QWebEngineView):
    """A settings/history window: opaque, frameless, its own chrome."""

    def __init__(self, section: str):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.resize(*PANEL_SIZE)
        self.setWindowTitle(f"Great Sage - {section}")
        self._drag_from = None
        self._filtered = None
        # Same reasoning as the overlay: QWebEngineView never receives
        # mouse events itself - they go to an internal render widget - so
        # the page's .pywebview-drag-region did nothing here, and there is
        # no pywebview under Qt to honour it anyway. That is why the title
        # bar could not be dragged.
        self.loadFinished.connect(lambda _ok: self._install_mouse_filter())

    def showEvent(self, event):
        # The render widget may not exist yet when the page finishes
        # loading, and installing on a proxy that is not there yet is a
        # silent no-op - which leaves the title bar dead with nothing to
        # show why. The overlay installs twice for the same reason.
        super().showEvent(event)
        self._install_mouse_filter()
        QTimer.singleShot(0, self._install_mouse_filter)

    def _install_mouse_filter(self):
        proxy = self.focusProxy()
        if proxy is not None and proxy is not self._filtered:
            proxy.installEventFilter(self)
            self._filtered = proxy

    def _in_bar(self, pos) -> bool:
        return (pos.y() <= PANEL_BAR_H
                and pos.x() <= self.width() - PANEL_BUTTONS_W)

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.MouseButtonPress:
            if (event.button() == Qt.LeftButton
                    and self._in_bar(event.position())):
                self._drag_from = (event.globalPosition().toPoint()
                                   - self.frameGeometry().topLeft())
                return True      # swallow, or the page reacts to it too
        elif et == QEvent.MouseMove:
            if self._drag_from is not None and (event.buttons() & Qt.LeftButton):
                self.move(event.globalPosition().toPoint() - self._drag_from)
                return True
        elif et in (QEvent.MouseButtonRelease, QEvent.Leave):
            self._drag_from = None
        return super().eventFilter(obj, event)


def _apply_ws_border(win) -> bool:
    """Add WS_BORDER to the window style, after it is shown.

    Workaround for QTBUG-51093. Windows gives OpenGL-based windows special
    treatment when they have no border style, and Qt's own Windows notes
    flag it: the window ends up on a different compositing path, which
    shows up as flicker and as popups drawing behind the window.

    Reported to fix exactly this in a PyQtGraph thread with the same
    symptom. WS_BORDER must be applied AFTER show(), because Qt sets the
    style itself when the window is created and would overwrite it.

    Nothing is drawn by this on a frameless translucent window - the style
    bit changes how Windows composites it, not what it paints. Failure is
    non-fatal: worst case the flicker stays.
    """
    try:
        import ctypes
        hwnd = int(win.winId())
        u = ctypes.windll.user32
        get_l = getattr(u, "GetWindowLongPtrW", None) or u.GetWindowLongW
        set_l = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
        get_l.restype = ctypes.c_ssize_t
        get_l.argtypes = [ctypes.c_void_p, ctypes.c_int]
        set_l.restype = ctypes.c_ssize_t
        set_l.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        _GWL_STYLE, _WS_BORDER = -16, 0x00800000
        style = get_l(ctypes.c_void_p(hwnd), _GWL_STYLE)
        set_l(ctypes.c_void_p(hwnd), _GWL_STYLE, style | _WS_BORDER)
        # SWP_FRAMECHANGED, or the new style is stored but never applied.
        u.SetWindowPos(ctypes.c_void_p(hwnd), None, 0, 0, 0, 0,
                       0x0020 | 0x0002 | 0x0001 | 0x0004)
        print(f"[overlay] WS_BORDER applied (style 0x{style & 0xFFFFFFFF:08X}"
              f" -> 0x{(style | _WS_BORDER) & 0xFFFFFFFF:08X})", flush=True)
        return True
    except Exception as exc:
        print(f"[overlay] WS_BORDER failed: {type(exc).__name__}: {exc}",
              flush=True)
        return False


def place_top_right(win, size: int):
    """Corner of the WORK area, so it tucks beside the taskbar."""
    screen = QGuiApplication.primaryScreen()
    area = screen.availableGeometry()
    win.move(area.right() - size - MARGIN + 1, area.top() + MARGIN)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=340)
    ap.add_argument("--url", default=None,
                    help="page to load; defaults to the local hud file")
    ap.add_argument("--panel", default=None,
                    help="open as a settings/history window instead of the "
                         "overlay (values: settings, history)")
    args = ap.parse_args()

    # Chromium needs this before the QApplication exists, or the WebGL
    # surface comes back opaque even with the Qt attributes set.
    # VSYNC STAYS ON, and the frame rate STAYS CAPPED.
    #
    # --disable-gpu-vsync and --disable-frame-rate-limit were tried here as
    # flicker mitigations and did active harm:
    #   * uncapped frames ran the GPU flat out and spun the fans up, for a
    #     visual that only ever needs 60fps;
    #   * the HUD's animations advance PER FRAME, not per second
    #     (rotation.y += 0.0022), so more frames literally meant faster
    #     spinning - the wireframe visibly sped up;
    #   * disabling vsync CAUSES tearing, which on a translucent window
    #     looks like exactly the flicker it was meant to fix.
    # Removing them is not a compromise; keeping them was the mistake.
    #
    # NOT --disable-gpu-compositing. It was tried here as a flicker fix, on
    # the theory that a 340x340 window is cheap to composite in software.
    # Measured in use: about 3fps. Software compositing of a continuously
    # animating WebGL scene is far more expensive than the small window
    # size suggests, and an unusable frame rate is worse than the flicker
    # it was meant to cure.
    #
    # THE FLICKER: ANGLE. Qt 6.5.1 switched QtWebEngine to the ANGLE
    # backend (OpenGL translated to Direct3D), and translucent windows have
    # flickered since - reported against other Qt WebEngine apps, not just
    # this one. The usual advice is to pin Qt 6.4.3, which is not possible
    # here: PySide6 only supports Python 3.14 from 6.10 onward, so pip
    # offers 6.10.1 at the oldest.
    #
    # Selecting a different backend was tried and cannot work HERE, because
    # ANGLE is also what makes the transparency work. Measured, each
    # against a magenta backdrop:
    #
    #   --use-angle=gl        GPU context lost, nothing renders at all
    #   --use-angle=d3d9      failed to come up
    #   QT_OPENGL=desktop     renders, but the window is OPAQUE - the
    #                         desktop no longer shows through
    #
    # So the default ANGLE/D3D11 path stays. Escaping the flicker by
    # avoiding ANGLE would mean giving up the transparency the overlay
    # exists for.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                          "--enable-transparent-visuals "
                          "--autoplay-policy=no-user-gesture-required")

    # Both of these MUST happen before the QApplication is constructed -
    # afterwards the GL context and surface format are already fixed.
    #
    # AA_ShareOpenGLContexts: Qt WebEngine renders in its own process and
    # shares GL resources with the GUI thread. Without a shared context the
    # two ends can disagree about which surface is current, which is a
    # known cause of flicker in Qt apps that mix OpenGL widgets with other
    # rendering - Qt itself warns about this attribute for WebEngine.
    #
    # The explicit alpha buffer matters for a TRANSLUCENT window
    # specifically: the default surface format has no alpha channel, so the
    # compositor can end up reading undefined alpha for the frame, which
    # shows up as the window flashing rather than blending steadily.
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setAlphaBufferSize(8)
    fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)

    # --panel is a separate process and must never claim the overlay PID
    # file or install the overlay's SIGUSR handlers.
    if args.panel:
        panel = PanelView(args.panel)

        def _on_panel_title(t):
            cmd = t.strip()
            if cmd == "GS_PANEL_CLOSE":
                app.quit()
            elif cmd == "GS_PANEL_MIN":
                panel.showMinimized()

        panel.titleChanged.connect(_on_panel_title)
        url = args.url or QUrl.fromLocalFile(
            os.path.join(HERE, "hud_prototype.html")).toString()
        panel.load(QUrl(f"{url}?panel={args.panel}"))
        panel.show()
        if os.name == "nt":
            _apply_ws_border(panel)
        return app.exec()

    if os.name != "nt":
        if not _acquire_overlay_lock():
            return 0

        try:
            with open(OVERLAY_PID_FILE, "w", encoding="utf-8") as fh:
                fh.write(str(os.getpid()))
        except OSError:
            pass
        commands = {"show": False, "hide": False}
        signal.signal(signal.SIGUSR1, lambda *_: commands.__setitem__("show", True))
        signal.signal(signal.SIGUSR2, lambda *_: commands.__setitem__("hide", True))
        command_timer = QTimer()
        def apply_command():
            if commands["show"]:
                commands["show"] = False
                if "view" in locals():
                    view.show()
                    view.raise_()
            if commands["hide"]:
                commands["hide"] = False
                if "view" in locals():
                    view.hide()
        command_timer.timeout.connect(apply_command)
        command_timer.start(150)
        def _cleanup_overlay_state():
            try:
                if os.path.exists(OVERLAY_PID_FILE):
                    os.unlink(OVERLAY_PID_FILE)
            except OSError:
                pass
            _release_overlay_lock()

        app.aboutToQuit.connect(_cleanup_overlay_state)

    view = OverlayView(args.size)

    if WAYLAND_SESSION:
        view._configure_wayland_layer()

    url = args.url or QUrl.fromLocalFile(
        os.path.join(HERE, "hud_prototype.html")).toString()
    view.load(QUrl(url + MINI_QUERY))

    # Deliberately NOT shown here - see READY_SENTINEL. The page asks to
    # be shown once it is actually in overlay mode.
    #
    # Failsafe: if the page never reports ready (an older copy of the HTML,
    # or a JS error before it gets there), show it anyway rather than
    # leaving an invisible process running with no window.
    def _failsafe():
        if not view.isVisible():
            # LayerShell ya determina la geometría en Wayland.
            if not WAYLAND_SESSION:
                place_top_right(view, args.size)
            view.show()

    QTimer.singleShot(12000, _failsafe)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
