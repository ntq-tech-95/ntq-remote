"""Các hàm tiện ích mạng và đường dẫn tệp an toàn."""

import os
import re
import socket
import uuid
from pathlib import Path


def get_local_ip() -> str:
    """Lấy địa chỉ IP mạng LAN hiện tại của máy."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def get_broadcast_addresses() -> list[str]:
    """Trả về danh sách địa chỉ broadcast để dò tìm trong mạng LAN."""
    addrs = {"255.255.255.255", "127.0.0.1"}
    local_ip = get_local_ip()
    parts = local_ip.split(".")
    if len(parts) == 4:
        addrs.add(f"{parts[0]}.{parts[1]}.{parts[2]}.255")
    return list(addrs)


def get_hostname() -> str:
    """Lấy tên máy tính Windows."""
    return socket.gethostname() or "May-Hoc-Sinh"


def sanitize_filename(name: str) -> str:
    """Làm sạch tên tệp/thư mục để tránh ký tự không hợp lệ hoặc path traversal."""
    base = os.path.basename(name.strip())
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base)
    return cleaned or "tep_khong_ten"


def get_student_inbox_dir() -> Path:
    """Thư mục lưu bài tập học sinh nhận được từ giáo viên."""
    desktop = Path.home() / "Desktop"
    base = desktop if desktop.exists() else Path.home()
    folder = base / "BaiTapNhanTuGiaoVien"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_teacher_collect_dir() -> Path:
    """Thư mục lưu bài làm thu từ học sinh về máy giáo viên."""
    desktop = Path.home() / "Desktop"
    base = desktop if desktop.exists() else Path.home()
    folder = base / "BaiThuTuHocSinh"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_app_data_dir() -> Path:
    """Thư mục lưu cấu hình nhỏ gọn của phần mềm."""
    local_app = os.environ.get("LOCALAPPDATA")
    base = Path(local_app) if local_app else Path.home()
    folder = base / "PhongTinHocVN"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def get_mac_address() -> str:
    """Lấy địa chỉ MAC của máy hiện tại dạng AA:BB:CC:DD:EE:FF."""
    node = uuid.getnode()
    return ":".join(f"{(node >> shift) & 0xFF:02X}" for shift in range(40, -1, -8))


def parse_mac_bytes(mac_str: str) -> bytes:
    """Chuyển chuỗi địa chỉ MAC thành 6 byte nhị phân."""
    hex_only = re.sub(r"[^0-9A-Fa-f]", "", mac_str)
    if len(hex_only) != 12:
        raise ValueError(f"Địa chỉ MAC không hợp lệ: {mac_str}")
    return bytes.fromhex(hex_only)


def send_wake_on_lan(
    mac_address: str, broadcast_ips: list[str] | None = None
) -> tuple[bool, str]:
    """Gửi gói tin Magic Packet (Wake-on-LAN) để bật máy tính qua mạng LAN."""
    try:
        mac_bytes = parse_mac_bytes(mac_address)
    except ValueError as exc:
        return False, str(exc)

    packet = b"\xff" * 6 + mac_bytes * 16
    targets = broadcast_ips or get_broadcast_addresses()
    sent_any = False
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for addr in targets:
            for port in (9, 7):
                try:
                    sock.sendto(packet, (addr, port))
                    sent_any = True
                except OSError:
                    pass
    if sent_any:
        return True, f"Đã gửi tín hiệu bật máy (Wake-on-LAN) tới MAC {mac_address}."
    return False, "Không gửi được gói tin Wake-on-LAN trên mạng hiện tại."
