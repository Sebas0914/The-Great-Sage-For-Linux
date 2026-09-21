"""Native Qt camera preview used by Great Sage's look-at-me tool.

The window is deliberately not HTML. It shows live camera frames for a few
seconds, freezes the final frame, saves it for the vision tool, and exits.
"""

import argparse
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QTimer, Qt
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


class CameraPreview(QWidget):
    def __init__(self, output: str, seconds: float):
        super().__init__()
        self.output = output
        self.seconds = max(1.0, seconds)
        self.last_frame = QImage()
        self.frozen = False

        self.setWindowTitle("Great Sage — Vision")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resize(760, 520)

        self.video = QLabel()
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setStyleSheet(
            "QLabel { background: #070b0d; color: #dce8ea; "
            "border: 1px solid rgba(255,255,255,150); }"
        )
        self.status = QLabel("RAPHAEL // CAMERA • LIVE")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet(
            "QLabel { color: #e8f2f2; background: #090d10; "
            "padding: 10px; font: 600 12px 'Sans Serif'; letter-spacing: 2px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)
        layout.addWidget(self.video, 1)
        layout.addWidget(self.status)

        devices = QMediaDevices()
        cameras = devices.videoInputs()
        if not cameras:
            self.status.setText("RAPHAEL // CAMERA UNAVAILABLE")
            QTimer.singleShot(350, QApplication.instance().quit)
            return

        self.camera = QCamera(cameras[0])
        self.session = QMediaCaptureSession()
        self.sink = QVideoSink()
        self.session.setCamera(self.camera)
        self.session.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._frame_changed)
        self.camera.start()

        self.capture_timer = QTimer(self)
        self.capture_timer.setSingleShot(True)
        self.capture_timer.timeout.connect(self._freeze_and_save)
        self.capture_timer.start(int(self.seconds * 1000))

        self.freeze_timer = None
        self._place_center()

    def _place_center(self):
        screen = self.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(
            area.center().x() - self.width() // 2,
            area.center().y() - self.height() // 2,
        )

    def _frame_changed(self, frame):
        if self.frozen or not frame.isValid():
            return
        image = frame.toImage()
        if image.isNull():
            return
        self.last_frame = image.convertToFormat(QImage.Format.Format_RGB32)
        self._show_image(self.last_frame)

    def _show_image(self, image):
        pix = QPixmap.fromImage(image)
        self.video.setPixmap(
            pix.scaled(
                self.video.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _freeze_and_save(self):
        if self.last_frame.isNull():
            self.status.setText("RAPHAEL // NO FRAME")
            QTimer.singleShot(300, QApplication.instance().quit)
            return

        self.frozen = True
        self.status.setText("RAPHAEL // CAPTURED")
        self._show_image(self.last_frame)

        image = self.last_frame
        if image.width() > 1280 or image.height() > 1280:
            image = image.scaled(
                1280, 1280,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        if not image.save(self.output, "JPG", 88):
            self.status.setText("RAPHAEL // CAPTURE FAILED")
        QTimer.singleShot(350, QApplication.instance().quit)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--seconds", type=float, default=3.0)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    win = CameraPreview(args.output, args.seconds)
    win.show()
    win.raise_()
    win.activateWindow()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
