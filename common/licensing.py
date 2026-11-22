"""Quản lý bản quyền phần mềm Phòng Tin Học VN theo Mã máy (Hardware ID) và chữ ký số Ed25519."""

import base64
import ctypes
import hashlib
import json
import socket
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from common.license_pubkey import PUBLIC_KEY_RAW
from common.network import get_app_data_dir

if sys.platform == "win32":
    import winreg


@dataclass
class LicenseInfo:
    """Thông tin chi tiết trong một giấy phép bản quyền hợp lệ."""

    hwid: str
    owner: str
    max_students: int
    expires_at: str  # "VINH_VIEN" hoặc "YYYY-MM-DD"
    issued_at: str


def _b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    pad = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode((text + pad).encode("ascii"))


def _read_reg_str(root: int, subkey: str, value_name: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, value_name)
            return str(val).strip()
    except OSError:
        return ""


def _get_system_volume_serial() -> str:
    if sys.platform != "win32":
        return ""
    try:
        serial = ctypes.c_uint32(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            "C:\\",
            None,
            0,
            ctypes.byref(serial),
            None,
            None,
            None,
            0,
        )
        return f"{serial.value:08X}" if ok else ""
    except Exception:
        return ""


def get_hardware_id() -> str:
    """Tạo Mã máy (Hardware ID) duy nhất cho máy tính hiện tại dạng PTH-XXXX-XXXX-XXXX."""
    parts = [
        _read_reg_str(
            winreg.HKEY_LOCAL_MACHINE if sys.platform == "win32" else 0,
            r"SOFTWARE\Microsoft\Cryptography",
            "MachineGuid",
        ),
        _read_reg_str(
            winreg.HKEY_LOCAL_MACHINE if sys.platform == "win32" else 0,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            "ProductId",
        ),
        _get_system_volume_serial(),
        socket.gethostname(),
        str(uuid.getnode()),
    ]
    raw = "|".join(p for p in parts if p)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    return f"PTH-{digest[0:4]}-{digest[4:8]}-{digest[8:12]}"


def verify_license_key(
    key_str: str,
    expected_hwid: str | None = None,
    public_key_raw: bytes = PUBLIC_KEY_RAW,
    today: date | None = None,
) -> tuple[bool, LicenseInfo | None, str]:
    """Xác minh chữ ký Ed25519, mã máy và thời hạn của Mã bản quyền."""
    cleaned = "".join(key_str.strip().split())
    if not cleaned:
        return False, None, "Chưa nhập mã bản quyền."

    segments = cleaned.split(".")
    if len(segments) != 3 or segments[0] != "PTH1":
        return False, None, "Định dạng mã bản quyền không hợp lệ (phải bắt đầu bằng PTH1.)."

    try:
        payload_bytes = _b64u_decode(segments[1])
        sig_bytes = _b64u_decode(segments[2])
        payload: dict[str, Any] = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return False, None, "Không thể đọc dữ liệu từ mã bản quyền."

    try:
        pub = Ed25519PublicKey.from_public_bytes(public_key_raw)
        pub.verify(sig_bytes, payload_bytes)
    except InvalidSignature:
        return False, None, "Chữ ký bản quyền không hợp lệ hoặc mã đã bị chỉnh sửa."
    except Exception as exc:
        return False, None, f"Lỗi xác minh bản quyền: {exc}"

    hwid_target = (expected_hwid or get_hardware_id()).strip().upper()
    key_hwid = str(payload.get("hwid") or "").strip().upper()
    if not key_hwid or key_hwid != hwid_target:
        return (
            False,
            None,
            f"Mã bản quyền này chỉ dành cho máy {key_hwid or 'khác'}, không khớp với máy hiện tại ({hwid_target}).",
        )

    expires_at = str(payload.get("expires_at") or "").strip()
    if expires_at != "VINH_VIEN":
        try:
            exp_date = date.fromisoformat(expires_at)
        except ValueError:
            return False, None, "Thông tin ngày hết hạn trong mã bản quyền không hợp lệ."
        ref_day = today or date.today()
        if ref_day > exp_date:
            return False, None, f"Mã bản quyền đã hết hạn vào ngày {expires_at}."

    owner = str(payload.get("owner") or "Đơn vị được cấp phép").strip()
    max_students = max(1, int(payload.get("max_students") or 40))
    issued_at = str(payload.get("issued_at") or "")
    info = LicenseInfo(
        hwid=key_hwid,
        owner=owner,
        max_students=max_students,
        expires_at=expires_at,
        issued_at=issued_at,
    )
    exp_label = "Vĩnh viễn" if expires_at == "VINH_VIEN" else f"đến {expires_at}"
    return True, info, f"Bản quyền hợp lệ — {owner} (Tối đa {max_students} máy, {exp_label})."


def _license_file(state_dir: Path | None = None) -> Path:
    root = state_dir or get_app_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / "license.key"


def load_saved_license(state_dir: Path | None = None) -> str:
    path = _license_file(state_dir)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_license_key(key_str: str, state_dir: Path | None = None) -> Path:
    path = _license_file(state_dir)
    path.write_text("".join(key_str.strip().split()), encoding="utf-8")
    return path


def check_active_license(
    state_dir: Path | None = None,
    expected_hwid: str | None = None,
) -> tuple[bool, LicenseInfo | None, str]:
    """Kiểm tra bản quyền đã lưu trên máy hiện tại."""
    saved = load_saved_license(state_dir)
    if not saved:
        return False, None, "Phần mềm chưa được kích hoạt bản quyền trên máy này."
    return verify_license_key(saved, expected_hwid=expected_hwid)
