"""Lưu trữ cấu hình lớp học, mật khẩu giáo viên và danh sách máy đã biết."""

import hashlib
import json
from pathlib import Path
from typing import Any

from common.config import (
    DEFAULT_ROOM_CODE,
    DEFAULT_TEACHER_NAME,
    DEFAULT_TEACHER_PASSWORD,
    DEFAULT_UPDATE_MANIFEST_URL,
)
from common.network import get_app_data_dir


def hash_password(password: str) -> str:
    """Băm mật khẩu bằng SHA-256."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain: str, expected_hash: str) -> bool:
    """Kiểm tra mật khẩu nhập vào có khớp với mã băm đã lưu không."""
    return hash_password(plain) == expected_hash


def _teacher_file(base_dir: Path | None = None) -> Path:
    root = base_dir or get_app_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / "teacher_state.json"


def _student_file(base_dir: Path | None = None) -> Path:
    root = base_dir or get_app_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / "student_state.json"


def load_teacher_state(base_dir: Path | None = None) -> dict[str, Any]:
    """Đọc cấu hình Giáo viên và danh sách máy đã lưu (cho sơ đồ & Wake-on-LAN)."""
    path = _teacher_file(base_dir)
    default_data: dict[str, Any] = {
        "room_code": DEFAULT_ROOM_CODE,
        "teacher_name": DEFAULT_TEACHER_NAME,
        "password_hash": hash_password(DEFAULT_TEACHER_PASSWORD),
        "update_url": DEFAULT_UPDATE_MANIFEST_URL,
        "auto_check_update": True,
        "known_pcs": {},
        "policy": {
            "blocked_apps": [],
            "web_mode": "allow_all",
            "web_domains": [],
        },
    }
    if not path.is_file():
        return default_data
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            default_data.update(loaded)
    except (OSError, json.JSONDecodeError):
        pass
    return default_data


def save_teacher_state(state: dict[str, Any], base_dir: Path | None = None) -> None:
    """Lưu cấu hình Giáo viên và danh sách máy trạm."""
    path = _teacher_file(base_dir)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_student_state(base_dir: Path | None = None) -> dict[str, Any]:
    """Đọc cấu hình đã lưu trên Máy Học Sinh."""
    path = _student_file(base_dir)
    default_data: dict[str, Any] = {
        "student_name": "",
        "target_room": "",
        "manual_host": "",
        "password_hash": hash_password(DEFAULT_TEACHER_PASSWORD),
    }
    if not path.is_file():
        return default_data
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            default_data.update(loaded)
    except (OSError, json.JSONDecodeError):
        pass
    return default_data


def save_student_state(state: dict[str, Any], base_dir: Path | None = None) -> None:
    """Lưu cấu hình Học sinh."""
    path = _student_file(base_dir)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
