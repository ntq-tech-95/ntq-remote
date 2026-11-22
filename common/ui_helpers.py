"""Tiện ích tải biểu tượng ứng dụng NTQ Remote."""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon


def get_app_icon_path() -> Path | None:
    """Tìm đường dẫn tới tệp biểu tượng ntq_remote.ico."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate = Path(sys._MEIPASS) / "assets" / "ntq_remote.ico"
        if candidate.is_file():
            return candidate
    candidate = Path(__file__).resolve().parent.parent / "assets" / "ntq_remote.ico"
    if candidate.is_file():
        return candidate
    return None


def load_app_icon() -> QIcon:
    """Tải QIcon biểu tượng ứng dụng NTQ Remote."""
    path = get_app_icon_path()
    if path is not None:
        return QIcon(str(path))
    return QIcon()
