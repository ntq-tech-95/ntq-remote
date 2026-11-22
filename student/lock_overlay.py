"""Màn hình khóa máy, tắt màn hình và trình chiếu màn hình giáo viên."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from common.win_hook import KeyboardBlocker


class LockOverlayWindow(QWidget):
    """Cửa sổ toàn màn hình dùng để khóa hoặc làm đen màn hình học sinh."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._active = False
        self._kbd_blocker = KeyboardBlocker()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_icon = QLabel("🔒")
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_icon.setStyleSheet("font-size: 64px; color: #ffffff;")
        layout.addWidget(self.lbl_icon)

        self.lbl_msg = QLabel("Màn hình đã bị khóa. Vui lòng chú ý nghe giảng!")
        self.lbl_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_msg.setWordWrap(True)
        self.lbl_msg.setStyleSheet(
            "font-size: 28px; font-weight: 700; color: #ffffff; padding: 20px;"
        )
        layout.addWidget(self.lbl_msg)

    def show_lock(self, message: str, blank_mode: bool = False) -> None:
        self._active = True
        screen = QGuiApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.virtualGeometry())
        if blank_mode:
            self.setStyleSheet("background-color: #000000;")
            self.lbl_icon.setText("")
            self.lbl_msg.setText("")
        else:
            self.setStyleSheet("background-color: #0f172a;")
            self.lbl_icon.setText("🔒")
            self.lbl_msg.setText(message)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self._kbd_blocker.start()

    def hide_lock(self) -> None:
        self._active = False
        self._kbd_blocker.stop()
        self.hide()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._active:
            event.ignore()
        else:
            super().closeEvent(event)


class BroadcastViewerWindow(QWidget):
    """Cửa sổ hiển thị màn hình trình chiếu trực tiếp từ máy Giáo viên."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._active = False
        self.setStyleSheet("background-color: #000000;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.lbl_banner = QLabel(
            "📡 Giáo viên đang trình chiếu màn hình — Vui lòng chú ý theo dõi"
        )
        self.lbl_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_banner.setStyleSheet(
            "background-color: #1e3a8a; color: #ffffff; font-size: 13px; font-weight: 700; padding: 6px;"
        )
        layout.addWidget(self.lbl_banner)

        self.lbl_image = QLabel("Đang nhận hình ảnh trình chiếu từ Giáo viên...")
        self.lbl_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_image.setStyleSheet("color: #cbd5e1; font-size: 16px;")
        layout.addWidget(self.lbl_image, 1)

    def set_presenter(self, presenter: str) -> None:
        self.lbl_banner.setText(
            f"📡 Đang xem trình chiếu từ: {presenter} — Vui lòng chú ý theo dõi"
        )

    def start_view(self) -> None:
        self._active = True
        screen = QGuiApplication.primaryScreen()
        if screen:
            self.setGeometry(screen.geometry())
        self.showFullScreen()
        self.raise_()

    def stop_view(self) -> None:
        self._active = False
        self.hide()

    def update_frame(self, jpeg_bytes: bytes) -> None:
        if not self._active:
            return
        img = QImage.fromData(jpeg_bytes, "JPEG")
        if img.isNull():
            return
        pix = QPixmap.fromImage(img).scaled(
            self.lbl_image.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.lbl_image.setPixmap(pix)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._active:
            event.ignore()
        else:
            super().closeEvent(event)
