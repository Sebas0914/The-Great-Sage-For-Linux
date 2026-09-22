cmake_minimum_required(VERSION 3.16)

project(great_sage_layershell_bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(PYSIDE_QT
    "$ENV{HOME}/The-GREAT-SAGE-master/.venv/lib/python3.14/site-packages/PySide6/Qt"
)

find_package(LayerShellQt REQUIRED)

add_library(great_sage_layershell_bridge SHARED
    layershell_bridge.cpp
)

target_include_directories(great_sage_layershell_bridge PRIVATE
    "${PYSIDE_QT}/include"
    "${PYSIDE_QT}/include/QtCore"
    "${PYSIDE_QT}/include/QtGui"
)

target_link_libraries(great_sage_layershell_bridge PRIVATE
    LayerShellQt::Interface
    "${PYSIDE_QT}/lib/libQt6Core.so.6"
    "${PYSIDE_QT}/lib/libQt6Gui.so.6"
    "${PYSIDE_QT}/lib/libQt6WaylandClient.so.6"
    "${PYSIDE_QT}/lib/libQt6DBus.so.6"
)

set_target_properties(great_sage_layershell_bridge PROPERTIES
    PREFIX "lib"
    BUILD_RPATH "${PYSIDE_QT}/lib"
    INSTALL_RPATH "${PYSIDE_QT}/lib"
)

