"""Cửa sổ làm bài kiểm tra nhiều câu có đồng hồ đếm ngược cho Học sinh."""

from typing import Any

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class StudentExamDialog(QDialog):
    """Hiển thị toàn bộ câu hỏi kiểm tra và tự động nộp khi hết giờ."""

    exam_submitted = Signal(str, list)

    def __init__(
        self,
        exam_id: str,
        title: str,
        duration_minutes: int,
        questions: list[dict[str, Any]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.exam_id = exam_id
        self._remaining_sec = max(10, int(duration_minutes) * 60)
        self._groups: list[QButtonGroup] = []
        self._submitted = False

        self.setWindowTitle(f"📝 Bài kiểm tra: {title}")
        self.resize(640, 560)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        top = QHBoxLayout()
        lbl_t = QLabel(f"Bài kiểm tra: {title} ({len(questions)} câu)")
        lbl_t.setStyleSheet("font-weight: 700; font-size: 14px;")
        top.addWidget(lbl_t, 1)

        self.lbl_timer = QLabel()
        self.lbl_timer.setStyleSheet(
            "background:#fee2e2; color:#991b1b; padding:5px 10px; border-radius:6px; font-weight:700;"
        )
        top.addWidget(self.lbl_timer)
        root.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setSpacing(10)

        letters = ["A", "B", "C", "D"]
        for i, q in enumerate(questions, start=1):
            box = QFrame()
            box.setStyleSheet(
                "QFrame { background:#ffffff; border:1px solid #cbd5e1; border-radius:8px; }"
            )
            bl = QVBoxLayout(box)
            lbl_q = QLabel(f"Câu {i}: {q['question']}")
            lbl_q.setWordWrap(True)
            lbl_q.setStyleSheet("font-weight: 700; border: none;")
            bl.addWidget(lbl_q)

            grp = QButtonGroup(self)
            for idx, opt in enumerate(q.get("options", [])):
                prefix = letters[idx] if idx < len(letters) else str(idx + 1)
                rb = QRadioButton(f"{prefix}. {opt}")
                grp.addButton(rb, idx)
                bl.addWidget(rb)
            self._groups.append(grp)
            cl.addWidget(box)

        cl.addStretch(1)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        btn_submit = QPushButton("✔ Nộp bài kiểm tra")
        btn_submit.setStyleSheet(
            "background-color: #16a34a; color: #ffffff; border: none; padding: 10px; font-weight: 700; font-size: 13px;"
        )
        btn_submit.clicked.connect(lambda: self._submit(auto=False))
        root.addWidget(btn_submit)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._refresh_timer_label()
        self._timer.start(1000)

    def _refresh_timer_label(self) -> None:
        mins, secs = divmod(self._remaining_sec, 60)
        self.lbl_timer.setText(f"⏱ Còn lại: {mins:02d}:{secs:02d}")

    def _on_tick(self) -> None:
        self._remaining_sec -= 1
        self._refresh_timer_label()
        if self._remaining_sec <= 0:
            self._timer.stop()
            self._submit(auto=True)

    def _submit(self, auto: bool) -> None:
        if self._submitted:
            return
        if not auto:
            unanswered = sum(1 for g in self._groups if g.checkedId() < 0)
            if unanswered > 0:
                reply = QMessageBox.question(
                    self,
                    "Xác nhận nộp bài",
                    f"Em vẫn còn {unanswered} câu chưa chọn đáp án. Em có chắc muốn nộp bài không?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
        self._submitted = True
        self._timer.stop()
        answers = [g.checkedId() for g in self._groups]
        self.exam_submitted.emit(self.exam_id, answers)
        self.accept()
