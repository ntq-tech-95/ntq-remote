"""Thẻ hiển thị màn hình thu nhỏ của từng máy học sinh."""

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QContextMenuEvent, QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QVBoxLayout,
    QWidget,
)


class StudentCard(QFrame):
    """Thẻ đại diện cho một máy học sinh trong lưới giám sát."""

    selection_changed = Signal(str, bool)
    double_clicked = Signal(str)
    seat_edit_requested = Signal(str)
    showcase_requested = Signal(str)
    history_requested = Signal(str)
    wake_requested = Signal(str)
    remove_offline_requested = Signal(str)

    def __init__(
        self,
        info: dict[str, Any],
        parent: QWidget | None = None,
        is_offline: bool = False,
    ) -> None:
        super().__init__(parent)
        self.is_offline = is_offline
        self.student_id: str = str(info.get("student_id") or info.get("mac_address") or "")
        self.info: dict[str, Any] = dict(info)
        self.setObjectName("StudentCard")
        self.setFixedSize(280, 232)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Hàng tiêu đề: checkbox chọn + tên máy/học sinh
        header = QHBoxLayout()
        header.setSpacing(6)
        self.chk_select = QCheckBox()
        self.chk_select.toggled.connect(self._on_checked)
        header.addWidget(self.chk_select)

        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet("font-weight: 700; font-size: 12px; color: #0f172a;")
        header.addWidget(self.lbl_title, 1)

        self.lbl_badge = QLabel()
        self.lbl_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.lbl_badge)
        root.addLayout(header)

        # Khung ảnh màn hình học sinh
        self.lbl_screen = QLabel("Đang chờ hình ảnh màn hình...")
        self.lbl_screen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_screen.setFixedSize(262, 148)
        self.lbl_screen.setStyleSheet(
            "background-color: #1e293b; color: #94a3b8; border-radius: 6px; font-size: 11px;"
        )
        root.addWidget(self.lbl_screen)

        # Hàng thông tin chân thẻ
        footer = QHBoxLayout()
        self.lbl_meta = QLabel()
        self.lbl_meta.setStyleSheet("font-size: 11px; color: #475569;")
        footer.addWidget(self.lbl_meta, 1)
        root.addLayout(footer)

        self.update_info(info)

    def _on_checked(self, checked: bool) -> None:
        self._apply_style()
        self.selection_changed.emit(self.student_id, checked)

    def is_selected(self) -> bool:
        return self.chk_select.isChecked()

    def set_selected(self, selected: bool) -> None:
        self.chk_select.setChecked(selected)

    def update_info(self, info: dict[str, Any]) -> None:
        self.info = dict(info)
        if self.is_offline:
            self.chk_select.setEnabled(False)
            self.chk_select.setChecked(False)
            pc_name = info.get("pc_name") or "Máy học sinh"
            seat = info.get("seat_label") or ""
            mac = info.get("mac_address") or ""
            last_ip = info.get("last_ip") or ""
            display_name = f"[{seat}] {pc_name}" if seat else pc_name
            self.lbl_title.setText(display_name)
            self.lbl_title.setToolTip(display_name)
            self.lbl_meta.setText(f"MAC: {mac}  •  IP cũ: {last_ip}")
            self.lbl_badge.setText("⚪ Đang tắt")
            self.lbl_badge.setStyleSheet(
                "background:#e2e8f0; color:#475569; border-radius:4px; padding:2px 6px; font-size:11px; font-weight:600;"
            )
            self.lbl_screen.setPixmap(QPixmap())
            self.lbl_screen.setText("Máy đang tắt\n(Chuột phải để Bật máy từ xa)")
            self.lbl_screen.setStyleSheet(
                "background-color: #334155; color: #cbd5e1; border-radius: 6px; font-size: 11px;"
            )
            self._apply_style()
            return

        student_name = info.get("student_name") or ""
        pc_name = info.get("pc_name") or "Máy học sinh"
        ip_addr = info.get("ip_address") or ""
        seat = info.get("seat_label") or ""

        base_name = f"{student_name} ({pc_name})" if student_name else pc_name
        display_name = f"[{seat}] {base_name}" if seat else base_name
        self.lbl_title.setText(display_name)
        self.lbl_title.setToolTip(display_name)
        self.lbl_meta.setText(f"IP: {ip_addr}  •  Vào lúc: {info.get('connected_at', '')}")

        if info.get("hand_raised"):
            self.lbl_badge.setText("✋ Giơ tay")
            self.lbl_badge.setStyleSheet(
                "background:#fef3c7; color:#b45309; border-radius:4px; padding:2px 6px; font-size:11px; font-weight:700;"
            )
        elif info.get("locked"):
            self.lbl_badge.setText("🔒 Đang khóa")
            self.lbl_badge.setStyleSheet(
                "background:#fee2e2; color:#b91c1c; border-radius:4px; padding:2px 6px; font-size:11px; font-weight:700;"
            )
        elif info.get("blanked"):
            self.lbl_badge.setText("⬛ Tắt màn hình")
            self.lbl_badge.setStyleSheet(
                "background:#e2e8f0; color:#334155; border-radius:4px; padding:2px 6px; font-size:11px; font-weight:700;"
            )
        else:
            self.lbl_badge.setText("● Trực tuyến")
            self.lbl_badge.setStyleSheet(
                "background:#dcfce7; color:#15803d; border-radius:4px; padding:2px 6px; font-size:11px; font-weight:600;"
            )

        self._apply_style()

    def _apply_style(self) -> None:
        if self.is_offline:
            border = "1px dashed #94a3b8"
            bg = "#f8fafc"
        elif self.info.get("hand_raised"):
            border = "2px solid #f59e0b"
            bg = "#fffbeb"
        elif self.chk_select.isChecked():
            border = "2px solid #2563eb"
            bg = "#eff6ff"
        else:
            border = "1px solid #cbd5e1"
            bg = "#ffffff"
        self.setStyleSheet(
            f"#StudentCard {{ background-color: {bg}; border: {border}; border-radius: 10px; }}"
        )

    def update_frame(self, jpeg_bytes: bytes) -> None:
        img = QImage.fromData(jpeg_bytes, "JPEG")
        if img.isNull():
            return
        pix = QPixmap.fromImage(img).scaled(
            self.lbl_screen.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        self.lbl_screen.setPixmap(pix)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if not self.is_offline and event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.student_id)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        if self.is_offline:
            mac = str(self.info.get("mac_address") or "")
            act_wake = QAction("⚡ Bật máy này (Wake-on-LAN)", self)
            act_wake.triggered.connect(lambda: self.wake_requested.emit(mac))
            act_seat = QAction("🪑 Đặt số máy / vị trí chỗ ngồi...", self)
            act_seat.triggered.connect(lambda: self.seat_edit_requested.emit(mac))
            act_del = QAction("🗑 Xóa máy này khỏi danh sách đã lưu", self)
            act_del.triggered.connect(lambda: self.remove_offline_requested.emit(mac))
            menu.addAction(act_wake)
            menu.addAction(act_seat)
            menu.addSeparator()
            menu.addAction(act_del)
            menu.exec(event.globalPos())
            return

        act_view = QAction("🖥 Xem & Điều khiển từ xa", self)
        act_view.triggered.connect(lambda: self.double_clicked.emit(self.student_id))
        act_showcase = QAction("🌟 Chiếu màn hình em này cho cả lớp", self)
        act_showcase.triggered.connect(lambda: self.showcase_requested.emit(self.student_id))
        act_history = QAction("📜 Xem nhật ký hoạt động của em này", self)
        act_history.triggered.connect(lambda: self.history_requested.emit(self.student_id))
        act_seat = QAction("🪑 Đặt số máy / vị trí chỗ ngồi...", self)
        act_seat.triggered.connect(lambda: self.seat_edit_requested.emit(self.student_id))
        menu.addAction(act_view)
        menu.addAction(act_showcase)
        menu.addAction(act_history)
        menu.addSeparator()
        menu.addAction(act_seat)
        menu.exec(event.globalPos())
