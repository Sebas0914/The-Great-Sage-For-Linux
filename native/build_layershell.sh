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
