"""Điểm khởi chạy ứng dụng Máy Giáo Viên - Phòng Tin Học VN."""

import sys

from PySide6.QtWidgets import QApplication

from common.config import APP_NAME
from teacher.license_dialog import ensure_teacher_licensed
from teacher.main_window import TeacherMainWindow
from teacher.server import TeacherServer


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} - Giáo Viên")
    if ensure_teacher_licensed() is None:
        return 0
    server = TeacherServer()
    win = TeacherMainWindow(server)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
