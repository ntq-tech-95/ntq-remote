"""Các hộp thoại chức năng nâng cao cho Máy Giáo Viên (WOL, Chặn App/Web, Trắc nghiệm)."""

import uuid
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class WakeOnLanDialog(QDialog):
    """Hộp thoại chọn và bật nguồn các máy học sinh từ xa qua mạng LAN (Wake-on-LAN)."""

    def __init__(
        self, known_pcs: list[dict[str, str]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("⚡ Bật máy học sinh từ xa (Wake-on-LAN)")
        self.resize(560, 440)
        self.selected_macs: list[str] = []

        root = QVBoxLayout(self)
        root.setSpacing(8)

        note = QLabel(
            "Chọn các máy đã lưu trong lớp để gửi tín hiệu bật máy qua mạng LAN.\n"
            "Lưu ý: Máy trạm cần cắm dây mạng LAN và bật sẵn Wake-on-LAN trong BIOS/Card mạng."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #334155; font-size: 12px;")
        root.addWidget(note)

        self.list_pcs = QListWidget()
        for pc in known_pcs:
            mac = pc.get("mac_address", "")
            if not mac:
                continue
            seat = f"[{pc['seat_label']}] " if pc.get("seat_label") else ""
            label = f"{seat}{pc.get('pc_name', 'Máy')}  |  MAC: {mac}  |  IP cũ: {pc.get('last_ip', '')}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, mac)
            self.list_pcs.addItem(item)
        root.addWidget(self.list_pcs, 1)

        sel_row = QHBoxLayout()
        btn_all = QPushButton("Chọn tất cả")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton("Bỏ chọn")
        btn_none.clicked.connect(lambda: self._set_all(False))
        sel_row.addWidget(btn_all)
        sel_row.addWidget(btn_none)
        sel_row.addStretch(1)
        root.addLayout(sel_row)

        manual_row = QHBoxLayout()
        manual_row.addWidget(QLabel("Hoặc nhập thêm MAC:"))
        self.edt_manual_mac = QLineEdit()
        self.edt_manual_mac.setPlaceholderText("VD: AA:BB:CC:DD:EE:FF")
        manual_row.addWidget(self.edt_manual_mac, 1)
        root.addLayout(manual_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_wake = QPushButton("⚡ Gửi lệnh bật máy")
        btn_wake.setStyleSheet(
            "background-color: #16a34a; color: #ffffff; border: none; padding: 8px 16px; font-weight: 700;"
        )
        btn_wake.clicked.connect(self._on_accept)
        btn_cancel = QPushButton("Đóng")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_wake)
        btn_row.addWidget(btn_cancel)
        root.addLayout(btn_row)

    def _set_all(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.list_pcs.count()):
            self.list_pcs.item(i).setCheckState(state)

    def _on_accept(self) -> None:
        macs: list[str] = []
        for i in range(self.list_pcs.count()):
            item = self.list_pcs.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                macs.append(str(item.data(Qt.ItemDataRole.UserRole)))
        extra = self.edt_manual_mac.text().strip()
        if extra:
            macs.append(extra)
        if not macs:
            QMessageBox.information(
                self, "Chưa chọn máy", "Vui lòng chọn ít nhất 1 máy hoặc nhập địa chỉ MAC."
            )
            return
        self.selected_macs = macs
        self.accept()


class PolicyDialog(QDialog):
    """Hộp thoại thiết lập chặn ứng dụng (game) và kiểm soát trang web."""

    def __init__(
        self, current_policy: dict[str, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("🛡 Chặn Ứng dụng & Kiểm soát Trang web")
        self.resize(560, 500)
        self.result_policy: dict[str, Any] = {}

        root = QVBoxLayout(self)
        root.setSpacing(10)

        lbl_apps = QLabel(
            "1. Danh sách ứng dụng bị chặn (mỗi tên hoặc từ khóa 1 dòng, VD: roblox, steam, valorant):"
        )
        lbl_apps.setStyleSheet("font-weight: 700;")
        root.addWidget(lbl_apps)

        self.txt_apps = QTextEdit()
        self.txt_apps.setMaximumHeight(110)
        self.txt_apps.setPlainText("\n".join(current_policy.get("blocked_apps", [])))
        root.addWidget(self.txt_apps)

        preset_row = QHBoxLayout()
        btn_preset_games = QPushButton("+ Thêm mẫu chặn Game phổ biến")
        btn_preset_games.clicked.connect(self._add_game_presets)
        btn_clear_apps = QPushButton("Xóa hết danh sách ứng dụng")
        btn_clear_apps.clicked.connect(self.txt_apps.clear)
        preset_row.addWidget(btn_preset_games)
        preset_row.addWidget(btn_clear_apps)
        preset_row.addStretch(1)
        root.addLayout(preset_row)

        lbl_web = QLabel("2. Chế độ kiểm soát trình duyệt / trang web:")
        lbl_web.setStyleSheet("font-weight: 700;")
        root.addWidget(lbl_web)

        self.web_group = QButtonGroup(self)
        self.rad_allow_all = QRadioButton("Cho phép truy cập tất cả trang web")
        self.rad_block_list = QRadioButton("Chặn các trang web chứa từ khóa / tên miền bên dưới")
        self.rad_allow_only = QRadioButton("CHỈ cho phép vào các trang web học tập bên dưới")
        for rb in (self.rad_allow_all, self.rad_block_list, self.rad_allow_only):
            self.web_group.addButton(rb)
            root.addWidget(rb)

        mode = current_policy.get("web_mode", "allow_all")
        if mode == "block_list":
            self.rad_block_list.setChecked(True)
        elif mode == "allow_only":
            self.rad_allow_only.setChecked(True)
        else:
            self.rad_allow_all.setChecked(True)

        self.txt_domains = QTextEdit()
        self.txt_domains.setMaximumHeight(110)
        self.txt_domains.setPlaceholderText(
            "Mỗi tên miền hoặc từ khóa 1 dòng (VD: facebook, youtube, tiktok, olm.vn)"
        )
        self.txt_domains.setPlainText("\n".join(current_policy.get("web_domains", [])))
        root.addWidget(self.txt_domains)

        btn_social = QPushButton("+ Thêm mẫu chặn Mạng xã hội / Giải trí")
        btn_social.clicked.connect(self._add_social_presets)
        root.addWidget(btn_social, alignment=Qt.AlignmentFlag.AlignLeft)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_apply = QPushButton("✔ Áp dụng ngay cho lớp")
        btn_apply.setStyleSheet(
            "background-color: #2563eb; color: #ffffff; border: none; padding: 8px 16px; font-weight: 700;"
        )
        btn_apply.clicked.connect(self._on_apply)
        btn_cancel = QPushButton("Hủy")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_apply)
        btn_row.addWidget(btn_cancel)
        root.addLayout(btn_row)

    def _add_game_presets(self) -> None:
        existing = [x.strip().lower() for x in self.txt_apps.toPlainText().splitlines() if x.strip()]
        for term in ("roblox", "steam", "garena", "league", "valorant", "minecraft", "epicgames"):
            if term not in existing:
                existing.append(term)
        self.txt_apps.setPlainText("\n".join(existing))

    def _add_social_presets(self) -> None:
        existing = [x.strip().lower() for x in self.txt_domains.toPlainText().splitlines() if x.strip()]
        for term in ("facebook", "youtube", "tiktok", "instagram", "netflix", "poki", "y8"):
            if term not in existing:
                existing.append(term)
        self.txt_domains.setPlainText("\n".join(existing))
        if self.rad_allow_all.isChecked():
            self.rad_block_list.setChecked(True)

    def _on_apply(self) -> None:
        apps = [x.strip() for x in self.txt_apps.toPlainText().splitlines() if x.strip()]
        domains = [x.strip() for x in self.txt_domains.toPlainText().splitlines() if x.strip()]
        if self.rad_block_list.isChecked():
            mode = "block_list"
        elif self.rad_allow_only.isChecked():
            mode = "allow_only"
        else:
            mode = "allow_all"

        self.result_policy = {
            "blocked_apps": apps,
            "web_mode": mode,
            "web_domains": domains,
        }
        self.accept()


class QuizTeacherDialog(QDialog):
    """Hộp thoại tạo câu hỏi trắc nghiệm nhanh và xem thống kê theo thời gian thực."""

    quiz_sent = Signal(str, str, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("📝 Trắc nghiệm / Khảo sát nhanh")
        self.resize(560, 540)
        self._active_quiz_id: str = ""
        self._answers: dict[str, tuple[int, str]] = {}
        self._correct_idx: int = -1

        root = QVBoxLayout(self)
        root.setSpacing(8)

        root.addWidget(QLabel("Nội dung câu hỏi:"))
        self.edt_question = QLineEdit()
        self.edt_question.setPlaceholderText("VD: Phím tắt để sao chép văn bản là gì?")
        root.addWidget(self.edt_question)

        self.option_edits: list[QLineEdit] = []
        self.correct_radios: list[QRadioButton] = []
        self.bars: list[QProgressBar] = []
        self.count_labels: list[QLabel] = []
        self.correct_group = QButtonGroup(self)

        labels = ["A", "B", "C", "D"]
        for i, lbl in enumerate(labels):
            row = QHBoxLayout()
            rb = QRadioButton(f"Đúng ({lbl})")
            self.correct_group.addButton(rb, i)
            self.correct_radios.append(rb)
            row.addWidget(rb)

            edt = QLineEdit()
            edt.setPlaceholderText(f"Đáp án {lbl}...")
            self.option_edits.append(edt)
            row.addWidget(edt, 1)
            root.addLayout(row)

        btn_send = QPushButton("🚀 Gửi câu hỏi xuống lớp ngay")
        btn_send.setStyleSheet(
            "background-color: #2563eb; color: #ffffff; border: none; padding: 8px 16px; font-weight: 700;"
        )
        btn_send.clicked.connect(self._on_send)
        root.addWidget(btn_send)

        lbl_stats = QLabel("Kết quả thống kê trực tiếp:")
        lbl_stats.setStyleSheet("font-weight: 700; margin-top: 6px;")
        root.addWidget(lbl_stats)

        for i, lbl in enumerate(labels):
            srow = QHBoxLayout()
            srow.addWidget(QLabel(f"Đáp án {lbl}:"))
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            self.bars.append(bar)
            srow.addWidget(bar, 1)
            clbl = QLabel("0 lượt")
            clbl.setMinimumWidth(65)
            self.count_labels.append(clbl)
            srow.addWidget(clbl)
            root.addLayout(srow)

        self.txt_detail = QTextEdit()
        self.txt_detail.setReadOnly(True)
        self.txt_detail.setMaximumHeight(120)
        root.addWidget(self.txt_detail)

    def _on_send(self) -> None:
        q = self.edt_question.text().strip()
        opts = [e.text().strip() for e in self.option_edits if e.text().strip()]
        if not q or len(opts) < 2:
            QMessageBox.warning(
                self, "Thiếu thông tin", "Vui lòng nhập câu hỏi và ít nhất 2 đáp án."
            )
            return
        self._active_quiz_id = uuid.uuid4().hex[:8]
        self._answers.clear()
        self._correct_idx = self.correct_group.checkedId()
        self.txt_detail.clear()
        self._refresh_stats()
        self.quiz_sent.emit(self._active_quiz_id, q, opts)

    def record_answer(
        self, student_id: str, quiz_id: str, choice_index: int, student_label: str
    ) -> None:
        if quiz_id != self._active_quiz_id:
            return
        self._answers[student_id] = (choice_index, student_label)
        labels = ["A", "B", "C", "D"]
        letter = labels[choice_index] if 0 <= choice_index < len(labels) else "?"
        mark = ""
        if self._correct_idx >= 0:
            mark = " ✅ Đúng" if choice_index == self._correct_idx else " ❌ Sai"
        self.txt_detail.append(f"• {student_label}: chọn {letter}{mark}")
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        total = max(1, len(self._answers))
        counts = [0, 0, 0, 0]
        for choice, _ in self._answers.values():
            if 0 <= choice < 4:
                counts[choice] += 1
        for i in range(4):
            pct = int((counts[i] / total) * 100) if self._answers else 0
            self.bars[i].setValue(pct)
            self.count_labels[i].setText(f"{counts[i]} ({pct}%)")
