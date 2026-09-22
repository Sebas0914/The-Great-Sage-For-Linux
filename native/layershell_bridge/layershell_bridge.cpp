#include <QWindow>
#include <QSize>
#include <QMargins>

#include <LayerShellQt/window.h>

extern "C" {

bool great_sage_layer_init(void *window_ptr, int width, int height, int margin)
{
    if (!window_ptr)
        return false;

    QWindow *window = static_cast<QWindow *>(window_ptr);

    LayerShellQt::Window *layer = LayerShellQt::Window::get(window);
    if (!layer)
        return false;

    layer->setLayer(LayerShellQt::Window::LayerOverlay);

    layer->setAnchors(
        LayerShellQt::Window::Anchors(
            LayerShellQt::Window::AnchorTop |
            LayerShellQt::Window::AnchorRight
        )
    );

    layer->setMargins(QMargins(margin, margin, margin, margin));

    layer->setDesiredSize(QSize(width, height));

    layer->setExclusiveZone(0);

    layer->setKeyboardInteractivity(
        LayerShellQt::Window::KeyboardInteractivityNone
    );

    layer->setScope(QStringLiteral("great-sage"));

    return true;
}

bool great_sage_layer_set_size(void *window_ptr, int width, int height)
{
    if (!window_ptr)
        return false;

    QWindow *window = static_cast<QWindow *>(window_ptr);

    LayerShellQt::Window *layer = LayerShellQt::Window::get(window);
    if (!layer)
        return false;

    layer->setDesiredSize(QSize(width, height));
    return true;
}

}
