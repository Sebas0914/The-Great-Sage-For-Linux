#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NATIVE_DIR="$ROOT/native"

cd "$NATIVE_DIR"

g++ -std=c++17 -fPIC -shared gs_layer_config.cpp \
  -I/usr/include/x86_64-linux-gnu/qt6 \
  -I/usr/include/x86_64-linux-gnu/qt6/QtGui \
  -I/usr/include/x86_64-linux-gnu/qt6/QtCore \
  -I/usr/include/LayerShellQt \
  -L/usr/lib/x86_64-linux-gnu \
  -Wl,-rpath,/usr/lib/x86_64-linux-gnu \
  -lLayerShellQtInterface \
  -lQt6Gui \
  -lQt6Core \
  -o libgs_layer_config.so

echo "Built $NATIVE_DIR/libgs_layer_config.so"
ldd "$NATIVE_DIR/libgs_layer_config.so" | grep -E 'LayerShellQt|Qt6Gui|Qt6Core' || true

# The fullscreen LayerShell surface must not consume the entire desktop.
# This bridge applies explicit wl_surface input regions so only Raphael and
# visible controls receive pointer events.
QT_PRIVATE_GUI_DIR="$(find /usr/include/x86_64-linux-gnu/qt6 -type d -path '*/QtGui/*/QtGui' -print -quit 2>/dev/null || true)"
if [[ -z "$QT_PRIVATE_GUI_DIR" ]]; then
  echo "Could not locate QtGui private headers (install qt6-base-private-dev)." >&2
  exit 1
fi

g++ -std=c++17 -fPIC -shared gs_input_region.cpp   -I/usr/include/x86_64-linux-gnu/qt6   -I/usr/include/x86_64-linux-gnu/qt6/QtGui   -I"$QT_PRIVATE_GUI_DIR"   -I/usr/include/x86_64-linux-gnu/qt6/QtCore   -I/usr/include/wayland   -L/usr/lib/x86_64-linux-gnu   -Wl,-rpath,/usr/lib/x86_64-linux-gnu   -lQt6Gui   -lQt6Core   -lwayland-client   -o libgs_input_region.so

echo "Built $NATIVE_DIR/libgs_input_region.so"
ldd "$NATIVE_DIR/libgs_input_region.so" | grep -E 'Qt6Gui|Qt6Core|wayland-client' || true
