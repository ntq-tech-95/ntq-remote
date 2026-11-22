"""Cửa sổ phóng to xem màn hình và điều khiển từ xa máy học sinh."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QImage, QKeyEvent, QMouseEvent, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _RemoteScreenLabel(QLabel):
    """Khung hiển thị ảnh màn hình có bắt sự kiện chuột/bàn phím."""

    input_event = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.control_enabled = False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("background-color: #0f172a; color: #cbd5e1;")
        self._pixmap_rect_norm = (0.0, 0.0, 1.0, 1.0)

    def set_frame(self, jpeg_bytes: bytes) -> None:
        img = QImage.fromData(jpeg_bytes, "JPEG")
        if img.isNull():
            return
        scaled = QPixmap.fromImage(img).scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)

    def _norm_coords(self, pos) -> tuple[float, float] | None:
        pix = self.pixmap()
        if pix is None or pix.isNull():
            return None
        pw, ph = pix.width(), pix.height()
        lw, lh = self.width(), self.height()
        ox = (lw - pw) / 2.0
        oy = (lh - ph) / 2.0
        rx = (pos.x() - ox) / max(1, pw)
        ry = (pos.y() - oy) / max(1, ph)
        if rx < 0.0 or rx > 1.0 or ry < 0.0 or ry > 1.0:
            return None
        return rx, ry

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.control_enabled:
            coords = self._norm_coords(event.position())
            if coords:
                self.input_event.emit({"action": "move", "x": coords[0], "y": coords[1]})
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.setFocus()
        if self.control_enabled:
            coords = self._norm_coords(event.position())
            if coords:
                btn = "right" if event.button() == Qt.MouseButton.RightButton else "left"
                self.input_event.emit(
                    {"action": "down", "x": coords[0], "y": coords[1], "button": btn}
                )
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.control_enabled:
            coords = self._norm_coords(event.position())
            if coords:
                btn = "right" if event.button() == Qt.MouseButton.RightButton else "left"
                self.input_event.emit(
                    {"action": "up", "x": coords[0], "y": coords[1], "button": btn}
                )
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self.control_enabled:
            coords = self._norm_coords(event.position())
            if coords:
                self.input_event.emit(
                    {"action": "dblclick", "x": coords[0], "y": coords[1], "button": "left"}
                )
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.control_enabled:
            coords = self._norm_coords(event.position())
            if coords:
                dy = 1 if event.angleDelta().y() > 0 else -1
                self.input_event.emit(
                    {"action": "scroll", "x": coords[0], "y": coords[1], "dy": dy}
                )
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.control_enabled:
            qt_key = event.key()
            if qt_key in (
                Qt.Key.Key_Control,
                Qt.Key.Key_Shift,
                Qt.Key.Key_Alt,
                Qt.Key.Key_Meta,
            ):
                return

            mods: list[str] = []
            qt_mods = event.modifiers()
            if qt_mods & Qt.KeyboardModifier.ControlModifier:
                mods.append("ctrl")
            if qt_mods & Qt.KeyboardModifier.ShiftModifier:
                mods.append("shift")
            if qt_mods & Qt.KeyboardModifier.AltModifier:
                mods.append("alt")

            key_map = {
                Qt.Key.Key_Return: "enter",
                Qt.Key.Key_Enter: "enter",
                Qt.Key.Key_Backspace: "backspace",
                Qt.Key.Key_Tab: "tab",
                Qt.Key.Key_Backtab: "tab",
                Qt.Key.Key_Escape: "escape",
                Qt.Key.Key_Space: "space",
                Qt.Key.Key_Delete: "delete",
                Qt.Key.Key_Up: "up",
                Qt.Key.Key_Down: "down",
                Qt.Key.Key_Left: "left",
                Qt.Key.Key_Right: "right",
                Qt.Key.Key_Home: "home",
                Qt.Key.Key_End: "end",
                Qt.Key.Key_PageUp: "page_up",
                Qt.Key.Key_PageDown: "page_down",
                Qt.Key.Key_F1: "f1",
                Qt.Key.Key_F2: "f2",
                Qt.Key.Key_F3: "f3",
                Qt.Key.Key_F4: "f4",
                Qt.Key.Key_F5: "f5",
                Qt.Key.Key_F6: "f6",
                Qt.Key.Key_F7: "f7",
                Qt.Key.Key_F8: "f8",
                Qt.Key.Key_F9: "f9",
                Qt.Key.Key_F10: "f10",
                Qt.Key.Key_F11: "f11",
                Qt.Key.Key_F12: "f12",
            }
            special = key_map.get(qt_key, "")
            if special:
                self.input_event.emit(
                    {"action": "key", "key": special, "text": "", "modifiers": mods}
                )
            elif mods and (
                Qt.Key.Key_A <= qt_key <= Qt.Key.Key_Z
                or Qt.Key.Key_0 <= qt_key <= Qt.Key.Key_9
            ):
                self.input_event.emit(
                    {"action": "key", "key": chr(qt_key).lower(), "text": "", "modifiers": mods}
                )
            elif event.text():
                self.input_event.emit(
                    {"action": "key", "key": "", "text": event.text(), "modifiers": []}
                )
            return
        super().keyPressEvent(event)


class RemoteViewDialog(QDialog):
    """Cửa sổ phóng to màn hình và điều khiển từ xa một máy học sinh."""

    input_sent = Signal(str, dict)
    dialog_closed = Signal(str)

    def __init__(self, student_id: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.student_id = student_id
        self.setWindowTitle(f"Xem & Điều khiển: {title}")
        self.resize(1080, 680)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        self.lbl_info = QLabel(f"Đang xem màn hình: {title}")
        self.lbl_info.setStyleSheet("font-weight: 700; font-size: 13px;")
        bar.addWidget(self.lbl_info, 1)

        self.btn_control = QPushButton("🖱️ Bật điều khiển chuột & bàn phím")
        self.btn_control.setCheckable(True)
        self.btn_control.toggled.connect(self._toggle_control)
        bar.addWidget(self.btn_control)

        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.close)
        bar.addWidget(btn_close)
        layout.addLayout(bar)

        self.screen_label = _RemoteScreenLabel()
        self.screen_label.setText("Đang tải hình ảnh độ nét cao từ máy học sinh...")
        self.screen_label.input_event.connect(
            lambda payload: self.input_sent.emit(self.student_id, payload)
        )
        layout.addWidget(self.screen_label, 1)

    def _toggle_control(self, checked: bool) -> None:
        self.screen_label.control_enabled = checked
        if checked:
            self.btn_control.setText("🟢 Đang điều khiển từ xa (Bấm để tắt)")
            self.btn_control.setStyleSheet("background-color:#dcfce7; font-weight:700;")
            self.screen_label.setFocus()
        else:
            self.btn_control.setText("🖱️ Bật điều khiển chuột & bàn phím")
            self.btn_control.setStyleSheet("")

    def update_frame(self, jpeg_bytes: bytes) -> None:
        self.screen_label.set_frame(jpeg_bytes)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.dialog_closed.emit(self.student_id)
        super().closeEvent(event)
