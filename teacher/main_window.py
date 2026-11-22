"""Cửa sổ chính của phần mềm Quản lý Phòng Tin Học (Máy Giáo Viên)."""

import csv
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from common.autostart import (
    TEACHER_AUTOSTART_KEY,
    build_launch_command,
    is_autostart_enabled,
    set_autostart,
)
from common.config import (
    APP_AUTHOR,
    APP_NAME,
    APP_VERSION,
    DEFAULT_ROOM_CODE,
    DEFAULT_TEACHER_NAME,
)
from common.network import get_local_ip, get_teacher_collect_dir
from common.recorder import ScreenRecorder
from common.ui_helpers import load_app_icon
from teacher.annotation_overlay import AnnotationController
from teacher.dialogs import PolicyDialog, QuizTeacherDialog, WakeOnLanDialog
from teacher.exam_dialog import ExamTeacherDialog
from teacher.license_dialog import LicenseDialog
from teacher.remote_dialog import RemoteViewDialog
from teacher.server import TeacherServer
from teacher.student_card import StudentCard
from teacher.update_dialog import OnlineUpdateDialog
from common.updater import fetch_update_manifest, is_newer_version


class TeacherMainWindow(QMainWindow):
    """Giao diện điều khiển trung tâm 100% Tiếng Việt dành cho Giáo viên."""

    _online_update_found = Signal(dict)

    def __init__(self, server: TeacherServer) -> None:
        super().__init__()
        self.server = server
        self._cards: dict[str, StudentCard] = {}
        self._offline_cards: dict[str, StudentCard] = {}
        self._remote_dialog: RemoteViewDialog | None = None
        self._quiz_dialog: QuizTeacherDialog | None = None
        self._exam_dialog: ExamTeacherDialog | None = None
        self._annotation = AnnotationController(on_closed=self._on_annotation_closed)
        self._recorder = ScreenRecorder()
        self._is_broadcasting = False
        self._is_showcasing = False
        self._is_audio_broadcasting = False
        self._available_manifest: dict[str, Any] | None = None

        self.setWindowTitle(f"{APP_NAME} — Máy Giáo Viên (v{APP_VERSION}) | Tác giả: {APP_AUTHOR}")
        icon = load_app_icon()
        if not icon.isNull():
            self.setWindowIcon(icon)
        self.resize(1340, 820)

        self._setup_ui()
        self._connect_signals()
        self._online_update_found.connect(self._on_silent_update_found)
        self._sync_offline_cards()
        self.server.start()
        if self.server.auto_check_update and self.server.enable_discovery:
            QTimer.singleShot(4000, self._schedule_silent_update_check)

    def _setup_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background-color: #f1f5f9; }
            QPushButton, QToolButton {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 600;
                color: #0f172a;
            }
            QPushButton:hover, QToolButton:hover {
                background-color: #e2e8f0;
            }
            QPushButton:checked {
                background-color: #2563eb;
                color: #ffffff;
                border-color: #1d4ed8;
            }
            """
        )

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # Thanh thông tin lớp học phía trên
        top_bar = QFrame()
        top_bar.setStyleSheet(
            "background-color: #1e3a8a; color: #ffffff; border-radius: 8px;"
        )
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 8, 12, 8)

        self.lbl_room = QLabel()
        self.lbl_room.setStyleSheet("font-size: 14px; font-weight: 700; color: #ffffff;")
        self._refresh_room_banner()
        top_layout.addWidget(self.lbl_room, 1)

        self.lbl_target = QLabel("Đối tượng thao tác: Toàn bộ lớp (0 máy)")
        self.lbl_target.setStyleSheet(
            "background:#1d4ed8; color:#e0f2fe; padding:4px 10px; border-radius:6px; font-weight:600;"
        )
        top_layout.addWidget(self.lbl_target)

        self.chk_autostart = QCheckBox("Khởi động cùng Windows")
        self.chk_autostart.setStyleSheet(
            "color: #ffffff; font-weight: 600; font-size: 12px; padding: 0 6px;"
        )
        self.chk_autostart.setChecked(is_autostart_enabled(TEACHER_AUTOSTART_KEY))
        self.chk_autostart.toggled.connect(self._on_toggle_autostart)
        top_layout.addWidget(self.chk_autostart)

        btn_pwd = QPushButton("🔑 Mật khẩu lớp")
        btn_pwd.setToolTip("Đặt mật khẩu để học sinh không tự tắt ứng dụng (mặc định: 123456)")
        btn_pwd.clicked.connect(self._on_change_password)
        top_layout.addWidget(btn_pwd)

        btn_lic = QPushButton("🔐 Bản quyền")
        btn_lic.setToolTip("Xem thông tin bản quyền hoặc nạp mã kích hoạt mới")
        btn_lic.clicked.connect(self._on_open_license)
        top_layout.addWidget(btn_lic)

        btn_edit_room = QPushButton("👨‍🏫 Đổi tên GV / Phòng")
        btn_edit_room.setToolTip("Đổi tên Giáo viên hiển thị và Mã phòng / Tên lớp")
        btn_edit_room.clicked.connect(self._on_edit_room)
        top_layout.addWidget(btn_edit_room)

        self.btn_update = QPushButton("🔄 Cập nhật")
        self.btn_update.setToolTip("Kiểm tra phiên bản mới từ Internet & cập nhật máy Học sinh qua LAN")
        self.btn_update.clicked.connect(self._on_open_update_dialog)
        top_layout.addWidget(self.btn_update)
        main_layout.addWidget(top_bar)

        # Thanh công cụ chức năng chính (2 hàng gọn gàng)
        toolbar_frame = QFrame()
        toolbar_frame.setStyleSheet(
            "background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px;"
        )
        tb_root = QVBoxLayout(toolbar_frame)
        tb_root.setContentsMargins(8, 6, 8, 6)
        tb_root.setSpacing(6)

        tb1 = QHBoxLayout()
        tb1.setSpacing(6)

        btn_view = QPushButton("🖥 Xem / Điều khiển")
        btn_view.setToolTip("Phóng to và điều khiển từ xa máy học sinh đang chọn")
        btn_view.clicked.connect(self._on_open_remote_selected)
        tb1.addWidget(btn_view)

        self.btn_broadcast = QPushButton("📡 Trình chiếu màn hình")
        self.btn_broadcast.setCheckable(True)
        self.btn_broadcast.setToolTip("Chiếu màn hình giáo viên xuống máy học sinh")
        self.btn_broadcast.toggled.connect(self._on_toggle_broadcast)
        tb1.addWidget(self.btn_broadcast)

        self.cmb_broadcast_mode = QComboBox()
        self.cmb_broadcast_mode.addItem("⚡ Tự động thích ứng (Khuyên dùng)", ("auto", 0, 0, 0.0, 0))
        self.cmb_broadcast_mode.addItem("Phòng 45-50 máy (960×540, 5 FPS)", ("fixed", 960, 540, 5.0, 48))
        self.cmb_broadcast_mode.addItem("Cân bằng (1280×720, 10 FPS)", ("fixed", 1280, 720, 10.0, 65))
        self.cmb_broadcast_mode.addItem("Tiết kiệm Wi-Fi (800×450, 4 FPS)", ("fixed", 800, 450, 4.0, 45))
        self.cmb_broadcast_mode.addItem("Mượt LAN 1Gb (1280×720, 15 FPS)", ("fixed", 1280, 720, 15.0, 75))
        self.cmb_broadcast_mode.setToolTip("Tự động điều chỉnh độ nét & FPS theo sức tải thực tế của mạng và máy")
        tb1.addWidget(self.cmb_broadcast_mode)

        self.btn_showcase = QPushButton("🌟 Chiếu bài HS")
        self.btn_showcase.setCheckable(True)
        self.btn_showcase.setToolTip("Chiếu màn hình 1 học sinh đang chọn cho cả lớp cùng xem")
        self.btn_showcase.toggled.connect(self._on_toggle_showcase)
        tb1.addWidget(self.btn_showcase)

        self.btn_audio = QPushButton("🎙 Nói qua loa")
        self.btn_audio.setCheckable(True)
        self.btn_audio.setToolTip("Truyền giọng nói từ micro giáo viên xuống loa/tai nghe học sinh")
        self.btn_audio.toggled.connect(self._on_toggle_audio)
        tb1.addWidget(self.btn_audio)

        self.btn_annotate = QPushButton("✏ Bảng vẽ")
        self.btn_annotate.setCheckable(True)
        self.btn_annotate.setToolTip("Vẽ chú thích trực tiếp lên màn hình khi giảng bài")
        self.btn_annotate.toggled.connect(self._on_toggle_annotation)
        tb1.addWidget(self.btn_annotate)

        self.btn_record = QPushButton("⏺ Quay bài giảng")
        self.btn_record.setCheckable(True)
        self.btn_record.setToolTip("Quay video màn hình bài giảng lưu vào Desktop\\BaiGiangDaQuay")
        self.btn_record.toggled.connect(self._on_toggle_recording)
        tb1.addWidget(self.btn_record)

        tb1.addWidget(self._vsep())

        btn_lock = QPushButton("🔒 Khóa máy")
        btn_lock.clicked.connect(lambda: self._apply_lock(True))
        tb1.addWidget(btn_lock)

        btn_unlock = QPushButton("🔓 Mở khóa")
        btn_unlock.clicked.connect(lambda: self._apply_lock(False))
        tb1.addWidget(btn_unlock)

        btn_blank = QPushButton("⬛ Tắt màn hình")
        btn_blank.clicked.connect(lambda: self._apply_blank(True))
        tb1.addWidget(btn_blank)

        btn_unblank = QPushButton("💡 Bật màn hình")
        btn_unblank.clicked.connect(lambda: self._apply_blank(False))
        tb1.addWidget(btn_unblank)

        tb1.addWidget(self._vsep())

        btn_send_file = QPushButton("📤 Phát bài tập")
        btn_send_file.clicked.connect(self._on_distribute_file)
        tb1.addWidget(btn_send_file)

        btn_collect = QPushButton("📥 Thu bài")
        btn_collect.clicked.connect(self._on_collect_file)
        tb1.addWidget(btn_collect)

        btn_open_folder = QPushButton("📂 Thư mục bài thu")
        btn_open_folder.clicked.connect(self._on_open_collect_folder)
        tb1.addWidget(btn_open_folder)
        tb1.addStretch(1)
        tb_root.addLayout(tb1)

        tb2 = QHBoxLayout()
        tb2.setSpacing(6)

        btn_policy = QPushButton("🛡 Chặn App & Web")
        btn_policy.setToolTip("Chặn game, ứng dụng và giới hạn trang web trên máy học sinh")
        btn_policy.clicked.connect(self._on_open_policy)
        tb2.addWidget(btn_policy)

        btn_quiz = QPushButton("📝 Trắc nghiệm nhanh")
        btn_quiz.setToolTip("Gửi câu hỏi trắc nghiệm nhanh tới cả lớp")
        btn_quiz.clicked.connect(self._on_open_quiz)
        tb2.addWidget(btn_quiz)

        btn_exam = QPushButton("📑 Đề kiểm tra")
        btn_exam.setToolTip("Tạo đề nhiều câu tự chấm điểm & xuất bảng điểm Excel")
        btn_exam.clicked.connect(self._on_open_exam)
        tb2.addWidget(btn_exam)

        btn_announce = QPushButton("📢 Gửi thông báo")
        btn_announce.clicked.connect(self._on_send_announcement)
        tb2.addWidget(btn_announce)

        btn_web = QPushButton("🌐 Mở trang web")
        btn_web.clicked.connect(self._on_open_url)
        tb2.addWidget(btn_web)

        tb2.addWidget(self._vsep())

        btn_export = QPushButton("📋 Xuất điểm danh")
        btn_export.setToolTip("Xuất danh sách học sinh điểm danh ra tệp CSV mở bằng Excel")
        btn_export.clicked.connect(self._on_export_attendance)
        tb2.addWidget(btn_export)

        self.btn_power = QToolButton()
        self.btn_power.setText("🔧 Thiết bị & Nguồn")
        self.btn_power.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        power_menu = QMenu(self)
        act_wake = QAction("⚡ Bật máy từ xa (Wake-on-LAN)...", self)
        act_wake.triggered.connect(self._on_wake_on_lan)
        act_mute = QAction("🔇 Tắt tiếng loa máy học sinh", self)
        act_mute.triggered.connect(lambda: self._on_device_control("mute_audio", True, "tắt tiếng loa"))
        act_unmute = QAction("🔊 Mở tiếng loa máy học sinh", self)
        act_unmute.triggered.connect(lambda: self._on_device_control("mute_audio", False, "mở tiếng loa"))
        act_lock_usb = QAction("🔒 Khóa cổng USB lưu trữ (cần Admin trên máy HS)", self)
        act_lock_usb.triggered.connect(lambda: self._on_device_control("block_usb", True, "khóa cổng USB"))
        act_unlock_usb = QAction("🔓 Mở cổng USB lưu trữ", self)
        act_unlock_usb.triggered.connect(lambda: self._on_device_control("block_usb", False, "mở cổng USB"))
        act_restart = QAction("🔄 Khởi động lại máy từ xa", self)
        act_restart.triggered.connect(lambda: self._on_power("restart", "khởi động lại"))
        act_shutdown = QAction("⏻ Tắt máy từ xa", self)
        act_shutdown.triggered.connect(lambda: self._on_power("shutdown", "tắt máy"))
        act_logoff = QAction("🚪 Đăng xuất tài khoản", self)
        act_logoff.triggered.connect(lambda: self._on_power("logoff", "đăng xuất"))
        act_online_update = QAction("🌐 Kiểm tra cập nhật Online (tự nâng cấp)...", self)
        act_online_update.triggered.connect(self._on_open_update_dialog)
        act_lan_update = QAction("🔄 Cập nhật phần mềm máy HS qua LAN...", self)
        act_lan_update.triggered.connect(self._on_lan_update)
        power_menu.addAction(act_wake)
        power_menu.addSeparator()
        power_menu.addAction(act_mute)
        power_menu.addAction(act_unmute)
        power_menu.addAction(act_lock_usb)
        power_menu.addAction(act_unlock_usb)
        power_menu.addSeparator()
        power_menu.addAction(act_online_update)
        power_menu.addAction(act_lan_update)
        power_menu.addSeparator()
        power_menu.addAction(act_restart)
        power_menu.addAction(act_shutdown)
        power_menu.addAction(act_logoff)
        self.btn_power.setMenu(power_menu)
        tb2.addWidget(self.btn_power)

        self.chk_show_offline = QCheckBox("Hiện máy đang tắt")
        self.chk_show_offline.setChecked(True)
        self.chk_show_offline.setStyleSheet("font-weight: 600; color: #334155;")
        self.chk_show_offline.toggled.connect(lambda *_: self._sync_offline_cards())
        tb2.addWidget(self.chk_show_offline)

        tb2.addStretch(1)

        btn_select_all = QPushButton("☑ Chọn tất cả")
        btn_select_all.clicked.connect(lambda: self._set_all_selected(True))
        tb2.addWidget(btn_select_all)

        btn_clear_sel = QPushButton("☐ Bỏ chọn")
        btn_clear_sel.clicked.connect(lambda: self._set_all_selected(False))
        tb2.addWidget(btn_clear_sel)
        tb_root.addLayout(tb2)

        main_layout.addWidget(toolbar_frame)

        # Vùng chia đôi: Lưới máy học sinh (trái) + Giơ tay & Trò chuyện (phải)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Vùng lưới màn hình học sinh
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            "QScrollArea { background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; }"
        )
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.grid_layout.setContentsMargins(12, 12, 12, 12)
        self.grid_layout.setSpacing(12)

        self.lbl_empty = QLabel(
            "Chưa có máy học sinh nào kết nối.\n\n"
            "Hãy mở ứng dụng Máy Học Sinh trên các máy trạm trong cùng mạng LAN\n"
            f"hoặc nhập địa chỉ IP máy Giáo viên: {get_local_ip()}"
        )
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet("color: #64748b; font-size: 14px; padding: 40px;")
        self.grid_layout.addWidget(self.lbl_empty, 0, 0)

        self.scroll_area.setWidget(self.grid_container)
        splitter.addWidget(self.scroll_area)

        # Bảng phải: Giơ tay + Nhắn tin + Nhật ký
        right_panel = QFrame()
        right_panel.setMinimumWidth(310)
        right_panel.setMaximumWidth(420)
        right_panel.setStyleSheet(
            "QFrame { background-color: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px; }"
        )
        rp = QVBoxLayout(right_panel)
        rp.setContentsMargins(10, 10, 10, 10)
        rp.setSpacing(8)

        lbl_hands = QLabel("✋ Học sinh giơ tay xin hỗ trợ")
        lbl_hands.setStyleSheet("font-weight: 700; font-size: 13px; border: none;")
        rp.addWidget(lbl_hands)

        self.list_hands = QListWidget()
        self.list_hands.setMaximumHeight(130)
        self.list_hands.itemDoubleClicked.connect(self._on_ack_hand_item)
        rp.addWidget(self.list_hands)

        btn_ack_hand = QPushButton("✔ Đã hỗ trợ (Hạ tay)")
        btn_ack_hand.clicked.connect(self._on_ack_hand_btn)
        rp.addWidget(btn_ack_hand)

        lbl_chat = QLabel("💬 Trò chuyện & Nhật ký lớp học")
        lbl_chat.setStyleSheet("font-weight: 700; font-size: 13px; border: none;")
        rp.addWidget(lbl_chat)

        self.txt_chat_log = QTextEdit()
        self.txt_chat_log.setReadOnly(True)
        self.txt_chat_log.setStyleSheet("background: #f8fafc; font-size: 12px;")
        rp.addWidget(self.txt_chat_log, 1)

        chat_input_row = QHBoxLayout()
        self.edt_chat = QLineEdit()
        self.edt_chat.setPlaceholderText("Nhập tin nhắn gửi học sinh...")
        self.edt_chat.returnPressed.connect(self._on_send_chat)
        chat_input_row.addWidget(self.edt_chat, 1)

        btn_send_chat = QPushButton("Gửi")
        btn_send_chat.clicked.connect(self._on_send_chat)
        chat_input_row.addWidget(btn_send_chat)
        rp.addLayout(chat_input_row)

        splitter.addWidget(right_panel)
        splitter.setSizes([960, 340])
        main_layout.addWidget(splitter, 1)

        self.statusBar().showMessage("Sẵn sàng.")
        lbl_author = QLabel(f"Tác giả: {APP_AUTHOR}  ")
        lbl_author.setStyleSheet("color: #475569; font-weight: 700; font-size: 12px;")
        self.statusBar().addPermanentWidget(lbl_author)

    def _vsep(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setStyleSheet("color: #cbd5e1;")
        return line

    def _refresh_room_banner(self) -> None:
        lic = self.server.license_info
        lic_txt = (
            f"   |   © {lic.owner} (Tối đa {lic.max_students} máy)"
            if lic
            else ""
        )
        self.lbl_room.setText(
            f"🏫 Phòng: {self.server.room_code}   |   "
            f"👨‍🏫 Giáo viên: {self.server.teacher_name}   |   "
            f"🌐 IP: {get_local_ip()}:{self.server.ws_port}"
            f"{lic_txt}"
        )

    def _connect_signals(self) -> None:
        s = self.server.signals
        s.student_connected.connect(self._on_student_connected)
        s.student_disconnected.connect(self._on_student_disconnected)
        s.student_updated.connect(self._on_student_updated)
        s.student_frame.connect(self._on_student_frame)
        s.chat_received.connect(self._on_chat_received)
        s.file_collected.connect(self._on_file_collected)
        s.quiz_answer_received.connect(self._on_quiz_answer_received)
        s.exam_submission_received.connect(self._on_exam_submission_received)
        s.device_notice.connect(self._on_device_notice)
        s.server_status.connect(self._on_server_status)
        s.server_error.connect(self._on_server_error)

    def _selected_ids(self) -> list[str]:
        return [sid for sid, card in self._cards.items() if card.is_selected()]

    def _target_ids_or_all(self) -> list[str] | None:
        sel = self._selected_ids()
        return sel if sel else None

    def _update_target_label(self) -> None:
        total = len(self._cards)
        sel = len(self._selected_ids())
        if sel > 0:
            self.lbl_target.setText(f"Đối tượng thao tác: Đã chọn {sel}/{total} máy")
        else:
            self.lbl_target.setText(f"Đối tượng thao tác: Toàn bộ lớp ({total} máy)")

    def _sync_offline_cards(self) -> None:
        online_macs = {
            str(c.info.get("mac_address") or "").upper()
            for c in self._cards.values()
            if c.info.get("mac_address")
        }
        want_offline: dict[str, dict[str, str]] = {}
        if self.chk_show_offline.isChecked():
            for pc in self.server.get_known_pcs():
                mac = str(pc.get("mac_address") or "").upper()
                if mac and mac not in online_macs:
                    want_offline[mac] = pc

        for mac in list(self._offline_cards.keys()):
            if mac not in want_offline:
                card = self._offline_cards.pop(mac)
                card.deleteLater()

        for mac, pc in want_offline.items():
            if mac in self._offline_cards:
                self._offline_cards[mac].update_info(pc)
            else:
                card = StudentCard(pc, self.grid_container, is_offline=True)
                card.wake_requested.connect(self._on_wake_single_mac)
                card.seat_edit_requested.connect(self._on_edit_offline_seat)
                card.remove_offline_requested.connect(self._on_remove_offline_mac)
                self._offline_cards[mac] = card

        self._relayout_grid()

    def _relayout_grid(self) -> None:
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w is not None and w is not self.lbl_empty:
                w.setParent(self.grid_container)

        all_cards = list(self._cards.values()) + list(self._offline_cards.values())
        if not all_cards:
            self.lbl_empty.show()
            self.grid_layout.addWidget(self.lbl_empty, 0, 0)
            self._update_target_label()
            return

        self.lbl_empty.hide()
        avail_w = max(300, self.scroll_area.viewport().width() - 24)
        cols = max(1, avail_w // 292)
        ordered = sorted(
            all_cards,
            key=lambda c: (
                1 if c.is_offline else 0,
                0 if c.info.get("seat_label") else 1,
                str(c.info.get("seat_label") or ""),
                str(c.info.get("pc_name") or ""),
            ),
        )
        for idx, card in enumerate(ordered):
            r, c = divmod(idx, cols)
            self.grid_layout.addWidget(card, r, c)
        self._update_target_label()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._cards or self._offline_cards:
            self._relayout_grid()

    def _append_log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.txt_chat_log.append(f"[{stamp}] {text}")

    # --- Slots xử lý tín hiệu từ Server ---

    def _on_student_connected(self, info: dict[str, Any]) -> None:
        sid = str(info["student_id"])
        if sid in self._cards:
            self._cards[sid].update_info(info)
        else:
            card = StudentCard(info, self.grid_container)
            card.selection_changed.connect(lambda *_: self._update_target_label())
            card.double_clicked.connect(self._open_remote_dialog)
            card.seat_edit_requested.connect(self._on_edit_seat)
            card.showcase_requested.connect(self._on_showcase_student)
            card.history_requested.connect(self._on_view_student_history)
            self._cards[sid] = card
            self._sync_offline_cards()

        name = info.get("student_name") or info.get("pc_name")
        self._append_log(f"🟢 {name} ({info.get('ip_address')}) đã vào lớp.")
        self._refresh_hands_list()

    def _on_student_disconnected(self, student_id: str) -> None:
        card = self._cards.pop(student_id, None)
        if card:
            name = card.info.get("student_name") or card.info.get("pc_name")
            card.deleteLater()
            self._sync_offline_cards()
            self._append_log(f"⚪ {name} đã ngắt kết nối.")
        if self._remote_dialog and self._remote_dialog.student_id == student_id:
            self._remote_dialog.close()
        self._refresh_hands_list()

    def _on_student_updated(self, info: dict[str, Any]) -> None:
        sid = str(info["student_id"])
        card = self._cards.get(sid)
        if card:
            card.update_info(info)
            self._relayout_grid()
        self._refresh_hands_list()

    def _on_student_frame(self, student_id: str, jpeg_bytes: bytes) -> None:
        card = self._cards.get(student_id)
        if card:
            card.update_frame(jpeg_bytes)
        if self._remote_dialog and self._remote_dialog.student_id == student_id:
            self._remote_dialog.update_frame(jpeg_bytes)

    def _on_chat_received(self, student_id: str, sender: str, text: str) -> None:
        self._append_log(f"💬 <b>{sender}</b>: {text}")

    def _on_file_collected(self, student_id: str, filename: str, saved_path: str) -> None:
        card = self._cards.get(student_id)
        who = (
            (card.info.get("student_name") or card.info.get("pc_name"))
            if card
            else student_id
        )
        self._append_log(f"📥 Đã thu bài '{filename}' từ <b>{who}</b> → {saved_path}")
        self.statusBar().showMessage(f"Đã thu tệp '{filename}' từ {who}", 6000)

    def _on_server_status(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 6000)
        self._append_log(f"ℹ {msg}")

    def _on_server_error(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 8000)
        QMessageBox.warning(self, "Cảnh báo máy chủ", msg)

    def _refresh_hands_list(self) -> None:
        self.list_hands.clear()
        for sid, card in self._cards.items():
            if card.info.get("hand_raised"):
                name = card.info.get("student_name") or card.info.get("pc_name")
                item = QListWidgetItem(f"✋ {name} ({card.info.get('pc_name')})")
                item.setData(Qt.ItemDataRole.UserRole, sid)
                self.list_hands.addItem(item)

    # --- Các hành động của Giáo viên ---

    def _on_toggle_autostart(self, checked: bool) -> None:
        cmd = build_launch_command("run_teacher.py", "--teacher") if checked else None
        ok, msg = set_autostart(TEACHER_AUTOSTART_KEY, checked, cmd)
        if not ok:
            self.chk_autostart.blockSignals(True)
            self.chk_autostart.setChecked(not checked)
            self.chk_autostart.blockSignals(False)
            QMessageBox.warning(self, "Khởi động cùng Windows", msg)
            return
        self.statusBar().showMessage(msg, 5000)
        self._append_log(f"⚙ {msg}")

    def _on_open_license(self) -> None:
        dlg = LicenseDialog(self, state_dir=self.server._state_dir)
        if dlg.exec() == LicenseDialog.DialogCode.Accepted:
            self.server.refresh_license()
            self._refresh_room_banner()

    def _on_edit_room(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Đổi tên Giáo viên & Mã phòng học")
        dlg.resize(400, 150)
        form = QFormLayout(dlg)

        edt_teacher = QLineEdit(self.server.teacher_name)
        edt_teacher.setPlaceholderText("VD: Thầy Quang, Cô Lan...")
        edt_room = QLineEdit(self.server.room_code)
        edt_room.setPlaceholderText("VD: PHONG-TIN-01")

        form.addRow("Tên giáo viên:", edt_teacher)
        form.addRow("Mã phòng / Tên lớp:", edt_room)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Lưu thay đổi")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.server.set_room_info(
                edt_room.text() or DEFAULT_ROOM_CODE,
                edt_teacher.text() or DEFAULT_TEACHER_NAME,
            )
            self._refresh_room_banner()
            self._append_log(
                f"👨‍🏫 Đã cập nhật Giáo viên: <b>{self.server.teacher_name}</b> | Phòng: <b>{self.server.room_code}</b>"
            )

    def _set_all_selected(self, selected: bool) -> None:
        for card in self._cards.values():
            card.set_selected(selected)
        self._update_target_label()

    def _on_open_remote_selected(self) -> None:
        sel = self._selected_ids()
        if not sel:
            if len(self._cards) == 1:
                sel = list(self._cards.keys())
            else:
                QMessageBox.information(
                    self,
                    "Chưa chọn máy học sinh",
                    "Vui lòng tích chọn 1 máy học sinh (hoặc nhấp đúp vào màn hình máy đó) để xem & điều khiển.",
                )
                return
        self._open_remote_dialog(sel[0])

    def _open_remote_dialog(self, student_id: str) -> None:
        card = self._cards.get(student_id)
        if not card:
            return
        if self._remote_dialog:
            self._remote_dialog.close()

        title = card.info.get("student_name") or card.info.get("pc_name") or student_id
        dlg = RemoteViewDialog(student_id, title, self)
        dlg.input_sent.connect(self.server.send_remote_input)
        dlg.dialog_closed.connect(lambda _sid: self.server.set_remote_view(None))
        self._remote_dialog = dlg
        self.server.set_remote_view(student_id)
        dlg.show()

    def _on_toggle_broadcast(self, checked: bool) -> None:
        if checked:
            if not self._cards:
                self.btn_broadcast.setChecked(False)
                QMessageBox.information(
                    self, "Chưa có học sinh", "Hiện chưa có máy học sinh nào kết nối."
                )
                return
            self._is_broadcasting = True
            self.btn_broadcast.setText("⏹ Dừng trình chiếu")
            mode, w, h, fps, quality = self.cmb_broadcast_mode.currentData() or (
                "auto",
                0,
                0,
                0.0,
                0,
            )
            if mode == "auto":
                self.server.start_broadcast(self._target_ids_or_all(), auto_adapt=True)
            else:
                self.server.start_broadcast(
                    self._target_ids_or_all(),
                    fps=fps,
                    quality=quality,
                    width=w,
                    height=h,
                    auto_adapt=False,
                )
        else:
            self._is_broadcasting = False
            self.btn_broadcast.setText("📡 Trình chiếu màn hình")
            self.server.stop_broadcast()

    def _apply_lock(self, locked: bool) -> None:
        if not self._cards:
            return
        msg = "Màn hình đã bị khóa. Vui lòng chú ý nghe giảng!"
        if locked:
            text, ok = QInputDialog.getText(
                self,
                "Khóa máy học sinh",
                "Thông điệp hiển thị trên màn hình học sinh:",
                text=msg,
            )
            if not ok:
                return
            msg = text.strip() or msg
        self.server.lock_students(self._target_ids_or_all(), locked, msg)

    def _apply_blank(self, blanked: bool) -> None:
        if not self._cards:
            return
        self.server.blank_students(
            self._target_ids_or_all(),
            blanked,
            "Giáo viên tạm tắt màn hình. Vui lòng nhìn lên bảng!",
        )

    def _on_distribute_file(self) -> None:
        if not self._cards:
            QMessageBox.information(
                self, "Chưa có học sinh", "Hiện chưa có máy học sinh nào kết nối."
            )
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn tệp bài tập để phát xuống máy học sinh"
        )
        if file_path:
            self.server.distribute_file(self._target_ids_or_all(), file_path)

    def _on_collect_file(self) -> None:
        if not self._cards:
            QMessageBox.information(
                self, "Chưa có học sinh", "Hiện chưa có máy học sinh nào kết nối."
            )
            return
        note, ok = QInputDialog.getText(
            self,
            "Yêu cầu học sinh nộp bài",
            "Lời nhắc gửi xuống máy học sinh:",
            text="Em hãy chọn tệp bài làm để nộp cho giáo viên!",
        )
        if ok:
            self.server.request_collect_file(self._target_ids_or_all(), note)
            self._append_log("📥 Đã gửi yêu cầu nộp bài tới học sinh.")

    def _on_open_collect_folder(self) -> None:
        folder = get_teacher_collect_dir()
        os.startfile(str(folder))

    def _on_send_announcement(self) -> None:
        if not self._cards:
            return
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Gửi thông báo tới lớp",
            "Nội dung thông báo hiển thị nổi bật trên màn hình học sinh:",
        )
        if ok and text.strip():
            self.server.send_announcement(
                self._target_ids_or_all(), "Thông báo từ Giáo viên", text.strip()
            )
            self._append_log(f"📢 Đã gửi thông báo: {text.strip()}")

    def _on_open_url(self) -> None:
        if not self._cards:
            return
        url, ok = QInputDialog.getText(
            self,
            "Mở trang web trên máy học sinh",
            "Nhập địa chỉ trang web (VD: https://olm.vn):",
            text="https://",
        )
        if ok and url.strip():
            target_url = url.strip()
            if not target_url.startswith(("http://", "https://")):
                target_url = "https://" + target_url
            self.server.open_url(self._target_ids_or_all(), target_url)
            self._append_log(f"🌐 Đã mở trang web {target_url} trên máy học sinh.")

    def _on_edit_seat(self, student_id: str) -> None:
        card = self._cards.get(student_id)
        if not card:
            return
        cur = str(card.info.get("seat_label") or "")
        label, ok = QInputDialog.getText(
            self,
            "Đặt số máy / vị trí chỗ ngồi",
            "Nhập số thứ tự hoặc tên vị trí (VD: Máy 01, Dãy A - 02):",
            text=cur,
        )
        if ok:
            self.server.set_seat_label(student_id, label)

    def _on_change_password(self) -> None:
        pwd, ok = QInputDialog.getText(
            self,
            "Đổi mật khẩu lớp học",
            "Mật khẩu dùng để bảo vệ ứng dụng Học sinh không bị tự ý thoát (mặc định ban đầu: 123456):",
            QLineEdit.EchoMode.Password,
        )
        if ok and pwd.strip():
            self.server.set_teacher_password(pwd.strip())
            self._append_log("🔑 Đã cập nhật mật khẩu lớp học mới và đồng bộ xuống máy học sinh.")

    def _on_open_policy(self) -> None:
        dlg = PolicyDialog(self.server.policy, self)
        if dlg.exec() == PolicyDialog.DialogCode.Accepted:
            pol = dlg.result_policy
            self.server.set_policy(
                self._target_ids_or_all(),
                pol["blocked_apps"],
                pol["web_mode"],
                pol["web_domains"],
            )
            self._append_log("🛡 Đã áp dụng chính sách chặn ứng dụng & trang web xuống máy học sinh.")

    def _on_open_quiz(self) -> None:
        if not self._cards:
            QMessageBox.information(
                self, "Chưa có học sinh", "Hiện chưa có máy học sinh nào kết nối."
            )
            return
        if self._quiz_dialog is None:
            self._quiz_dialog = QuizTeacherDialog(self)
            self._quiz_dialog.quiz_sent.connect(
                lambda qid, q, opts: self.server.send_quiz(
                    self._target_ids_or_all(), qid, q, opts
                )
            )
        self._quiz_dialog.show()
        self._quiz_dialog.raise_()

    def _on_quiz_answer_received(
        self, student_id: str, quiz_id: str, choice_index: int, student_label: str
    ) -> None:
        if self._quiz_dialog:
            self._quiz_dialog.record_answer(
                student_id, quiz_id, choice_index, student_label
            )

    def _on_open_exam(self) -> None:
        if not self._cards:
            QMessageBox.information(
                self, "Chưa có học sinh", "Hiện chưa có máy học sinh nào kết nối."
            )
            return
        if self._exam_dialog is None:
            self._exam_dialog = ExamTeacherDialog(self)
            self._exam_dialog.exam_sent.connect(
                lambda eid, title, mins, qs: self.server.send_exam(
                    self._target_ids_or_all(), eid, title, mins, qs
                )
            )
        self._exam_dialog.show()
        self._exam_dialog.raise_()

    def _on_exam_submission_received(
        self,
        student_id: str,
        exam_id: str,
        student_label: str,
        correct: int,
        total: int,
        score: float,
    ) -> None:
        self._append_log(
            f"📝 <b>{student_label}</b> đã nộp bài kiểm tra: {correct}/{total} ({score:.2f} điểm)"
        )
        if self._exam_dialog:
            self._exam_dialog.record_submission(
                student_id, exam_id, student_label, correct, total, score
            )

    def _on_toggle_showcase(self, checked: bool) -> None:
        if checked:
            sel = self._selected_ids()
            if not sel:
                self.btn_showcase.setChecked(False)
                QMessageBox.information(
                    self,
                    "Chưa chọn học sinh",
                    "Vui lòng tích chọn 1 máy học sinh (hoặc chuột phải lên thẻ máy đó) để chiếu cho cả lớp xem.",
                )
                return
            self._on_showcase_student(sel[0])
        else:
            self._is_showcasing = False
            self.btn_showcase.setText("🌟 Chiếu bài HS")
            self.server.stop_showcase()

    def _on_showcase_student(self, student_id: str) -> None:
        if len(self._cards) < 2:
            self.btn_showcase.blockSignals(True)
            self.btn_showcase.setChecked(False)
            self.btn_showcase.blockSignals(False)
            QMessageBox.information(
                self, "Cần ít nhất 2 máy", "Cần ít nhất 2 máy học sinh để chiếu bài từ 1 máy cho các bạn khác xem."
            )
            return
        self._is_showcasing = True
        self.btn_showcase.blockSignals(True)
        self.btn_showcase.setChecked(True)
        self.btn_showcase.setText("⏹ Dừng chiếu bài HS")
        self.btn_showcase.blockSignals(False)
        self.server.start_showcase(student_id)

    def _on_toggle_audio(self, checked: bool) -> None:
        if checked:
            if not self._cards:
                self.btn_audio.setChecked(False)
                QMessageBox.information(
                    self, "Chưa có học sinh", "Hiện chưa có máy học sinh nào kết nối."
                )
                return
            ok, msg = self.server.start_audio_broadcast(self._target_ids_or_all())
            if not ok:
                self.btn_audio.blockSignals(True)
                self.btn_audio.setChecked(False)
                self.btn_audio.blockSignals(False)
                QMessageBox.warning(self, "Lỗi Micro", msg)
                return
            self._is_audio_broadcasting = True
            self.btn_audio.setText("🔇 Tắt loa lớp")
        else:
            self._is_audio_broadcasting = False
            self.btn_audio.setText("🎙 Nói qua loa")
            self.server.stop_audio_broadcast()

    def _on_toggle_annotation(self, checked: bool) -> None:
        if checked:
            self._annotation.start()
        else:
            self._annotation.stop()

    def _on_annotation_closed(self) -> None:
        self.btn_annotate.blockSignals(True)
        self.btn_annotate.setChecked(False)
        self.btn_annotate.blockSignals(False)

    def _on_toggle_recording(self, checked: bool) -> None:
        if checked:
            out_path = self._recorder.start()
            self.btn_record.setText("⏹ Dừng quay")
            self._append_log(f"⏺ Bắt đầu quay video bài giảng: {out_path}")
        else:
            saved = self._recorder.stop()
            self.btn_record.setText("⏺ Quay bài giảng")
            if saved:
                self._append_log(f"💾 Đã lưu video bài giảng tại: {saved}")
                QMessageBox.information(
                    self,
                    "Đã lưu video bài giảng",
                    f"Video bài giảng đã được lưu tại:\n{saved}",
                )

    def _on_device_control(self, action: str, value: bool, label_vn: str) -> None:
        if not self._cards:
            return
        self.server.send_device_control(self._target_ids_or_all(), action, value)
        self._append_log(f"🔧 Đã gửi lệnh {label_vn} xuống máy học sinh.")

    def _on_device_notice(self, student_id: str, msg: str) -> None:
        card = self._cards.get(student_id)
        who = (card.info.get("student_name") or card.info.get("pc_name")) if card else student_id
        self._append_log(f"🔧 <b>{who}</b>: {msg}")

    def _on_wake_single_mac(self, mac: str) -> None:
        if not mac:
            return
        ok_count, msgs = self.server.wake_pcs([mac])
        self._append_log(f"⚡ Đã gửi tín hiệu bật máy tới MAC {mac}.")
        self.statusBar().showMessage(msgs[0] if msgs else "Đã gửi lệnh bật máy.", 5000)

    def _on_edit_offline_seat(self, mac: str) -> None:
        card = self._offline_cards.get(mac)
        if not card:
            return
        cur = str(card.info.get("seat_label") or "")
        label, ok = QInputDialog.getText(
            self,
            "Đặt số máy / vị trí chỗ ngồi",
            "Nhập số thứ tự hoặc tên vị trí:",
            text=cur,
        )
        if ok:
            self.server.set_known_pc_seat(mac, label)
            self._sync_offline_cards()

    def _on_remove_offline_mac(self, mac: str) -> None:
        self.server.remove_known_pc(mac)
        self._sync_offline_cards()

    def _schedule_silent_update_check(self) -> None:
        url = self.server.update_url
        if not url:
            return

        def _worker() -> None:
            try:
                data = fetch_update_manifest(url, timeout=5.0)
                remote_ver = str(data.get("version") or "").strip()
                dl_url = str(data.get("download_url") or "").strip()
                if (
                    remote_ver
                    and is_newer_version(remote_ver, APP_VERSION)
                    and dl_url.startswith(("http://", "https://"))
                ):
                    self._online_update_found.emit(data)
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _on_silent_update_found(self, data: dict[str, Any]) -> None:
        self._available_manifest = data
        ver = str(data.get("version") or "").strip()
        self.btn_update.setText(f"🆕 Có bản v{ver}!")
        self.btn_update.setStyleSheet(
            "background-color: #16a34a; color: #ffffff; border: 1px solid #15803d;"
        )
        self._append_log(
            f"🎉 Có bản cập nhật mới v{ver} — bấm nút '🆕 Có bản v{ver}!' ở góc trên phải để nâng cấp."
        )

    def _on_open_update_dialog(self) -> None:
        dlg = OnlineUpdateDialog(
            self.server,
            self,
            initial_manifest=self._available_manifest,
            on_pick_lan_file=self._on_lan_update,
        )
        dlg.exec()

    def _on_lan_update(self) -> None:
        if not self._cards:
            QMessageBox.information(
                self, "Chưa có học sinh", "Hiện chưa có máy học sinh nào đang kết nối để cập nhật."
            )
            return
        default_exe = (
            str(Path(sys.executable).resolve())
            if getattr(sys, "frozen", False)
            else str(Path.cwd())
        )
        exe_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn tệp NTQ Remote.exe phiên bản mới để gửi cập nhật cho học sinh",
            default_exe,
            "Ứng dụng Windows (*.exe)",
        )
        if not exe_path:
            return
        reply = QMessageBox.question(
            self,
            "Xác nhận cập nhật qua LAN",
            "Các máy học sinh được chọn sẽ nhận tệp cập nhật mới, tự khởi động lại ứng dụng và kết nối lại sau vài giây.\nBạn có muốn tiếp tục không?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.server.distribute_update(self._target_ids_or_all(), exe_path)

    def _on_view_student_history(self, student_id: str) -> None:
        card = self._cards.get(student_id)
        title = (card.info.get("student_name") or card.info.get("pc_name")) if card else student_id
        entries = self.server.get_student_history(student_id)
        text = "\n".join(entries) if entries else "Chưa có sự kiện nào được ghi nhận."
        QMessageBox.information(self, f"Nhật ký hoạt động: {title}", text)

    def _on_export_attendance(self) -> None:
        students = self.server.get_students_snapshot()
        if not students:
            QMessageBox.information(
                self, "Chưa có dữ liệu", "Hiện chưa có máy học sinh nào đang kết nối để xuất điểm danh."
            )
            return
        default_name = f"DiemDanh_{self.server.room_code}_{time.strftime('%Y%m%d_%H%M')}.csv"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu danh sách điểm danh",
            str(Path.home() / "Desktop" / default_name),
            "Tệp Excel CSV (*.csv)",
        )
        if not file_path:
            return
        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["STT", "Vị trí máy", "Họ và tên học sinh", "Tên máy", "Địa chỉ IP", "Địa chỉ MAC", "Giờ vào lớp", "Trạng thái"]
            )
            for idx, st in enumerate(students, start=1):
                status = "Đang khóa" if st.get("locked") else "Trực tuyến"
                writer.writerow(
                    [
                        idx,
                        st.get("seat_label", ""),
                        st.get("student_name") or "(Chưa nhập tên)",
                        st.get("pc_name", ""),
                        st.get("ip_address", ""),
                        st.get("mac_address", ""),
                        st.get("connected_at", ""),
                        status,
                    ]
                )
        self._append_log(f"📋 Đã xuất danh sách điểm danh ra: {file_path}")
        QMessageBox.information(
            self, "Xuất điểm danh thành công", f"Đã lưu danh sách điểm danh tại:\n{file_path}"
        )

    def _on_wake_on_lan(self) -> None:
        known = self.server.get_known_pcs()
        dlg = WakeOnLanDialog(known, self)
        if dlg.exec() == WakeOnLanDialog.DialogCode.Accepted:
            ok_count, msgs = self.server.wake_pcs(dlg.selected_macs)
            self._append_log(f"⚡ Đã gửi tín hiệu bật máy (Wake-on-LAN) tới {ok_count} máy.")
            QMessageBox.information(
                self,
                "Đã gửi lệnh bật máy",
                "\n".join(msgs[:10]),
            )

    def _on_power(self, action: str, label_vn: str) -> None:
        if not self._cards:
            return
        targets = self._target_ids_or_all()
        scope_text = (
            f"{len(targets)} máy đã chọn"
            if targets is not None
            else f"TOÀN BỘ {len(self._cards)} máy trong lớp"
        )
        reply = QMessageBox.question(
            self,
            "Xác nhận thao tác nguồn",
            f"Bạn có chắc chắn muốn {label_vn} đối với {scope_text}?\n"
            "Học sinh sẽ có 5 giây trước khi máy thực thi.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.server.send_power(targets, action)
            self._append_log(f"⏻ Đã gửi lệnh {label_vn} tới {scope_text}.")

    def _on_send_chat(self) -> None:
        text = self.edt_chat.text().strip()
        if not text:
            return
        self.server.send_chat(self._target_ids_or_all(), text)
        self._append_log(f"💬 <b>Bạn (Giáo viên)</b>: {text}")
        self.edt_chat.clear()

    def _on_ack_hand_item(self, item: QListWidgetItem) -> None:
        sid = item.data(Qt.ItemDataRole.UserRole)
        if sid:
            self.server.clear_hand(str(sid))

    def _on_ack_hand_btn(self) -> None:
        item = self.list_hands.currentItem()
        if item is None and self.list_hands.count() > 0:
            item = self.list_hands.item(0)
        if item:
            sid = item.data(Qt.ItemDataRole.UserRole)
            if sid:
                self.server.clear_hand(str(sid))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._recorder.is_recording():
            self._recorder.stop()
        self._annotation.stop()
        if self._is_audio_broadcasting:
            self.server.stop_audio_broadcast()
        if self._is_showcasing:
            self.server.stop_showcase()
        if self._is_broadcasting:
            self.server.stop_broadcast()
        self.server.stop()
        super().closeEvent(event)
