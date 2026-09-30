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

    // The desktop Raphael host is a compositor-managed FULLSCREEN
    // transparent surface. The visual itself remains compact and is moved
    // inside this surface by hud_prototype.html.
    //
    // The previous implementation switched to fullscreen only when the
    // requested size was >=1000x700. overlay_window.py intentionally starts
    // at 340x340, so that condition was never met: Raphael was literally
    // trapped inside a 340x340 Wayland surface and got clipped. That also
    // explains why horizontal dragging could not work reliably.
    //
    // Do NOT make the layer keyboard-exclusive. Input is supplied through
    // explicit Wayland input regions, so the transparent parts of the
    // surface remain non-interactive and the desktop stays usable.
    LayerShellQt::Window::Anchors anchors;
    anchors |= LayerShellQt::Window::AnchorTop;
    anchors |= LayerShellQt::Window::AnchorBottom;
    anchors |= LayerShellQt::Window::AnchorLeft;
    anchors |= LayerShellQt::Window::AnchorRight;
    layer->setAnchors(anchors);
    layer->setMargins(QMargins(0, 0, 0, 0));
    layer->setDesiredSize(QSize(0, 0));
    layer->setExclusiveZone(-1);
    layer->setKeyboardInteractivity(
        LayerShellQt::Window::KeyboardInteractivityNone
    );
    layer->setActivateOnShow(false);
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
    layer->setDesiredSize(QSize(0, 0));
    layer->setExclusiveZone(-1);
    layer->setLayer(LayerShellQt::Window::LayerOverlay);
    layer->setKeyboardInteractivity(
        LayerShellQt::Window::KeyboardInteractivityExclusive
    );
    layer->setActivateOnShow(true);
    return 0;
}
