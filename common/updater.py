"""Hệ thống kiểm tra, tải và tự động cập nhật phiên bản mới (Online OTA & LAN)."""

import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Callable

from common.config import APP_VERSION
from common.network import get_app_data_dir


def get_update_dir(base_dir: Path | None = None) -> Path:
    """Trả về thư mục tạm chứa tệp cập nhật."""
    root = base_dir or get_app_data_dir()
    folder = root / "update"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def compute_sha256(file_path: Path) -> str:
    """Tính mã băm SHA-256 dạng hex chữ thường của một tệp."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest().lower()


def verify_sha256(file_path: Path, expected_sha256: str) -> bool:
    """Kiểm tra mã băm SHA-256 của tệp cập nhật."""
    if not expected_sha256 or not file_path.is_file():
        return False
    return compute_sha256(file_path) == expected_sha256.strip().lower()


def prepare_self_update_script(
    downloaded_exe: Path,
    target_exe: Path,
    launch_args: str = "--student",
    work_dir: Path | None = None,
) -> Path:
    """Tạo tệp batch thay thế NTQ Remote.exe sau khi ứng dụng đóng."""
    folder = work_dir or downloaded_exe.parent
    bat_path = folder / "apply_update.bat"
    content = (
        "@echo off\n"
        "ping 127.0.0.1 -n 3 > nul\n"
        "set /a tries=0\n"
        ":retry\n"
        f'copy /y "{downloaded_exe}" "{target_exe}" > nul 2>&1\n'
        "if errorlevel 1 (\n"
        "  set /a tries+=1\n"
        "  if %tries% lss 6 (\n"
        "    ping 127.0.0.1 -n 2 > nul\n"
        "    goto retry\n"
        "  )\n"
        "  exit /b 1\n"
        ")\n"
        f'del /f /q "{downloaded_exe}" > nul 2>&1\n'
        f'start "" "{target_exe}" {launch_args}\n'
        'del "%~f0" > nul 2>&1\n'
    )
    bat_path.write_text(content, encoding="utf-8")
    return bat_path


def launch_detached_updater(bat_path: Path) -> None:
    """Chạy script cập nhật ở chế độ ẩn không cửa sổ đen."""
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=creation_flags,
        close_fds=True,
    )


def parse_version(version_str: str) -> tuple[int, ...]:
    """Chuyển chuỗi phiên bản ('v2.1.0') thành tuple số nguyên để so sánh."""
    cleaned = str(version_str or "").strip().lstrip("vV")
    nums = [int(m) for m in re.findall(r"\d+", cleaned)]
    return tuple(nums) if nums else (0,)


def is_newer_version(remote_ver: str, current_ver: str = APP_VERSION) -> bool:
    """Trả về True nếu phiên bản từ xa mới hơn phiên bản hiện tại."""
    r_parts = parse_version(remote_ver)
    c_parts = parse_version(current_ver)
    max_len = max(len(r_parts), len(c_parts))
    r_pad = r_parts + (0,) * (max_len - len(r_parts))
    c_pad = c_parts + (0,) * (max_len - len(c_parts))
    return r_pad > c_pad


def _validate_http_url(url: str) -> str:
    clean = str(url or "").strip()
    parsed = urllib.parse.urlparse(clean)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise ValueError("Địa chỉ cập nhật phải bắt đầu bằng http:// hoặc https://")
    return clean


def make_ssl_context() -> ssl.SSLContext:
    """Tạo SSLContext ưu tiên bộ chứng chỉ certifi (tránh lỗi CA cũ trên Windows)."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch_update_manifest(
    manifest_url: str, timeout: float = 8.0
) -> dict[str, Any]:
    """Tải và kiểm tra tệp version.json mô tả phiên bản mới."""
    url = _validate_http_url(manifest_url)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"NTQ-Remote/{APP_VERSION}", "Accept": "application/json"},
    )
    ctx = make_ssl_context() if url.lower().startswith("https://") else None
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        raw = resp.read(256 * 1024).decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict) or not str(data.get("version") or "").strip():
        raise ValueError("Tệp version.json thiếu trường 'version' hợp lệ.")
    return data


def download_update_exe(
    download_url: str,
    expected_sha256: str = "",
    dest_dir: Path | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    timeout: float = 30.0,
) -> Path:
    """Tải tệp cài đặt EXE bản mới và kiểm tra SHA-256 (nếu có)."""
    url = _validate_http_url(download_url)
    target_dir = get_update_dir(dest_dir)
    part_path = target_dir / "NTQ_Remote_online_update.exe.part"
    final_path = target_dir / "NTQ_Remote_online_update.exe"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"NTQ-Remote/{APP_VERSION}"},
    )
    ctx = make_ssl_context() if url.lower().startswith("https://") else None
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            total_hdr = resp.headers.get("Content-Length")
            total_bytes = int(total_hdr) if total_hdr and total_hdr.isdigit() else 0
            downloaded = 0
            with open(part_path, "wb") as out:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(downloaded, total_bytes)
        os.replace(part_path, final_path)
    except Exception:
        part_path.unlink(missing_ok=True)
        raise

    if expected_sha256.strip() and not verify_sha256(final_path, expected_sha256):
        final_path.unlink(missing_ok=True)
        raise ValueError("Tệp tải về không khớp mã kiểm tra toàn vẹn SHA-256.")
    return final_path


