"""Chính sách chặn ứng dụng (game) và kiểm soát trang web trên máy Học sinh."""

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass, field

BROWSER_KEYWORDS = (
    "chrome",
    "edge",
    "firefox",
    "cốc cốc",
    "coc coc",
    "opera",
    "brave",
)

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_TERMINATE = 0x0001
WM_CLOSE = 0x0010


@dataclass
class ClassroomPolicy:
    """Quy tắc kiểm soát ứng dụng và trang web do Giáo viên gửi xuống."""

    blocked_apps: list[str] = field(default_factory=list)
    web_mode: str = "allow_all"  # "allow_all" | "block_list" | "allow_only"
    web_domains: list[str] = field(default_factory=list)


def normalize_terms(items: list[str]) -> list[str]:
    """Chuẩn hóa danh sách từ khóa ứng dụng / tên miền."""
    out: list[str] = []
    for raw in items:
        clean = raw.strip().lower()
        if clean and clean not in out:
            out.append(clean)
    return out


def match_blocked_app(proc_name: str, blocked_terms: list[str]) -> bool:
    """Kiểm tra tên tiến trình có khớp danh sách ứng dụng bị chặn không."""
    name = proc_name.strip().lower()
    if not name or name in ("phongtinhocvn.exe", "ntq remote.exe", "python.exe", "pythonw.exe"):
        return False
    stem = name[:-4] if name.endswith(".exe") else name
    for term in blocked_terms:
        t = term[:-4] if term.endswith(".exe") else term
        if t and (t == stem or t in stem):
            return True
    return False


def match_web_title_allowed(
    window_title: str, web_mode: str, web_domains: list[str]
) -> bool:
    """Kiểm tra tiêu đề cửa sổ trình duyệt có hợp lệ theo chính sách web không."""
    if web_mode == "allow_all" or not web_domains:
        return True
    title_low = window_title.strip().lower()
    if not title_low:
        return True
    if not any(b in title_low for b in BROWSER_KEYWORDS):
        return True
    # Bỏ qua tab trống / trang mới
    if any(
        neutral in title_low
        for neutral in ("new tab", "thẻ mới", "tab mới", "about:blank", "cài đặt")
    ):
        return True

    terms = normalize_terms(web_domains)
    matched = any(term in title_low for term in terms)
    if web_mode == "block_list":
        return not matched
    if web_mode == "allow_only":
        return matched
    return True


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def enforce_blocked_apps(blocked_apps: list[str]) -> list[str]:
    """Đóng các ứng dụng đang chạy nằm trong danh sách bị chặn trên Windows."""
    if sys.platform != "win32":
        return []
    terms = normalize_terms(blocked_apps)
    if not terms:
        return []

    kernel32 = ctypes.windll.kernel32
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == wintypes.HANDLE(-1).value:
        return []

    killed: list[str] = []
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
    try:
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            exe_name = entry.szExeFile
            if match_blocked_app(exe_name, terms):
                proc = kernel32.OpenProcess(PROCESS_TERMINATE, False, entry.th32ProcessID)
                if proc:
                    try:
                        if kernel32.TerminateProcess(proc, 1):
                            killed.append(exe_name)
                    finally:
                        kernel32.CloseHandle(proc)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return killed


def enforce_web_policy(web_mode: str, web_domains: list[str]) -> list[str]:
    """Đóng cửa sổ trình duyệt đang mở trang web vi phạm quy định lớp học."""
    if sys.platform != "win32" or web_mode == "allow_all" or not web_domains:
        return []

    user32 = ctypes.windll.user32
    closed_titles: list[str] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _enum_cb(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if "phòng tin học" in title.lower():
            return True
        if not match_web_title_allowed(title, web_mode, web_domains):
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            closed_titles.append(title)
        return True

    user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
    return closed_titles
