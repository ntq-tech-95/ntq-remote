"""Hộp thoại kiểm tra và kích hoạt bản quyền phần mềm Phòng Tin Học VN."""

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from common.config import APP_AUTHOR
from common.licensing import (
    LicenseInfo,
    check_active_license,
    get_hardware_id,
    save_license_key,
    verify_license_key,
)


class LicenseDialog(QDialog):
    """Cửa sổ kích hoạt bản quyền theo Mã máy (100% Tiếng Việt)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        state_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._state_dir = state_dir
        self._hwid = get_hardware_id()
        self.license_info: LicenseInfo | None = None

        self.setWindowTitle("🔐 Bản quyền Phòng Tin Học VN")
        self.resize(580, 410)

        root = QVBoxLayout(self)
        root.setSpacing(10)

        ok, info, status_msg = check_active_license(state_dir)
        self.license_info = info if ok else None

        self.lbl_status = QLabel(status_msg)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(
            "background:#dcfce7; color:#166534; padding:8px; border-radius:6px; font-weight:700;"
            if ok
            else "background:#fef3c7; color:#92400e; padding:8px; border-radius:6px; font-weight:700;"
        )
        root.addWidget(self.lbl_status)

        lbl_hw = QLabel(
            f"Mã máy (Hardware ID) của máy Giáo viên này (gửi mã này cho tác giả {APP_AUTHOR} để cấp key):"
        )
        lbl_hw.setStyleSheet("font-weight: 700;")
        root.addWidget(lbl_hw)

        hw_row = QHBoxLayout()
        self.edt_hwid = QLineEdit(self._hwid)
        self.edt_hwid.setReadOnly(True)
        self.edt_hwid.setStyleSheet("font-family: Consolas; font-size: 13px; font-weight: 700;")
        hw_row.addWidget(self.edt_hwid, 1)

        btn_copy = QPushButton("📋 Copy Mã máy")
        btn_copy.clicked.connect(self._copy_hwid)
        hw_row.addWidget(btn_copy)
        root.addLayout(hw_row)

        lbl_key = QLabel("Dán Mã bản quyền (PTH1....) hoặc nạp từ tệp .lic:")
        lbl_key.setStyleSheet("font-weight: 700;")
        root.addWidget(lbl_key)

        self.txt_key = QTextEdit()
        self.txt_key.setPlaceholderText("Dán mã bản quyền bắt đầu bằng PTH1. vào đây...")
        self.txt_key.setStyleSheet("font-family: Consolas; font-size: 11px;")
        root.addWidget(self.txt_key, 1)

        btn_row = QHBoxLayout()
        btn_load = QPushButton("📂 Nạp tệp .lic...")
        btn_load.clicked.connect(self._load_lic_file)
        btn_row.addWidget(btn_load)

        btn_row.addStretch(1)
        btn_activate = QPushButton("✔ Kích hoạt bản quyền")
        btn_activate.setStyleSheet(
            "background-color: #2563eb; color: #ffffff; border: none; padding: 8px 16px; font-weight: 700;"
        )
        btn_activate.clicked.connect(self._on_activate)
        btn_row.addWidget(btn_activate)

        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)
        root.addLayout(btn_row)

    def _copy_hwid(self) -> None:
        QApplication.clipboard().setText(self._hwid)
        QMessageBox.information(
            self,
            "Đã sao chép",
            f"Đã sao chép Mã máy:\n{self._hwid}\n\nHãy gửi mã này cho tác giả để nhận Mã bản quyền.",
        )

    def _load_lic_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn tệp bản quyền (.lic)", str(Path.home()), "Tệp bản quyền (*.lic *.txt)"
        )
        if path:
            self.txt_key.setPlainText(Path(path).read_text(encoding="utf-8").strip())

    def _on_activate(self) -> None:
        key_text = self.txt_key.toPlainText().strip()
        ok, info, msg = verify_license_key(key_text, expected_hwid=self._hwid)
        if not ok or info is None:
            QMessageBox.warning(self, "Mã bản quyền không hợp lệ", msg)
            return
        save_license_key(key_text, self._state_dir)
        self.license_info = info
        QMessageBox.information(self, "Kích hoạt thành công", msg)
        self.accept()


def ensure_teacher_licensed(
    parent: QWidget | None = None,
    state_dir: Path | None = None,
) -> LicenseInfo | None:
    """Đảm bảo Máy Giáo Viên có bản quyền hợp lệ trước khi sử dụng."""
    ok, info, _ = check_active_license(state_dir)
    if ok and info is not None:
        return info
    dlg = LicenseDialog(parent=parent, state_dir=state_dir)
    if dlg.exec() == QDialog.DialogCode.Accepted and dlg.license_info is not None:
        return dlg.license_info
    return None
