#include <QGuiApplication>
#include <QWindow>
#include <qpa/qplatformnativeinterface.h>
#include <wayland-client.h>

extern "C" int gs_set_input_region(
    void *window_ptr,
    int x,
    int y,
    int width,
    int height)
{
    auto *window = static_cast<QWindow *>(window_ptr);
    if (!window) return 1;

    auto *native = QGuiApplication::platformNativeInterface();
    if (!native) return 2;

    auto *surface = static_cast<wl_surface *>(
        native->nativeResourceForWindow("surface", window));

    if (!surface) return 3;

    auto *compositor = static_cast<wl_compositor *>(
        native->nativeResourceForIntegration("compositor"));

    if (!compositor) return 4;

    wl_region *region = wl_compositor_create_region(compositor);
    if (!region) return 5;

    if (width > 0 && height > 0) {
        wl_region_add(region, x, y, width, height);
    }

    wl_surface_set_input_region(surface, region);
    wl_region_destroy(region);

    wl_surface_commit(surface);

    return 0;
}


extern "C" int gs_set_input_regions(
    void *window_ptr,
    const int *rects,
    int count)
{
    auto *window = static_cast<QWindow *>(window_ptr);
    if (!window) return 1;

    if (count < 0 || (count > 0 && !rects)) return 2;

    auto *native = QGuiApplication::platformNativeInterface();
    if (!native) return 3;

    auto *surface = static_cast<wl_surface *>(
        native->nativeResourceForWindow("surface", window));

    if (!surface) return 4;

    auto *compositor = static_cast<wl_compositor *>(
        native->nativeResourceForIntegration("compositor"));

    if (!compositor) return 5;

    wl_region *region = wl_compositor_create_region(compositor);
    if (!region) return 6;

    for (int i = 0; i < count; ++i) {
        const int x = rects[i * 4 + 0];
        const int y = rects[i * 4 + 1];
        const int width = rects[i * 4 + 2];
        const int height = rects[i * 4 + 3];

        if (width > 0 && height > 0) {
            wl_region_add(region, x, y, width, height);
        }
    }

    wl_surface_set_input_region(surface, region);
    wl_region_destroy(region);

    wl_surface_commit(surface);

    return 0;
}
