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

    // GREAT SAGE desktop mode uses one fixed, fullscreen
    // transparent LayerShell surface. Raphael itself moves
    // inside the HTML/Three.js scene.
    LayerShellQt::Window::Anchors anchors;
    anchors |= LayerShellQt::Window::AnchorTop;
    anchors |= LayerShellQt::Window::AnchorBottom;
    anchors |= LayerShellQt::Window::AnchorLeft;
    anchors |= LayerShellQt::Window::AnchorRight;

    layer->setAnchors(anchors);

    // No margins: the surface covers the complete screen.
    layer->setMargins(QMargins(0, 0, 0, 0));

    // With all four anchors the compositor determines the
    // actual surface size. Keep the desired size as a harmless
    // fallback for LayerShellQt implementations that use it.
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

    // The desktop surface is fullscreen and fixed.
    // Positioning is deliberately ignored.
    layer->setMargins(QMargins(0, 0, 0, 0));

    return 0;
}
