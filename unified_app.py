"""Ứng dụng hợp nhất 1 file duy nhất: Chạy ngay Giáo viên/Học sinh hoặc Cài đặt vào máy."""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from common.config import APP_AUTHOR, APP_NAME, APP_VERSION
from common.storage import load_student_state, save_student_state
from common.ui_helpers import load_app_icon
from installer.setup_wizard import default_install_dir, perform_unified_install
from student.client import StudentClient
from student.tray_window import StudentMainWindow
from teacher.license_dialog import ensure_teacher_licensed
from teacher.main_window import TeacherMainWindow
from teacher.server import TeacherServer


class _InstallSignals(QObject):
    progress = Signal(str)
    finished = Signal(list)
    failed = Signal(str)


class UnifiedLauncherWindow(QMainWindow):
    """Màn hình chọn chế độ chạy ngay hoặc cài đặt vào máy tính (100% Tiếng Việt)."""

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self._app = app
        self._active_windows: list[QMainWindow] = []
        self._installed_targets: list[tuple[Path, str]] = []
        self._signals = _InstallSignals()

        self.setWindowTitle(f"{APP_NAME} (v{APP_VERSION}) — Tác giả: {APP_AUTHOR}")
        ico = load_app_icon()
        if not ico.isNull():
            self.setWindowIcon(ico)
        self.resize(640, 610)
        self._setup_ui()

        self._signals.progress.connect(self._set_status_text)
        self._signals.finished.connect(self._on_install_done)
        self._signals.failed.connect(self._on_install_error)

    def _setup_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background-color: #f1f5f9; }
            QGroupBox {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
                margin-top: 10px;
                padding: 12px;
                font-weight: 700;
                color: #0f172a;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #e2e8f0; }
            """
        )

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Tiêu đề
        banner = QFrame()
        banner.setStyleSheet("background-color: #1e3a8a; border-radius: 8px;")
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(14, 12, 14, 12)
        lbl_t = QLabel(f"🏫 {APP_NAME.upper()} (v{APP_VERSION})")
        lbl_t.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: 700;")
        lbl_s = QLabel(
            f"Quản lý phòng tin học 100% Tiếng Việt — Tác giả: {APP_AUTHOR}"
        )
        lbl_s.setStyleSheet("color: #dbeafe; font-size: 12px;")
        bl.addWidget(lbl_t)
        bl.addWidget(lbl_s)
        root.addWidget(banner)

        # Phần 1: Chạy trực tiếp
        grp_run = QGroupBox("1. Chạy ngay lập tức (không cần cài đặt)")
        rl = QHBoxLayout(grp_run)
        rl.setSpacing(10)

        btn_teacher = QPushButton("👨‍🏫 Mở chế độ MÁY GIÁO VIÊN")
        btn_teacher.setStyleSheet(
            "background-color: #2563eb; color: #ffffff; border: none; padding: 12px; font-size: 13px;"
        )
        btn_teacher.clicked.connect(self._launch_teacher)
        rl.addWidget(btn_teacher, 1)

        btn_student = QPushButton("🧑‍🎓 Mở chế độ MÁY HỌC SINH")
        btn_student.setStyleSheet(
            "background-color: #16a34a; color: #ffffff; border: none; padding: 12px; font-size: 13px;"
        )
        btn_student.clicked.connect(self._launch_student)
        rl.addWidget(btn_student, 1)
        root.addWidget(grp_run)

        # Phần 2: Cài đặt cố định vào máy
        grp_inst = QGroupBox("2. Cài đặt vào máy tính này (tạo lối tắt & tự khởi động)")
        il = QVBoxLayout(grp_inst)
        il.setSpacing(8)

        self.role_group = QButtonGroup(self)
        self.rad_student = QRadioButton("Máy Học Sinh (cài cho các máy trạm của học sinh)")
        self.rad_student.setChecked(True)
        self.rad_teacher = QRadioButton("Máy Giáo Viên (cài cho máy chủ của giáo viên)")
        self.rad_both = QRadioButton("Cài lối tắt cho cả Giáo viên & Học sinh")
        for idx, rb in enumerate((self.rad_student, self.rad_teacher, self.rad_both)):
            self.role_group.addButton(rb, idx)
            il.addWidget(rb)

        dir_row = QHBoxLayout()
        lbl_d = QLabel("Thư mục cài:")
        lbl_d.setStyleSheet("font-weight: 600;")
        dir_row.addWidget(lbl_d)
        self.edt_dir = QLineEdit(str(default_install_dir()))
        dir_row.addWidget(self.edt_dir, 1)
        btn_browse = QPushButton("Chọn...")
        btn_browse.clicked.connect(self._browse_dir)
        dir_row.addWidget(btn_browse)
        il.addLayout(dir_row)

        room_row = QHBoxLayout()
        lbl_rm = QLabel("Khóa mã phòng HS:")
        lbl_rm.setStyleSheet("font-weight: 600;")
        room_row.addWidget(lbl_rm)
        self.edt_room = QLineEdit()
        self.edt_room.setPlaceholderText("Tùy chọn: VD PHONG-TIN-01 (để trống = tự nhận trong LAN)")
        room_row.addWidget(self.edt_room, 1)
        il.addLayout(room_row)

        self.chk_desktop = QCheckBox("Tạo biểu tượng ngoài màn hình Desktop")
        self.chk_desktop.setChecked(True)
        self.chk_start_menu = QCheckBox("Tạo lối tắt trong Start Menu & bộ gỡ cài đặt")
        self.chk_start_menu.setChecked(True)
        self.chk_autostart = QCheckBox("Tự động khởi động cùng Windows khi mở máy")
        self.chk_autostart.setChecked(True)
        self.chk_firewall = QCheckBox("Tự động mở cổng tường lửa Windows (nếu có quyền Quản trị)")
        self.chk_firewall.setChecked(True)
        self.chk_elevated_task = QCheckBox(
            "Chạy nền quyền Quản trị viên (hỗ trợ khóa cổng USB — nếu cài bằng Run as Administrator)"
        )
        self.chk_elevated_task.setChecked(False)
        for chk in (
            self.chk_desktop,
            self.chk_start_menu,
            self.chk_autostart,
            self.chk_firewall,
            self.chk_elevated_task,
        ):
            il.addWidget(chk)

        self.lbl_status = QLabel("Sẵn sàng.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum
        )
        self.lbl_status.setMaximumHeight(52)
        self.lbl_status.setStyleSheet("color: #475569; font-size: 12px;")
        il.addWidget(self.lbl_status)

        act_row = QHBoxLayout()
        self.btn_quick_student = QPushButton("⚡ Cài nhanh MÁY HỌC SINH (1 chạm)")
        self.btn_quick_student.setStyleSheet(
            "background-color: #16a34a; color: #ffffff; border: none; padding: 9px 14px;"
        )
        self.btn_quick_student.setToolTip(
            "Cài ngay phần Học sinh với đầy đủ lối tắt Desktop, Start Menu và Tự khởi động"
        )
        self.btn_quick_student.clicked.connect(self._quick_install_student)
        act_row.addWidget(self.btn_quick_student)

        self.btn_install = QPushButton("📥 Cài theo tùy chọn trên")
        self.btn_install.setStyleSheet(
            "background-color: #0f172a; color: #ffffff; border: none; padding: 9px 14px;"
        )
        self.btn_install.clicked.connect(self._start_install)
        act_row.addWidget(self.btn_install)

        self.btn_open_installed = QPushButton("▶ Mở ngay")
        self.btn_open_installed.setEnabled(False)
        self.btn_open_installed.clicked.connect(self._open_installed)
        act_row.addWidget(self.btn_open_installed)
        il.addLayout(act_row)

        root.addWidget(grp_inst, 1)

        lbl_footer = QLabel(f"© Bản quyền thuộc về tác giả: {APP_AUTHOR}")
        lbl_footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_footer.setStyleSheet("color: #475569; font-size: 11px; font-weight: 700;")
        root.addWidget(lbl_footer)

    def _launch_teacher(self) -> None:
        if ensure_teacher_licensed(self) is None:
            return
        server = TeacherServer()
        win = TeacherMainWindow(server)
        self._active_windows.append(win)
        win.show()
        self.hide()

    def _launch_student(self) -> None:
        self._app.setQuitOnLastWindowClosed(False)
        client = StudentClient()
        win = StudentMainWindow(client)
        self._active_windows.append(win)
        win.show()
        self.hide()

    def _browse_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục cài đặt", self.edt_dir.text()
        )
        if chosen:
            self.edt_dir.setText(chosen)

    def _selected_role(self) -> str:
        if self.rad_teacher.isChecked():
            return "teacher"
        if self.rad_both.isChecked():
            return "both"
        return "student"

    def _quick_install_student(self) -> None:
        self.rad_student.setChecked(True)
        self.chk_desktop.setChecked(True)
        self.chk_start_menu.setChecked(True)
        self.chk_autostart.setChecked(True)
        self.chk_firewall.setChecked(True)
        self._start_install()

    def _start_install(self) -> None:
        import threading

        target_dir = Path(self.edt_dir.text().strip())
        if not str(target_dir):
            QMessageBox.warning(self, "Thiếu thư mục", "Vui lòng chọn thư mục cài đặt.")
            return

        role = self._selected_role()
        if role in ("teacher", "both") and ensure_teacher_licensed(self) is None:
            return
        room_code = self.edt_room.text().strip()
        if role in ("student", "both") and room_code:
            st = load_student_state()
            st["target_room"] = room_code
            save_student_state(st)

        make_desktop = self.chk_desktop.isChecked()
        make_start = self.chk_start_menu.isChecked()
        autostart = self.chk_autostart.isChecked()
        firewall = self.chk_firewall.isChecked()
        elevated_task = self.chk_elevated_task.isChecked()

        self.btn_install.setEnabled(False)
        self.btn_quick_student.setEnabled(False)

        def _worker() -> None:
            try:
                res = perform_unified_install(
                    role=role,
                    install_dir=target_dir,
                    make_desktop=make_desktop,
                    make_start_menu=make_start,
                    enable_autostart=autostart,
                    add_firewall=firewall,
                    log_cb=lambda m: self._signals.progress.emit(m),
                    elevated_task=elevated_task,
                )
                self._signals.finished.emit(res)
            except Exception as exc:
                self._signals.failed.emit(str(exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_install_done(self, targets: list) -> None:
        self._installed_targets = targets
        self.btn_install.setEnabled(True)
        self.btn_quick_student.setEnabled(True)
        self.btn_install.setText("📥 Cài đặt lại")
        self.btn_open_installed.setEnabled(True)
        QMessageBox.information(
            self,
            "Cài đặt thành công",
            f"Đã cài đặt xong tại:\n{self.edt_dir.text()}\n\nBạn có thể mở phần mềm từ biểu tượng ngoài Desktop hoặc bấm 'Mở ngay'.",
        )

    def _set_status_text(self, text: str, is_error: bool = False) -> None:
        clean = " ".join(str(text).splitlines()).strip()
        if len(clean) > 160:
            clean = clean[:157] + "..."
        color = "#b91c1c" if is_error else "#475569"
        self.lbl_status.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.lbl_status.setToolTip(str(text))
        self.lbl_status.setText(clean)

    def _on_install_error(self, err: str) -> None:
        self.btn_install.setEnabled(True)
        self.btn_quick_student.setEnabled(True)
        self._set_status_text(f"Lỗi: {err}", is_error=True)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Lỗi cài đặt")
        short_err = err if len(err) <= 240 else err[:237] + "..."
        box.setText(f"Không thể hoàn tất cài đặt:\n{short_err}")
        if len(err) > 240:
            box.setDetailedText(err)
        box.exec()

    def _open_installed(self) -> None:
        for exe_path, flag in self._installed_targets:
            if exe_path.is_file():
                subprocess.Popen([str(exe_path), flag], cwd=str(exe_path.parent))
        self.close()


def _get_arg_value(args: list[str], flag: str) -> str:
    if flag in args:
        idx = args.index(flag)
        if idx + 1 < len(args):
            return args[idx + 1].strip()
    return ""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if "--install-student" in args:
        target_dir = Path(_get_arg_value(args, "--dir") or str(default_install_dir()))
        room_code = _get_arg_value(args, "--room")
        if room_code:
            st = load_student_state()
            st["target_room"] = room_code
            save_student_state(st)
        perform_unified_install(
            role="student",
            install_dir=target_dir,
            make_desktop=True,
            make_start_menu=True,
            enable_autostart=True,
            add_firewall=True,
        )
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    ico = load_app_icon()
    if not ico.isNull():
        app.setWindowIcon(ico)

    if "--teacher" in args:
        if ensure_teacher_licensed() is None:
            return 0
        server = TeacherServer()
        win = TeacherMainWindow(server)
        win.show()
        return app.exec()

    if "--student" in args:
        app.setQuitOnLastWindowClosed(False)
        client = StudentClient()
        win = StudentMainWindow(client)
        win.show()
        return app.exec()

    launcher = UnifiedLauncherWindow(app)
    launcher.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
