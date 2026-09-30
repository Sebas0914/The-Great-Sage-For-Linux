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

    // Use one full-display layer surface so Raphael and subtitles can be
    // positioned anywhere on the desktop. The input region is managed
    // separately and stays limited to the visible controls.
    LayerShellQt::Window::Anchors anchors;
    anchors |= LayerShellQt::Window::AnchorTop;
    anchors |= LayerShellQt::Window::AnchorBottom;
    anchors |= LayerShellQt::Window::AnchorLeft;
    anchors |= LayerShellQt::Window::AnchorRight;
    layer->setAnchors(anchors);

    layer->setMargins(QMargins(0, 0, 0, 0));
    // With four anchors and zero desired size the compositor fills the
    // output, including on HiDPI displays where Qt's logical size differs.
    layer->setDesiredSize(QSize(0, 0));

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

    // Fullscreen anchors own the geometry; retain the symbol for callers
    // from older versions without changing the full-display placement.
    layer->setMargins(QMargins(0, 0, 0, 0));

    return 0;
}