def write_release_manifest(
    exe_path: Path,
    manifest_path: Path,
    version: str = APP_VERSION,
    download_url: str = "",
    notes: str = "",
) -> Path:
    """Tạo hoặc cập nhật tệp version.json kèm SHA-256 chính xác của tệp EXE vừa build."""
    existing: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            pass

    payload: dict[str, Any] = {
        "app_name": "NTQ Remote",
        "version": version,
        "sha256": compute_sha256(exe_path) if exe_path.is_file() else "",
        "file_size": exe_path.stat().st_size if exe_path.is_file() else 0,
        "download_url": download_url or str(existing.get("download_url") or ""),
        "notes": notes
        or str(
            existing.get("notes")
            or "Cập nhật NTQ Remote: tối ưu hiệu năng, tự động sửa lỗi và nâng cao ổn định."
        ),
        "released_at": date.today().isoformat(),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest_path


def sync_app_version_files(
    new_version: str, project_root: Path | None = None
) -> tuple[str, str]:
    """Đồng bộ số phiên bản vào common/config.py và version_info.txt."""
    clean = str(new_version or "").strip().lstrip("vV")
    parts = [int(x) for x in re.findall(r"\d+", clean)[:4]]
    if len(parts) < 3:
        raise ValueError("Số phiên bản phải có dạng X.Y.Z (VD: 2.1.0)")
    ver_3 = f"{parts[0]}.{parts[1]}.{parts[2]}"
    ver_4_tuple = f"({parts[0]}, {parts[1]}, {parts[2]}, {parts[3] if len(parts) > 3 else 0})"
    ver_4_str = f"{parts[0]}.{parts[1]}.{parts[2]}.{parts[3] if len(parts) > 3 else 0}"

    root = project_root or Path(__file__).resolve().parent.parent
    cfg_path = root / "common" / "config.py"
    if cfg_path.is_file():
        txt = cfg_path.read_text(encoding="utf-8")
        txt = re.sub(
            r'APP_VERSION\s*=\s*"[^"]*"',
            f'APP_VERSION = "{ver_3}"',
            txt,
            count=1,
        )
        cfg_path.write_text(txt, encoding="utf-8")

    vi_path = root / "version_info.txt"
    if vi_path.is_file():
        vtxt = vi_path.read_text(encoding="utf-8")
        vtxt = re.sub(r"filevers=\([^)]+\)", f"filevers={ver_4_tuple}", vtxt, count=1)
        vtxt = re.sub(r"prodvers=\([^)]+\)", f"prodvers={ver_4_tuple}", vtxt, count=1)
        vtxt = re.sub(
            r"StringStruct\('FileVersion',\s*'[^']*'\)",
            f"StringStruct('FileVersion', '{ver_4_str}')",
            vtxt,
            count=1,
        )
        vtxt = re.sub(
            r"StringStruct\('ProductVersion',\s*'[^']*'\)",
            f"StringStruct('ProductVersion', '{ver_4_str}')",
            vtxt,
            count=1,
        )
        vi_path.write_text(vtxt, encoding="utf-8")
    return ver_3, ver_4_str


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Công cụ quản lý phiên bản NTQ Remote")
    parser.add_argument("exe_path", nargs="?", help="Đường dẫn tệp EXE")
    parser.add_argument("manifest_path", nargs="?", help="Đường dẫn tệp version.json")
    parser.add_argument("--version", default=APP_VERSION, help="Số phiên bản (VD 2.1.0)")
    parser.add_argument("--download-url", default="", help="Liên kết tải trực tiếp EXE")
    parser.add_argument("--notes", default="", help="Ghi chú phát hành")
    parser.add_argument("--bump", default="", help="Đồng bộ số phiên bản trong mã nguồn")
    ns = parser.parse_args()

    if ns.bump:
        v3, v4 = sync_app_version_files(ns.bump)
        print(f"Updated APP_VERSION={v3} (FileVersion={v4})")
    elif ns.exe_path and ns.manifest_path:
        write_release_manifest(
            Path(ns.exe_path),
            Path(ns.manifest_path),
            version=str(ns.version).lstrip("vV") or APP_VERSION,
            download_url=ns.download_url,
            notes=ns.notes,
        )
