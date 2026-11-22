"""Hộp thoại kiểm tra, tải và tự động cập nhật NTQ Remote (Online OTA & LAN)."""

import sys
import threading
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from common.config import APP_VERSION, DEFAULT_UPDATE_MANIFEST_URL
from common.updater import (
    download_update_exe,
    fetch_update_manifest,
    is_newer_version,
    launch_detached_updater,
    prepare_self_update_script,
)
from teacher.server import TeacherServer


class _UpdateSignals(QObject):
    check_ok = Signal(dict)
    check_err = Signal(str)
    dl_progress = Signal(int, int)
    dl_ok = Signal(str)
    dl_err = Signal(str)


class OnlineUpdateDialog(QDialog):
    """Kiểm tra phiên bản mới từ Internet và tự nâng cấp Giáo viên + Học sinh."""

    def __init__(
        self,
        server: TeacherServer,
        parent=None,
        initial_manifest: dict[str, Any] | None = None,
        on_pick_lan_file: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.server = server
        self._on_pick_lan_file = on_pick_lan_file
        self._manifest: dict[str, Any] | None = initial_manifest
        self._signals = _UpdateSignals(self)
        self._busy = False

        self.setWindowTitle(f"Cập nhật phần mềm — NTQ Remote (v{APP_VERSION})")
        self.resize(560, 440)
        self._setup_ui()

        self._signals.check_ok.connect(self._on_check_ok)
        self._signals.check_err.connect(self._on_check_err)
        self._signals.dl_progress.connect(self._on_dl_progress)
        self._signals.dl_ok.connect(self._on_dl_ok)
        self._signals.dl_err.connect(self._on_dl_err)

        if initial_manifest:
            self._on_check_ok(initial_manifest)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        lbl_head = QLabel(
            f"Phiên bản hiện tại: <b>v{APP_VERSION}</b>"
            f" | Máy HS kết nối: <b>{len(self.server.get_students_snapshot())}</b>"
            f" (cũ hơn: <b>{len(self.server.get_outdated_student_ids())}</b>)"
        )
        lbl_head.setStyleSheet("font-size: 13px; color: #0f172a;")
        layout.addWidget(lbl_head)

        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("Nguồn kiểm tra (version.json):"))
        self.edt_url = QLineEdit(
            self.server.update_url or DEFAULT_UPDATE_MANIFEST_URL
        )
        self.edt_url.setPlaceholderText(DEFAULT_UPDATE_MANIFEST_URL)
        url_row.addWidget(self.edt_url, 1)
        layout.addLayout(url_row)

        self.chk_auto = QCheckBox("Tự động kiểm tra bản mới âm thầm khi mở máy Giáo viên")
        self.chk_auto.setChecked(self.server.auto_check_update)
        layout.addWidget(self.chk_auto)

        self.lbl_result = QLabel("Bấm 'Kiểm tra ngay' để kiểm tra bản phát hành mới nhất.")
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setStyleSheet("font-weight: 600; color: #1e3a8a;")
        layout.addWidget(self.lbl_result)

        self.txt_notes = QTextEdit()
        self.txt_notes.setReadOnly(True)
        self.txt_notes.setPlaceholderText("Thông tin thay đổi của phiên bản mới sẽ hiển thị ở đây...")
        self.txt_notes.setMaximumHeight(160)
        layout.addWidget(self.txt_notes)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        btn_row1 = QHBoxLayout()
        self.btn_check = QPushButton("🔍 Kiểm tra ngay")
        self.btn_check.clicked.connect(self._start_check)
        btn_row1.addWidget(self.btn_check)

        self.btn_download = QPushButton("⬇ Tải về & Tự cập nhật")
        self.btn_download.setEnabled(False)
        self.btn_download.setStyleSheet(
            "background-color: #16a34a; color: #ffffff; font-weight: 700; padding: 7px 12px;"
        )
        self.btn_download.clicked.connect(self._start_download)
        btn_row1.addWidget(self.btn_download)
        layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.btn_sync_students = QPushButton("⚡ Đẩy bản hiện tại sang máy HS qua LAN")
        self.btn_sync_students.setEnabled(
            getattr(sys, "frozen", False)
            and len(self.server.get_students_snapshot()) > 0
        )
        self.btn_sync_students.clicked.connect(self._sync_current_exe_to_students)
        btn_row2.addWidget(self.btn_sync_students)

        btn_lan_pick = QPushButton("📂 Chọn tệp EXE đẩy qua LAN...")
        btn_lan_pick.clicked.connect(self._open_lan_picker)
        btn_row2.addWidget(btn_lan_pick)

        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.close)
        btn_row2.addWidget(btn_close)
        layout.addLayout(btn_row2)

    def _save_settings(self) -> str:
        url = self.edt_url.text().strip() or DEFAULT_UPDATE_MANIFEST_URL
        self.server.set_update_settings(url, self.chk_auto.isChecked())
        return url

    def _start_check(self) -> None:
        if self._busy:
            return
        url = self._save_settings()
        self._busy = True
        self.btn_check.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.lbl_result.setStyleSheet("font-weight: 600; color: #1e3a8a;")
        self.lbl_result.setText("Đang kiểm tra phiên bản mới...")

        def _worker() -> None:
            try:
                data = fetch_update_manifest(url)
                self._signals.check_ok.emit(data)
            except Exception as exc:
                self._signals.check_err.emit(str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_check_ok(self, data: dict[str, Any]) -> None:
        self._busy = False
        self._manifest = data
        self.btn_check.setEnabled(True)
        remote_ver = str(data.get("version") or "").strip()
        dl_url = str(data.get("download_url") or "").strip()
        notes = str(data.get("notes") or "").strip()
        released = str(data.get("released_at") or "").strip()
        size_b = int(data.get("file_size") or 0)
        size_note = f" ({size_b / (1024 * 1024):.1f} MB)" if size_b > 0 else ""

        detail_lines = [f"Phiên bản trên máy chủ: v{remote_ver}{size_note}"]
        if released:
            detail_lines.append(f"Ngày phát hành: {released}")
        if notes:
            detail_lines.append("")
            detail_lines.append(notes)
        self.txt_notes.setPlainText("\n".join(detail_lines))

        if is_newer_version(remote_ver, APP_VERSION):
            if dl_url.startswith(("http://", "https://")):
                self.lbl_result.setStyleSheet("font-weight: 700; color: #15803d;")
                self.lbl_result.setText(
                    f"🎉 Đã có phiên bản mới v{remote_ver} (hiện tại v{APP_VERSION})!"
                )
                self.btn_download.setEnabled(True)
            else:
                self.lbl_result.setStyleSheet("font-weight: 600; color: #b45309;")
                self.lbl_result.setText(
                    f"Có bản mới v{remote_ver} nhưng chưa cấu hình đường dẫn tải (download_url)."
                )
                self.btn_download.setEnabled(False)
        else:
            self.lbl_result.setStyleSheet("font-weight: 600; color: #0f766e;")
            self.lbl_result.setText(
                f"✔ Bạn đang dùng phiên bản mới nhất (v{APP_VERSION})."
            )
            self.btn_download.setEnabled(False)

    def _on_check_err(self, err: str) -> None:
        self._busy = False
        self.btn_check.setEnabled(True)
        self.lbl_result.setStyleSheet("font-weight: 600; color: #b91c1c;")
        short = err if len(err) <= 180 else err[:177] + "..."
        self.lbl_result.setText(f"Không kiểm tra được bản mới: {short}")

    def _start_download(self) -> None:
        if self._busy or not self._manifest:
            return
        dl_url = str(self._manifest.get("download_url") or "").strip()
        sha256 = str(self._manifest.get("sha256") or "").strip()
        self._busy = True
        self.btn_check.setEnabled(False)
        self.btn_download.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.lbl_result.setStyleSheet("font-weight: 600; color: #1e3a8a;")
        self.lbl_result.setText("Đang tải bản cập nhật và kiểm tra SHA-256...")

        def _worker() -> None:
            try:
                path = download_update_exe(
                    dl_url,
                    expected_sha256=sha256,
                    progress_cb=lambda got, total: self._signals.dl_progress.emit(got, total),
                )
                self._signals.dl_ok.emit(str(path))
            except Exception as exc:
                self._signals.dl_err.emit(str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_dl_progress(self, got: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, 100)
            pct = max(0, min(100, int(got * 100 / total)))
            self.progress.setValue(pct)
            self.lbl_result.setText(
                f"Đang tải bản cập nhật: {got / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB ({pct}%)"
            )
        else:
            self.progress.setRange(0, 0)
            self.lbl_result.setText(f"Đang tải bản cập nhật: {got / (1024 * 1024):.1f} MB...")

    def _on_dl_ok(self, exe_path_str: str) -> None:
        self._busy = False
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        downloaded = Path(exe_path_str)

        if not getattr(sys, "frozen", False):
            self.btn_check.setEnabled(True)
            QMessageBox.information(
                self,
                "Đã tải xong bản mới",
                f"Tệp đã được xác thực SHA-256 tại:\n{downloaded}\n\n"
                "(Đang chạy từ mã nguồn Python nên không tự ghi đè EXE).",
            )
            return

        target_exe = Path(sys.executable).resolve()
        bat = prepare_self_update_script(
            downloaded, target_exe, launch_args="--teacher"
        )
        launch_detached_updater(bat)
        QMessageBox.information(
            self,
            "Sẵn sàng nâng cấp",
            "Đã tải và xác thực bản mới.\n"
            "Phần mềm Giáo viên sẽ đóng trong giây lát để cập nhật và tự mở lại.\n\n"
            "Sau khi mở lại, bấm '🔄 Cập nhật -> ⚡ Đẩy bản hiện tại sang máy HS qua LAN' để đồng bộ cả lớp.",
        )
        self.server.stop()
        app = QApplication.instance()
        if app:
            app.quit()

    def _on_dl_err(self, err: str) -> None:
        self._busy = False
        self.btn_check.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.progress.setVisible(False)
        self.lbl_result.setStyleSheet("font-weight: 600; color: #b91c1c;")
        short = err if len(err) <= 180 else err[:177] + "..."
        self.lbl_result.setText(f"Lỗi khi tải bản cập nhật: {short}")

    def _sync_current_exe_to_students(self) -> None:
        if not getattr(sys, "frozen", False):
            return
        exe_path = str(Path(sys.executable).resolve())
        targets = self.server.get_outdated_student_ids() or None
        count_text = f"{len(targets)} máy HS cũ hơn" if targets else "toàn bộ máy HS"
        ans = QMessageBox.question(
            self,
            "Đồng bộ phiên bản qua LAN",
            f"Gửi NTQ Remote v{APP_VERSION} xuống {count_text} và tự khởi động lại các máy đó?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.server.distribute_update(targets, exe_path)
            self.lbl_result.setStyleSheet("font-weight: 600; color: #15803d;")
            self.lbl_result.setText(f"Đang gửi v{APP_VERSION} qua LAN xuống máy học sinh...")

    def _open_lan_picker(self) -> None:
        if self._on_pick_lan_file:
            self.close()
            self._on_pick_lan_file()
