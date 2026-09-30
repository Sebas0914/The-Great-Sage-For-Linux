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
    const bool fullscreen_panel = (width >= 1000 || height >= 700);
    if (fullscreen_panel) {
        anchors |= LayerShellQt::Window::AnchorTop;
        anchors |= LayerShellQt::Window::AnchorBottom;
        anchors |= LayerShellQt::Window::AnchorLeft;
        anchors |= LayerShellQt::Window::AnchorRight;
        layer->setAnchors(anchors);
        layer->setMargins(QMargins(0, 0, 0, 0));
        layer->setExclusiveZone(-1);
        layer->setKeyboardInteractivity(
            LayerShellQt::Window::KeyboardInteractivityExclusive
        );
        layer->setActivateOnShow(true);
    } else {
        anchors |= LayerShellQt::Window::AnchorTop;
        anchors |= LayerShellQt::Window::AnchorRight;
        layer->setAnchors(anchors);
        layer->setMargins(QMargins(margin_top, margin_right, 0, 0));
        layer->setExclusiveZone(0);
        layer->setKeyboardInteractivity(
            LayerShellQt::Window::KeyboardInteractivityNone
        );
        layer->setActivateOnShow(false);
    }
    layer->setDesiredSize(QSize(width, height));
    layer->setLayer(LayerShellQt::Window::LayerOverlay);

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


extern "C" int gs_configure_panel_layer(void *window_ptr, int width, int height)
{
    auto *window = static_cast<QWindow *>(window_ptr);
    if (!window) return 1;
    auto *layer = LayerShellQt::Window::get(window);
    if (!layer) return 2;
    LayerShellQt::Window::Anchors anchors;
    anchors |= LayerShellQt::Window::AnchorTop;
    anchors |= LayerShellQt::Window::AnchorBottom;
    anchors |= LayerShellQt::Window::AnchorLeft;
    anchors |= LayerShellQt::Window::AnchorRight;
    layer->setAnchors(anchors);
    layer->setMargins(QMargins(0, 0, 0, 0));
    layer->setDesiredSize(QSize(width, height));
    layer->setExclusiveZone(-1);
    layer->setLayer(LayerShellQt::Window::LayerOverlay);
    layer->setKeyboardInteractivity(
        LayerShellQt::Window::KeyboardInteractivityExclusive
    );
    layer->setActivateOnShow(true);
    return 0;
}
