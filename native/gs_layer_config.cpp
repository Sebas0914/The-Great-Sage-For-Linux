#include <QWindow>
#include <QSize>
#include <QMargins>
#include <LayerShellQt/window.h>

extern "C" int gs_configure_layer(
    void *window_ptr,
    int width,
    int height,
    int margin_top,
    int margin_right)
{
    auto *window = static_cast<QWindow *>(window_ptr);
    if (!window) return 1;

    auto *layer = LayerShellQt::Window::get(window);
    if (!layer) return 2;

    // Keep the LayerShell surface the same size as the Raphael overlay.
    // Anchoring all four edges makes it fullscreen; on some QtWebEngine
    // Wayland paths that turns the transparent Chromium background into a
    // black fullscreen surface, blocking the entire desktop.
    //
    // Top + right anchors give us a small, compositor-managed surface that
    // stays above normal windows without needing fullscreen input capture.
    LayerShellQt::Window::Anchors anchors;
    anchors |= LayerShellQt::Window::AnchorTop;
    anchors |= LayerShellQt::Window::AnchorRight;
    layer->setAnchors(anchors);

    // These margins place the small surface near the top-right corner.
    layer->setMargins(QMargins(margin_top, margin_right, 0, 0));
    layer->setDesiredSize(QSize(width, height));

    layer->setExclusiveZone(0);
    layer->setLayer(LayerShellQt::Window::LayerOverlay);

    layer->setKeyboardInteractivity(
        LayerShellQt::Window::KeyboardInteractivityNone
    );

    layer->setActivateOnShow(false);

    return 0;
}

extern "C" int gs_position_layer(
    void *window_ptr,
    int margin_top,
    int margin_right)
{
    auto *window = static_cast<QWindow *>(window_ptr);
    if (!window) return 1;

    auto *layer = LayerShellQt::Window::get(window);
    if (!layer) return 2;

    // Position the small top-right LayerShell surface using its margins.
    layer->setMargins(QMargins(margin_top, margin_right, 0, 0));

    return 0;
}
