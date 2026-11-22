"""Tạo đề kiểm tra nhiều câu tự chấm, thống kê trực tiếp và xuất bảng điểm Excel."""

import csv
import json
import time
import uuid
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ExamTeacherDialog(QDialog):
    """Trình tạo đề kiểm tra trắc nghiệm nhiều câu và chấm điểm tự động."""

    exam_sent = Signal(str, str, int, list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("📝 Tạo Đề Kiểm Tra Nhiều Câu & Chấm Điểm Tự Động")
        self.resize(920, 620)
        self._questions: list[dict[str, Any]] = []
        self._active_exam_id = ""
        self._results: dict[str, tuple[str, int, int, float, str]] = {}

        root = QVBoxLayout(self)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.addWidget(QLabel("Tên bài kiểm tra:"))
        self.edt_title = QLineEdit("Kiểm tra 15 phút Tin học")
        top.addWidget(self.edt_title, 1)
        top.addWidget(QLabel("Thời gian (phút):"))
        self.spn_minutes = QSpinBox()
        self.spn_minutes.setRange(1, 120)
        self.spn_minutes.setValue(10)
        top.addWidget(self.spn_minutes)

        btn_load = QPushButton("📂 Mở bộ đề (.json)")
        btn_load.clicked.connect(self._on_load_bank)
        top.addWidget(btn_load)

        btn_save = QPushButton("💾 Lưu bộ đề")
        btn_save.clicked.connect(self._on_save_bank)
        top.addWidget(btn_save)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Trái: Soạn câu hỏi
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Danh sách câu hỏi trong đề:"))
        self.list_questions = QListWidget()
        ll.addWidget(self.list_questions, 1)

        btn_del_q = QPushButton("🗑 Xóa câu hỏi đang chọn")
        btn_del_q.clicked.connect(self._on_delete_question)
        ll.addWidget(btn_del_q)

        ll.addWidget(QLabel("Thêm câu hỏi mới:"))
        self.edt_q = QLineEdit()
        self.edt_q.setPlaceholderText("Nhập nội dung câu hỏi...")
        ll.addWidget(self.edt_q)

        self.opt_edits: list[QLineEdit] = []
        for letter in ("A", "B", "C", "D"):
            e = QLineEdit()
            e.setPlaceholderText(f"Đáp án {letter}...")
            self.opt_edits.append(e)
            ll.addWidget(e)

        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Đáp án đúng:"))
        self.cmb_correct = QComboBox()
        self.cmb_correct.addItems(["A", "B", "C", "D"])
        add_row.addWidget(self.cmb_correct)
        btn_add = QPushButton("+ Thêm câu vào đề")
        btn_add.clicked.connect(self._on_add_question)
        add_row.addWidget(btn_add, 1)
        ll.addLayout(add_row)

        btn_send = QPushButton("🚀 Phát đề kiểm tra cho lớp")
        btn_send.setStyleSheet(
            "background-color: #2563eb; color: #ffffff; border: none; padding: 9px; font-weight: 700;"
        )
        btn_send.clicked.connect(self._on_send_exam)
        ll.addWidget(btn_send)
        splitter.addWidget(left)

        # Phải: Bảng điểm chấm tự động
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("Bảng điểm trực tiếp (Chấm tự động):"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Học sinh / Máy", "Số câu đúng", "Điểm (thang 10)", "Giờ nộp"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        rl.addWidget(self.table, 1)

        btn_export = QPushButton("📊 Xuất bảng điểm ra Excel (.csv)")
        btn_export.clicked.connect(self._on_export_scores)
        rl.addWidget(btn_export)
        splitter.addWidget(right)
        splitter.setSizes([450, 450])

        root.addWidget(splitter, 1)

    def _on_add_question(self) -> None:
        q = self.edt_q.text().strip()
        opts = [e.text().strip() for e in self.opt_edits]
        if not q or any(not o for o in opts):
            QMessageBox.warning(
                self, "Thiếu thông tin", "Vui lòng nhập đầy đủ câu hỏi và 4 đáp án A, B, C, D."
            )
            return
        correct_idx = self.cmb_correct.currentIndex()
        self._questions.append(
            {"question": q, "options": opts, "correct_index": correct_idx}
        )
        self._refresh_list()
        self.edt_q.clear()
        for e in self.opt_edits:
            e.clear()

    def _on_delete_question(self) -> None:
        row = self.list_questions.currentRow()
        if 0 <= row < len(self._questions):
            self._questions.pop(row)
            self._refresh_list()

    def _refresh_list(self) -> None:
        self.list_questions.clear()
        letters = ["A", "B", "C", "D"]
        for i, q in enumerate(self._questions, start=1):
            c = letters[q["correct_index"]] if 0 <= q["correct_index"] < 4 else "?"
            self.list_questions.addItem(f"Câu {i}: {q['question']} (Đáp án: {c})")

    def _on_save_bank(self) -> None:
        if not self._questions:
            QMessageBox.information(self, "Trống", "Chưa có câu hỏi nào để lưu.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu bộ đề kiểm tra", str(Path.home() / "Desktop" / "BoDeTinHoc.json"), "JSON (*.json)"
        )
        if not path:
            return
        payload = {
            "title": self.edt_title.text().strip(),
            "duration_minutes": self.spn_minutes.value(),
            "questions": self._questions,
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _on_load_bank(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Mở bộ đề kiểm tra", str(Path.home() / "Desktop"), "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.edt_title.setText(str(data.get("title") or "Bài kiểm tra"))
            self.spn_minutes.setValue(int(data.get("duration_minutes") or 10))
            self._questions = list(data.get("questions") or [])
            self._refresh_list()
        except Exception as exc:
            QMessageBox.warning(self, "Lỗi đọc đề", f"Không thể mở tệp đề: {exc}")

    def _on_send_exam(self) -> None:
        if not self._questions:
            QMessageBox.warning(self, "Chưa có câu hỏi", "Vui lòng thêm ít nhất 1 câu hỏi trước khi phát đề.")
            return
        self._active_exam_id = uuid.uuid4().hex[:8]
        self._results.clear()
        self.table.setRowCount(0)
        self.exam_sent.emit(
            self._active_exam_id,
            self.edt_title.text().strip() or "Bài kiểm tra",
            self.spn_minutes.value(),
            list(self._questions),
        )
        QMessageBox.information(
            self,
            "Đã phát đề",
            f"Đã phát đề '{self.edt_title.text().strip()}' ({len(self._questions)} câu) xuống máy học sinh!",
        )

    def record_submission(
        self,
        student_id: str,
        exam_id: str,
        student_label: str,
        correct: int,
        total: int,
        score: float,
    ) -> None:
        if exam_id != self._active_exam_id:
            return
        self._results[student_id] = (
            student_label,
            correct,
            total,
            score,
            time.strftime("%H:%M:%S"),
        )
        self.table.setRowCount(len(self._results))
        for r, (name, cor, tot, sc, stamp) in enumerate(self._results.values()):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(f"{cor}/{tot}"))
            self.table.setItem(r, 2, QTableWidgetItem(f"{sc:.2f}"))
            self.table.setItem(r, 3, QTableWidgetItem(stamp))

    def _on_export_scores(self) -> None:
        if not self._results:
            QMessageBox.information(self, "Chưa có điểm", "Chưa có học sinh nào nộp bài.")
            return
        default_name = f"BangDiem_{time.strftime('%Y%m%d_%H%M')}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất bảng điểm", str(Path.home() / "Desktop" / default_name), "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["STT", "Học sinh / Máy", "Số câu đúng", "Tổng số câu", "Điểm (thang 10)", "Giờ nộp"])
            for idx, (name, cor, tot, sc, stamp) in enumerate(self._results.values(), start=1):
                writer.writerow([idx, name, cor, tot, f"{sc:.2f}", stamp])
        QMessageBox.information(self, "Xuất bảng điểm", f"Đã lưu bảng điểm tại:\n{path}")
