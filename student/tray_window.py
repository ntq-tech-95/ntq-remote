"""Giao diện chính và biểu tượng khay hệ thống dành cho Máy Học Sinh."""

import os
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from common.autostart import (
    STUDENT_AUTOSTART_KEY,
    build_launch_command,
    is_autostart_enabled,
    set_autostart,
)
from common.config import APP_AUTHOR, APP_NAME, APP_VERSION, WS_PORT
from common.network import get_student_inbox_dir
from common.ui_helpers import load_app_icon
from student.app_update import launch_detached_updater
from student.client import StudentClient
from student.exam_dialog import StudentExamDialog
from student.lock_overlay import BroadcastViewerWindow, LockOverlayWindow
from student.quiz_dialog import StudentQuizDialog


def _create_app_icon() -> QIcon:
    ico = load_app_icon()
    if not ico.isNull():
        return ico
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2563eb"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)
    painter.setPen(QColor("#ffffff"))
    font = painter.font()
    font.setPointSize(22)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "HS")
    painter.end()
    return QIcon(pix)


class StudentMainWindow(QMainWindow):
    """Bảng điều khiển gọn nhẹ 100% Tiếng Việt cho Máy Học Sinh."""

    def __init__(self, client: StudentClient) -> None:
        super().__init__()
        self.client = client
        self._allow_quit = False
        self._locked = False
        self._blanked = False
        self._lock_msg = ""

        self._lock_overlay = LockOverlayWindow()
        self._broadcast_win = BroadcastViewerWindow()

        self.setWindowTitle(f"{APP_NAME} — Máy Học Sinh (v{APP_VERSION}) | {APP_AUTHOR}")
        self.setWindowIcon(_create_app_icon())
        self.resize(460, 580)

        self._setup_ui()
        self._setup_tray()
        self._connect_signals()
        self.client.start()

    def _setup_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background-color: #f8fafc; }
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 7px 12px;
                font-size: 12px;
                font-weight: 600;
                color: #0f172a;
            }
            QPushButton:hover { background-color: #e2e8f0; }
            """
        )

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # Trạng thái kết nối
        self.lbl_status = QLabel("🔴 Đang tìm máy Giáo viên trong mạng LAN...")
        self.lbl_status.setStyleSheet(
            "background:#fee2e2; color:#991b1b; padding:8px 10px; border-radius:8px; font-weight:700;"
        )
        root.addWidget(self.lbl_status)

        # Khung chọn lớp / nhập IP giáo viên
        conn_box = QFrame()
        conn_box.setStyleSheet(
            "QFrame { background:#ffffff; border:1px solid #cbd5e1; border-radius:8px; }"
        )
        cl = QVBoxLayout(conn_box)
        cl.setContentsMargins(10, 10, 10, 10)
        cl.setSpacing(6)

        lbl_conn = QLabel("🌐 Kết nối tới máy Giáo viên")
        lbl_conn.setStyleSheet("font-weight:700; border:none;")
        cl.addWidget(lbl_conn)

        self.cmb_rooms = QComboBox()
        self.cmb_rooms.addItem("Tự động dò tìm trong mạng LAN...", "")
        self.cmb_rooms.currentIndexChanged.connect(self._on_room_selected)
        cl.addWidget(self.cmb_rooms)

        ip_row = QHBoxLayout()
        self.edt_ip = QLineEdit(self.client.manual_host)
        self.edt_ip.setPlaceholderText("Hoặc nhập IP Giáo viên (VD: 192.168.1.10 hoặc 127.0.0.1)")
        ip_row.addWidget(self.edt_ip, 1)

        btn_connect = QPushButton("Kết nối")
        btn_connect.clicked.connect(self._on_manual_connect)
        ip_row.addWidget(btn_connect)
        cl.addLayout(ip_row)

        room_row = QHBoxLayout()
        self.edt_room = QLineEdit(self.client.target_room)
        self.edt_room.setPlaceholderText("Khóa theo mã phòng (trống = tự tìm, VD: PHONG-TIN-01)")
        room_row.addWidget(self.edt_room, 1)

        btn_room_lock = QPushButton("Áp dụng phòng")
        btn_room_lock.clicked.connect(self._on_apply_target_room)
        room_row.addWidget(btn_room_lock)
        cl.addLayout(room_row)
        root.addWidget(conn_box)

        # Khung điểm danh họ tên học sinh
        name_box = QFrame()
        name_box.setStyleSheet(
            "QFrame { background:#ffffff; border:1px solid #cbd5e1; border-radius:8px; }"
        )
        nl = QVBoxLayout(name_box)
        nl.setContentsMargins(10, 10, 10, 10)
        nl.setSpacing(6)

        lbl_name = QLabel(f"🧑‍🎓 Điểm danh học sinh (Tên máy: {self.client.pc_name})")
        lbl_name.setStyleSheet("font-weight:700; border:none;")
        nl.addWidget(lbl_name)

        name_row = QHBoxLayout()
        self.edt_name = QLineEdit(self.client.student_name)
        self.edt_name.setPlaceholderText("Nhập họ và tên của em...")
        self.edt_name.returnPressed.connect(self._on_save_name)
        name_row.addWidget(self.edt_name, 1)

        btn_save_name = QPushButton("Xác nhận tên")
        btn_save_name.clicked.connect(self._on_save_name)
        name_row.addWidget(btn_save_name)
        nl.addLayout(name_row)
        root.addWidget(name_box)

        # Các nút thao tác nhanh của Học sinh
        action_row = QHBoxLayout()
        self.btn_hand = QPushButton("✋ Giơ tay xin hỗ trợ")
        self.btn_hand.setCheckable(True)
        self.btn_hand.toggled.connect(self._on_toggle_hand)
        action_row.addWidget(self.btn_hand)

        btn_submit = QPushButton("📤 Nộp bài cho Giáo viên")
        btn_submit.clicked.connect(self._on_submit_file)
        action_row.addWidget(btn_submit)
        root.addLayout(action_row)

        btn_inbox = QPushButton("📂 Mở thư mục bài tập Giáo viên đã gửi")
        btn_inbox.clicked.connect(lambda: os.startfile(str(get_student_inbox_dir())))
        root.addWidget(btn_inbox)

        self.chk_autostart = QCheckBox("Tự động khởi động cùng Windows")
        self.chk_autostart.setStyleSheet("font-weight: 600; color: #0f172a;")
        self.chk_autostart.setChecked(is_autostart_enabled(STUDENT_AUTOSTART_KEY))
        self.chk_autostart.toggled.connect(self._on_toggle_autostart)
        root.addWidget(self.chk_autostart)

        # Khung nhắn tin với giáo viên
        lbl_chat = QLabel("💬 Nhắn tin với Giáo viên")
        lbl_chat.setStyleSheet("font-weight:700;")
        root.addWidget(lbl_chat)

        self.txt_chat = QTextEdit()
        self.txt_chat.setReadOnly(True)
        self.txt_chat.setStyleSheet("background:#ffffff; font-size:12px;")
        root.addWidget(self.txt_chat, 1)

        chat_row = QHBoxLayout()
        self.edt_chat = QLineEdit()
        self.edt_chat.setPlaceholderText("Nhập tin nhắn gửi thầy/cô...")
        self.edt_chat.returnPressed.connect(self._on_send_chat)
        chat_row.addWidget(self.edt_chat, 1)

        btn_send = QPushButton("Gửi")
        btn_send.clicked.connect(self._on_send_chat)
        chat_row.addWidget(btn_send)
        root.addLayout(chat_row)

        lbl_author = QLabel(f"© Bản quyền phần mềm thuộc về {APP_AUTHOR}")
        lbl_author.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_author.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 600;")
        root.addWidget(lbl_author)

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(_create_app_icon(), self)
        menu = QMenu()
        act_open = QAction("Mở bảng Học sinh", self)
        act_open.triggered.connect(self.showNormal)
        act_hand = QAction("Giơ tay xin hỗ trợ", self)
        act_hand.triggered.connect(lambda: self.btn_hand.toggle())
        act_submit = QAction("Nộp bài tập", self)
        act_submit.triggered.connect(self._on_submit_file)
        self.act_autostart = QAction("Khởi động cùng Windows", self)
        self.act_autostart.setCheckable(True)
        self.act_autostart.setChecked(self.chk_autostart.isChecked())
        self.act_autostart.toggled.connect(self._on_toggle_autostart)
        act_quit = QAction("Thoát ứng dụng", self)
        act_quit.triggered.connect(self._quit_app)

        menu.addAction(act_open)
        menu.addAction(act_hand)
        menu.addAction(act_submit)
        menu.addSeparator()
        menu.addAction(self.act_autostart)
        menu.addSeparator()
        menu.addAction(act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()
            self.activateWindow()

    def _connect_signals(self) -> None:
        s = self.client.signals
        s.connection_changed.connect(self._on_connection_changed)
        s.rooms_discovered.connect(self._on_rooms_discovered)
        s.lock_changed.connect(self._on_lock_changed)
        s.blank_changed.connect(self._on_blank_changed)
        s.broadcast_changed.connect(self._on_broadcast_changed)
        s.broadcast_presenter.connect(self._broadcast_win.set_presenter)
        s.broadcast_frame.connect(self._broadcast_win.update_frame)
        s.chat_received.connect(self._on_chat_received)
        s.announcement_received.connect(self._on_announcement)
        s.file_received.connect(self._on_file_received)
        s.collect_requested.connect(self._on_collect_requested)
        s.quiz_received.connect(self._on_quiz_received)
        s.exam_received.connect(self._on_exam_received)
        s.exam_result_received.connect(self._on_exam_result)
        s.hand_acknowledged.connect(self._on_hand_ack)
        s.update_ready.connect(self._on_update_ready)
        s.status_message.connect(self._append_log)

    def _append_log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.txt_chat.append(f"[{stamp}] {text}")

    def _on_connection_changed(self, connected: bool, message: str) -> None:
        if connected:
            self.lbl_status.setText(f"🟢 {message}")
            self.lbl_status.setStyleSheet(
                "background:#dcfce7; color:#166534; padding:8px 10px; border-radius:8px; font-weight:700;"
            )
        else:
            self.lbl_status.setText(f"🔴 {message}")
            self.lbl_status.setStyleSheet(
                "background:#fee2e2; color:#991b1b; padding:8px 10px; border-radius:8px; font-weight:700;"
            )

    def _on_rooms_discovered(self, rooms: list[dict[str, Any]]) -> None:
        current = self.cmb_rooms.currentData()
        self.cmb_rooms.blockSignals(True)
        self.cmb_rooms.clear()
        self.cmb_rooms.addItem("Tự động chọn phòng tìm thấy trong LAN", "")
        for r in rooms:
            label = f"{r['room_code']} — {r['teacher_name']} ({r['host_ip']})"
            self.cmb_rooms.addItem(label, r["host_ip"])
        if current:
            idx = self.cmb_rooms.findData(current)
            if idx >= 0:
                self.cmb_rooms.setCurrentIndex(idx)
        self.cmb_rooms.blockSignals(False)

    def _on_room_selected(self, idx: int) -> None:
        ip = self.cmb_rooms.itemData(idx)
        if ip:
            self.edt_ip.setText(str(ip))
            self.client.set_manual_host(str(ip), WS_PORT)

    def _on_manual_connect(self) -> None:
        ip = self.edt_ip.text().strip()
        self.client.set_manual_host(ip, WS_PORT)
        self._append_log(
            f"🔄 Đang kết nối tới {ip or 'chế độ tự dò LAN'}..."
        )

    def _on_apply_target_room(self) -> None:
        room = self.edt_room.text().strip()
        self.client.set_target_room(room)
        self._append_log(
            f"🏫 Đã đặt lọc phòng: {room or 'Tự động nhận bất kỳ phòng nào trong LAN'}"
        )

    def _ask_teacher_password(self, reason: str) -> bool:
        pwd, ok = QInputDialog.getText(
            self,
            "Yêu cầu mật khẩu Giáo viên",
            f"{reason}\nVui lòng nhập mật khẩu giáo viên (mặc định: 123456):",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return False
        if not self.client.verify_teacher_password(pwd):
            QMessageBox.warning(self, "Sai mật khẩu", "Mật khẩu giáo viên không đúng.")
            return False
        return True

    def _on_toggle_autostart(self, checked: bool) -> None:
        if not checked and not self._ask_teacher_password(
            "Cần mật khẩu giáo viên để tắt tự khởi động cùng Windows."
        ):
            for w in (self.chk_autostart, self.act_autostart):
                w.blockSignals(True)
                w.setChecked(True)
                w.blockSignals(False)
            return
        cmd = build_launch_command("run_student.py", "--student") if checked else None
        ok, msg = set_autostart(STUDENT_AUTOSTART_KEY, checked, cmd)
        target_state = checked if ok else not checked
        for w in (self.chk_autostart, self.act_autostart):
            w.blockSignals(True)
            w.setChecked(target_state)
            w.blockSignals(False)
        if not ok:
            QMessageBox.warning(self, "Khởi động cùng Windows", msg)
            return
        self._append_log(f"⚙ {msg}")

    def _on_save_name(self) -> None:
        name = self.edt_name.text().strip()
        if not name:
            return
        self.client.set_student_name(name)
        self._append_log(f"✔ Đã cập nhật tên điểm danh: {name}")

    def _on_toggle_hand(self, checked: bool) -> None:
        self.client.set_hand_raised(checked)
        if checked:
            self.btn_hand.setText("✋ Đang giơ tay (Bấm để hạ tay)")
            self.btn_hand.setStyleSheet(
                "background:#fef3c7; border-color:#f59e0b; color:#92400e;"
            )
            self._append_log("✋ Em đã giơ tay xin giáo viên hỗ trợ.")
        else:
            self.btn_hand.setText("✋ Giơ tay xin hỗ trợ")
            self.btn_hand.setStyleSheet("")

    def _on_hand_ack(self) -> None:
        self.btn_hand.blockSignals(True)
        self.btn_hand.setChecked(False)
        self.btn_hand.setText("✋ Giơ tay xin hỗ trợ")
        self.btn_hand.setStyleSheet("")
        self.btn_hand.blockSignals(False)
        self._append_log("✔ Giáo viên đã xác nhận hỗ trợ.")

    def _on_lock_changed(self, locked: bool, msg: str) -> None:
        self._locked = locked
        self._lock_msg = msg
        self._refresh_overlay()

    def _on_blank_changed(self, blanked: bool, msg: str) -> None:
        self._blanked = blanked
        self._refresh_overlay()

    def _refresh_overlay(self) -> None:
        if self._blanked:
            self._lock_overlay.show_lock("", blank_mode=True)
        elif self._locked:
            self._lock_overlay.show_lock(self._lock_msg, blank_mode=False)
        else:
            self._lock_overlay.hide_lock()

    def _on_broadcast_changed(self, active: bool) -> None:
        if active:
            self._broadcast_win.start_view()
        else:
            self._broadcast_win.stop_view()

    def _on_chat_received(self, sender: str, text: str) -> None:
        self._append_log(f"💬 <b>{sender}</b>: {text}")
        self.showNormal()

    def _on_announcement(self, title: str, text: str) -> None:
        self._append_log(f"📢 <b>{title}</b>: {text}")
        QMessageBox.information(self, title, text)

    def _on_file_received(self, filename: str, saved_path: str) -> None:
        self._append_log(f"📥 Đã nhận bài tập '{filename}' → {saved_path}")
        self.tray.showMessage(
            "Nhận bài tập mới",
            f"Giáo viên đã gửi tệp '{filename}'. Lưu tại: {saved_path}",
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    def _on_collect_requested(self, note: str) -> None:
        msg = note or "Giáo viên yêu cầu nộp bài. Em hãy chọn tệp bài làm để gửi!"
        self._append_log(f"📤 Yêu cầu nộp bài: {msg}")
        reply = QMessageBox.question(
            self,
            "Giáo viên yêu cầu nộp bài",
            f"{msg}\n\nEm có muốn chọn tệp để nộp ngay bây giờ không?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._on_submit_file()

    def _on_quiz_received(self, data: dict[str, Any]) -> None:
        quiz_id = str(data.get("quiz_id") or "")
        question = str(data.get("question") or "")
        options = [str(x) for x in data.get("options", [])]
        if not quiz_id or not question or not options:
            return
        self.showNormal()
        self.raise_()
        dlg = StudentQuizDialog(quiz_id, question, options, self)
        dlg.answer_submitted.connect(self.client.send_quiz_answer)
        dlg.exec()

    def _on_exam_received(self, data: dict[str, Any]) -> None:
        exam_id = str(data.get("exam_id") or "")
        title = str(data.get("title") or "Bài kiểm tra")
        duration = int(data.get("duration_minutes") or 10)
        questions = list(data.get("questions") or [])
        if not exam_id or not questions:
            return
        self.showNormal()
        self.raise_()
        dlg = StudentExamDialog(exam_id, title, duration, questions, self)
        dlg.exam_submitted.connect(self.client.submit_exam)
        dlg.exec()

    def _on_exam_result(self, data: dict[str, Any]) -> None:
        title = str(data.get("title") or "Bài kiểm tra")
        correct = int(data.get("correct") or 0)
        total = int(data.get("total") or 0)
        score = float(data.get("score") or 0.0)
        msg = f"Kết quả '{title}': {correct}/{total} câu đúng — Điểm: {score:.2f}/10"
        self._append_log(f"🏆 {msg}")
        QMessageBox.information(self, "Kết quả bài kiểm tra", msg)

    def _on_submit_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn tệp bài làm để nộp cho Giáo viên"
        )
        if file_path:
            self.client.submit_file(file_path)

    def _on_send_chat(self) -> None:
        text = self.edt_chat.text().strip()
        if not text:
            return
        self.client.send_chat(text)
        self._append_log(f"💬 <b>Em</b>: {text}")
        self.edt_chat.clear()

    def _on_update_ready(self, bat_path: str) -> None:
        self._append_log("🔄 Đang khởi động lại để cập nhật phiên bản mới từ Giáo viên...")
        self._allow_quit = True
        self._lock_overlay.hide_lock()
        self._broadcast_win.stop_view()
        self.client.stop()
        self.tray.hide()
        launch_detached_updater(Path(bat_path))
        app = QApplication.instance()
        if app:
            app.quit()

    def _quit_app(self) -> None:
        if not self._ask_teacher_password("Cần mật khẩu giáo viên để thoát ứng dụng Học sinh."):
            return
        self._allow_quit = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._allow_quit:
            event.ignore()
            self.hide()
            self.tray.showMessage(
                APP_NAME,
                "Ứng dụng vẫn đang chạy ngầm ở khay hệ thống. Nhấp đúp biểu tượng HS để mở lại.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            return

        self._lock_overlay.hide_lock()
        self._broadcast_win.stop_view()
        self.client.stop()
        self.tray.hide()
        super().closeEvent(event)
