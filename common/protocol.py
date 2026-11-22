"""Định nghĩa giao thức truyền thông JSON và nhị phân giữa Giáo viên và Học sinh."""

import json
import struct
from typing import Any

from common.config import (
    BIN_FILE_TRANSFER,
    BIN_STUDENT_SCREEN,
    BIN_TEACHER_AUDIO,
    BIN_TEACHER_BROADCAST,
)


def encode_msg(msg_type: str, **payload: Any) -> str:
    """Đóng gói thông điệp điều khiển thành chuỗi JSON."""
    data = {"type": msg_type, **payload}
    return json.dumps(data, ensure_ascii=False)


def decode_msg(raw: str) -> dict[str, Any]:
    """Giải mã thông điệp điều khiển từ chuỗi JSON."""
    obj = json.loads(raw)
    if not isinstance(obj, dict) or "type" not in obj:
        raise ValueError("Gói tin điều khiển không hợp lệ")
    return obj


def pack_screen_frame(frame_kind: int, jpeg_bytes: bytes) -> bytes:
    """Đóng gói khung hình JPEG (hoặc âm thanh) kèm 1 byte định danh."""
    if frame_kind not in (BIN_STUDENT_SCREEN, BIN_TEACHER_BROADCAST, BIN_TEACHER_AUDIO):
        raise ValueError(f"Loại khung hình không hợp lệ: {frame_kind}")
    return bytes((frame_kind,)) + jpeg_bytes


def pack_file_packet(header: dict[str, Any], chunk: bytes = b"") -> bytes:
    """Đóng gói mảnh dữ liệu tệp tin: [1B kind][4B header_len][JSON][bytes]."""
    header_bytes = json.dumps(header, ensure_ascii=False).encode("utf-8")
    return (
        bytes((BIN_FILE_TRANSFER,))
        + struct.pack(">I", len(header_bytes))
        + header_bytes
        + chunk
    )


def unpack_binary_packet(data: bytes) -> tuple[int, dict[str, Any] | None, bytes]:
    """Giải mã gói nhị phân thành (loại_gói, header_tệp_hoặc_None, dữ_liệu)."""
    if not data:
        raise ValueError("Gói nhị phân rỗng")
    kind = data[0]
    if kind in (BIN_STUDENT_SCREEN, BIN_TEACHER_BROADCAST, BIN_TEACHER_AUDIO):
        return kind, None, data[1:]
    if kind == BIN_FILE_TRANSFER:
        if len(data) < 5:
            raise ValueError("Gói truyền tệp bị thiếu phần đầu")
        (header_len,) = struct.unpack(">I", data[1:5])
        end = 5 + header_len
        if len(data) < end:
            raise ValueError("Độ dài phần đầu tệp không khớp")
        header = json.loads(data[5:end].decode("utf-8"))
        return kind, header, data[end:]
    raise ValueError(f"Mã gói nhị phân không xác định: {kind}")
