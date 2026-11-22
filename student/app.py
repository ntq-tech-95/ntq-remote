"""Điểm khởi chạy ứng dụng Máy Học Sinh - Phòng Tin Học VN."""

import sys

from PySide6.QtWidgets import QApplication

from common.config import APP_NAME
from student.client import StudentClient
from student.tray_window import StudentMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_NAME} - Học Sinh")
    app.setQuitOnLastWindowClosed(False)

    manual_ip = sys.argv[1] if len(sys.argv) > 1 else ""
    client = StudentClient(manual_host=manual_ip)
    win = StudentMainWindow(client)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
