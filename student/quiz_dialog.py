"""Cửa sổ trả lời câu hỏi trắc nghiệm nhanh trên Máy Học Sinh."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


class StudentQuizDialog(QDialog):
    """Hiển thị câu hỏi trắc nghiệm giáo viên vừa gửi để học sinh chọn đáp án."""

    answer_submitted = Signal(str, int)

    def __init__(
        self,
        quiz_id: str,
        question: str,
        options: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.quiz_id = quiz_id
        self.setWindowTitle("📝 Câu hỏi nhanh từ Giáo viên")
        self.resize(460, 320)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        lbl_q = QLabel(question)
        lbl_q.setWordWrap(True)
        lbl_q.setStyleSheet("font-size: 14px; font-weight: 700; color: #0f172a;")
        root.addWidget(lbl_q)

        self.group = QButtonGroup(self)
        letters = ["A", "B", "C", "D"]
        for i, opt in enumerate(options):
            prefix = letters[i] if i < len(letters) else str(i + 1)
            rb = QRadioButton(f"{prefix}. {opt}")
            rb.setStyleSheet("font-size: 13px; padding: 4px;")
            self.group.addButton(rb, i)
            root.addWidget(rb)

        root.addStretch(1)
        btn_submit = QPushButton("✔ Gửi đáp án")
        btn_submit.setStyleSheet(
            "background-color: #2563eb; color: #ffffff; border: none; padding: 9px 16px; font-weight: 700;"
        )
        btn_submit.clicked.connect(self._on_submit)
        root.addWidget(btn_submit)

    def _on_submit(self) -> None:
        idx = self.group.checkedId()
        if idx < 0:
            QMessageBox.information(self, "Chưa chọn đáp án", "Em hãy chọn 1 đáp án trước khi gửi.")
            return
        self.answer_submitted.emit(self.quiz_id, idx)
        self.accept()
