"""Quản lý bật/tắt tự động khởi động cùng Windows (Registry HKCU\\...\\Run)."""

import sys
from pathlib import Path

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
TEACHER_AUTOSTART_KEY = "PhongTinHocVN_GiaoVien"
STUDENT_AUTOSTART_KEY = "PhongTinHocVN_HocSinh"

if sys.platform == "win32":
    import winreg


def build_launch_command(entry_script: str, unified_flag: str = "") -> str:
    """Tạo dòng lệnh khởi chạy ứng dụng phù hợp cho bản gộp 1 file, bản tách riêng và bản Python."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if unified_flag and exe.stem.lower() not in ("giaovien", "hocsinh"):
            return f'"{exe}" {unified_flag}'
        return f'"{exe}"'

    exe_path = Path(sys.executable).resolve()
    pythonw = exe_path.with_name("pythonw.exe")
    launcher = pythonw if pythonw.is_file() else exe_path
    root_dir = Path(__file__).resolve().parent.parent
    script_path = (root_dir / entry_script).resolve()
    return f'"{launcher}" "{script_path}"'


def is_autostart_enabled(app_key: str, reg_path: str = RUN_KEY_PATH) -> bool:
    """Kiểm tra xem ứng dụng đã được bật khởi động cùng Windows chưa."""
    if sys.platform != "win32":
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, app_key)
            return bool(str(value).strip())
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart(
    app_key: str,
    enabled: bool,
    command: str | None = None,
    reg_path: str = RUN_KEY_PATH,
) -> tuple[bool, str]:
    """Bật hoặc tắt khởi động cùng Windows cho app_key."""
    if sys.platform != "win32":
        return False, "Tính năng khởi động cùng hệ thống chỉ hỗ trợ trên Windows."

    try:
        if enabled:
            cmd = (command or "").strip()
            if not cmd:
                return False, "Không xác định được đường dẫn khởi chạy ứng dụng."
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, app_key, 0, winreg.REG_SZ, cmd)
            return True, "Đã bật tự động khởi động cùng Windows."

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, app_key)
        except FileNotFoundError:
            pass
        return True, "Đã tắt tự động khởi động cùng Windows."
    except OSError as exc:
        return False, f"Không thể cập nhật thiết lập khởi động cùng Windows: {exc}"
