"""Trình cài đặt đồ họa 100% Tiếng Việt cho phần mềm Phòng Tin Học VN."""

import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from common.autostart import (
    STUDENT_AUTOSTART_KEY,
    TEACHER_AUTOSTART_KEY,
    set_autostart,
)
from common.config import APP_VERSION


def get_payload_dir() -> Path:
    """Tìm thư mục chứa GiaoVien.exe và HocSinh.exe đi kèm."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "payload"
    return Path(__file__).resolve().parent.parent / "dist"


def default_install_dir() -> Path:
    """Chọn thư mục cài đặt mặc định hợp lý (ưu tiên ổ D nếu còn dung lượng)."""
    d_root = Path("D:\\")
    if d_root.exists():
        return d_root / "PhongTinHocVN_CaiDat"
    local_app = os.environ.get("LOCALAPPDATA")
    base = Path(local_app) if local_app else Path.home()
    return base / "PhongTinHocVN"


def _get_known_folder(csidl: int, fallback: Path) -> Path:
    """Lấy thư mục hệ thống chuẩn Windows (hỗ trợ cả Desktop trỏ qua OneDrive)."""
    if sys.platform != "win32":
        return fallback
    try:
        import ctypes
        from ctypes import wintypes

        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        hr = ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
        if hr == 0 and buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return fallback


def _get_desktop_dir() -> Path:
    return _get_known_folder(0x0010, Path.home() / "Desktop")


def _get_start_menu_programs_dir() -> Path:
    default_sm = (
        Path(os.environ.get("APPDATA", str(Path.home())))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
    )
    return _get_known_folder(0x0002, default_sm)


def _create_shortcut_com_unicode(
    target_exe: Path,
    shortcut_path: Path,
    description: str,
    arguments: str = "",
) -> None:
    """Tạo tệp .lnk bằng COM IShellLinkW + IPersistFile (hỗ trợ đầy đủ Unicode Tiếng Việt)."""
    import ctypes
    import uuid
    from ctypes import wintypes

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

        @classmethod
        def from_str(cls, val: str) -> "_GUID":
            u = uuid.UUID(val)
            g = cls()
            g.Data1, g.Data2, g.Data3 = u.fields[0], u.fields[1], u.fields[2]
            for idx, b in enumerate(u.bytes[8:]):
                g.Data4[idx] = b
            return g

    def _vcall(obj_ptr: ctypes.c_void_p, idx: int, restype, *args):
        vtbl = ctypes.cast(
            ctypes.cast(obj_ptr, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        argtypes = [a for a, _ in args]
        vals = [v for _, v in args]
        fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtbl[idx])
        return fn(obj_ptr, *vals)

    def _check_hr(hr: int, action: str) -> None:
        if hr < 0:
            raise OSError(f"{action} thất bại (HRESULT=0x{hr & 0xFFFFFFFF:08X})")

    clsid_shell_link = _GUID.from_str("{00021401-0000-0000-C000-000000000046}")
    iid_ishell_link_w = _GUID.from_str("{000214F9-0000-0000-C000-000000000046}")
    iid_ipersist_file = _GUID.from_str("{0000010B-0000-0000-C000-000000000046}")

    ole32 = ctypes.windll.ole32
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoCreateInstance.restype = ctypes.c_long
    hr_init = ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
    need_uninit = hr_init in (0, 1)  # S_OK or S_FALSE

    psl = ctypes.c_void_p()
    ppf = ctypes.c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid_shell_link),
            None,
            1,
            ctypes.byref(iid_ishell_link_w),
            ctypes.byref(psl),
        )
        _check_hr(hr, "CoCreateInstance(IShellLinkW)")
        _check_hr(
            _vcall(psl, 20, ctypes.c_long, (wintypes.LPCWSTR, str(target_exe))),
            "SetPath",
        )
        _check_hr(
            _vcall(psl, 9, ctypes.c_long, (wintypes.LPCWSTR, str(target_exe.parent))),
            "SetWorkingDirectory",
        )
        _check_hr(
            _vcall(psl, 7, ctypes.c_long, (wintypes.LPCWSTR, description)),
            "SetDescription",
        )
        if arguments:
            _check_hr(
                _vcall(psl, 11, ctypes.c_long, (wintypes.LPCWSTR, arguments)),
                "SetArguments",
            )
        if target_exe.suffix.lower() == ".exe":
            _vcall(
                psl,
                17,
                ctypes.c_long,
                (wintypes.LPCWSTR, str(target_exe)),
                (ctypes.c_int, 0),
            )
        _check_hr(
            _vcall(
                psl,
                0,
                ctypes.c_long,
                (ctypes.POINTER(_GUID), ctypes.byref(iid_ipersist_file)),
                (ctypes.POINTER(ctypes.c_void_p), ctypes.byref(ppf)),
            ),
            "QueryInterface(IPersistFile)",
        )
        _check_hr(
            _vcall(
                ppf,
                6,
                ctypes.c_long,
                (wintypes.LPCWSTR, str(shortcut_path)),
                (wintypes.BOOL, True),
            ),
            "IPersistFile.Save",
        )
    finally:
        if ppf.value:
            _vcall(ppf, 2, wintypes.ULONG)
        if psl.value:
            _vcall(psl, 2, wintypes.ULONG)
        if need_uninit:
            ole32.CoUninitialize()


def create_windows_shortcut(
    target_exe: Path,
    shortcut_path: Path,
    description: str,
    arguments: str = "",
) -> None:
    """Tạo lối tắt (.lnk) chuẩn Windows hỗ trợ đường dẫn & tên Tiếng Việt Unicode."""
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    _create_shortcut_com_unicode(target_exe, shortcut_path, description, arguments)


def try_add_firewall_rules(exe_paths: list[Path]) -> bool:
    """Thử thêm ngoại lệ tường lửa Windows (thành công nếu chạy với quyền Admin)."""
    if sys.platform != "win32":
        return False
    all_ok = True
    for exe in exe_paths:
        rule_name = f"PhongTinHocVN_{exe.stem}"
        cmd = [
            "netsh",
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={rule_name}",
            "dir=in",
            "action=allow",
            f"program={exe}",
            "enable=yes",
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if res.returncode != 0:
            all_ok = False
    return all_ok


def write_uninstaller_bat(
    install_dir: Path,
    desktop_links: list[Path],
    start_menu_dir: Path,
) -> Path:
    """Tạo tệp Go_Cai_Dat.bat để gỡ phần mềm sạch sẽ."""
    bat_path = install_dir / "Go_Cai_Dat.bat"
    del_shortcuts = "\n".join(
        f'if exist "{p}" del /f /q "{p}"' for p in desktop_links
    )
    content = (
        "@echo off\n"
        "chcp 65001 > nul\n"
        "echo ======================================================\n"
        "echo   GO CAI DAT PHAN MEM PHONG TIN HOC VN\n"
        "echo ======================================================\n"
        "taskkill /f /im GiaoVien.exe >nul 2>&1\n"
        "taskkill /f /im HocSinh.exe >nul 2>&1\n"
        "taskkill /f /im PhongTinHocVN.exe >nul 2>&1\n"
        'taskkill /f /im "NTQ Remote.exe" >nul 2>&1\n'
        f'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "{TEACHER_AUTOSTART_KEY}" /f >nul 2>&1\n'
        f'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "{STUDENT_AUTOSTART_KEY}" /f >nul 2>&1\n'
        f'schtasks /delete /tn "{TEACHER_AUTOSTART_KEY}" /f >nul 2>&1\n'
        f'schtasks /delete /tn "{STUDENT_AUTOSTART_KEY}" /f >nul 2>&1\n'
        f"{del_shortcuts}\n"
        f'if exist "{start_menu_dir}" rmdir /s /q "{start_menu_dir}"\n'
        "echo Da go bo loi tat va khoi dong cung Windows.\n"
        'echo Ban co the xoa thu muc nay neu muon: "%~dp0"\n'
        "pause\n"
    )
    bat_path.write_text(content, encoding="utf-8")
    return bat_path


def perform_install(
    role: str,
    install_dir: Path,
    make_desktop: bool,
    make_start_menu: bool,
    enable_autostart: bool,
    add_firewall: bool,
    log_cb: Callable[[str], None] | None = None,
    payload_dir: Path | None = None,
) -> list[Path]:
    """Thực thi sao chép tệp cài đặt, tạo lối tắt và cấu hình hệ thống."""
    def log(msg: str) -> None:
        if log_cb:
            log_cb(msg)

    src_dir = payload_dir or get_payload_dir()
    targets: list[tuple[str, str, str]] = []
    if role in ("teacher", "both"):
        targets.append(
            ("GiaoVien.exe", "Phòng Tin Học - Giáo Viên", TEACHER_AUTOSTART_KEY)
        )
    if role in ("student", "both"):
        targets.append(
            ("HocSinh.exe", "Phòng Tin Học - Học Sinh", STUDENT_AUTOSTART_KEY)
        )
    if not targets:
        raise ValueError("Vai trò cài đặt không hợp lệ.")

    for exe_name, _, _ in targets:
        if not (src_dir / exe_name).is_file():
            raise FileNotFoundError(f"Thiếu tệp nguồn cài đặt: {src_dir / exe_name}")

    install_dir.mkdir(parents=True, exist_ok=True)
    installed_exes: list[Path] = []
    desktop_links: list[Path] = []
    desktop_dir = _get_desktop_dir()
    start_menu_dir = _get_start_menu_programs_dir() / "Phòng Tin Học VN"

    for exe_name, shortcut_title, reg_key in targets:
        src_exe = src_dir / exe_name
        dst_exe = install_dir / exe_name
        log(f"Đang sao chép {exe_name} vào {install_dir}...")
        shutil.copy2(src_exe, dst_exe)
        installed_exes.append(dst_exe)

        if make_desktop and desktop_dir.exists():
            lnk = desktop_dir / f"{shortcut_title}.lnk"
            log(f"Đang tạo biểu tượng ngoài Desktop: {lnk.name}")
            create_windows_shortcut(dst_exe, lnk, shortcut_title)
            desktop_links.append(lnk)

        if make_start_menu:
            lnk = start_menu_dir / f"{shortcut_title}.lnk"
            log(f"Đang tạo lối tắt Start Menu: {shortcut_title}")
            create_windows_shortcut(dst_exe, lnk, shortcut_title)

        if enable_autostart:
            ok, msg = set_autostart(reg_key, True, f'"{dst_exe}"')
            log(f"Khởi động cùng Windows ({exe_name}): {msg}")

    uninst_bat = write_uninstaller_bat(install_dir, desktop_links, start_menu_dir)
    if make_start_menu:
        create_windows_shortcut(
            uninst_bat,
            start_menu_dir / "Gỡ cài đặt Phòng Tin Học VN.lnk",
            "Gỡ cài đặt Phòng Tin Học VN",
        )

    if add_firewall:
        fw_ok = try_add_firewall_rules(installed_exes)
        if fw_ok:
            log("Đã tự động mở cổng tường lửa Windows.")
        else:
            log("Lưu ý: Chưa có quyền Quản trị để tự mở tường lửa (khi mở lần đầu hãy bấm 'Allow').")

    log("Hoàn tất cài đặt!")
    return installed_exes


def try_register_scheduled_task(task_name: str, exe_path: Path, flag: str) -> bool:
    """Đăng ký chạy tự động với quyền cao nhất qua Windows Task Scheduler (cần quyền Admin)."""
    if sys.platform != "win32":
        return False
    cmd = [
        "schtasks",
        "/create",
        "/tn",
        task_name,
        "/tr",
        f'"{exe_path}" {flag}',
        "/sc",
        "ONLOGON",
        "/rl",
        "HIGHEST",
        "/f",
    ]
    res = subprocess.run(
        cmd,
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return res.returncode == 0


def perform_unified_install(
    role: str,
    install_dir: Path,
    make_desktop: bool,
    make_start_menu: bool,
    enable_autostart: bool,
    add_firewall: bool,
    source_exe: Path | None = None,
    log_cb: Callable[[str], None] | None = None,
    elevated_task: bool = False,
) -> list[tuple[Path, str]]:
    """Cài đặt từ 1 tệp NTQ Remote.exe duy nhất, trả về danh sách (exe, flag)."""
    def log(msg: str) -> None:
        if log_cb:
            log_cb(msg)

    src = source_exe or (
        Path(sys.executable).resolve()
        if getattr(sys, "frozen", False)
        else (Path(__file__).resolve().parent.parent / "BoCaiDat" / "NTQ Remote.exe")
    )
    if not src.is_file():
        raise FileNotFoundError(f"Không tìm thấy tệp ứng dụng: {src}")

    roles: list[tuple[str, str, str]] = []
    if role in ("teacher", "both"):
        roles.append(("--teacher", "Phòng Tin Học - Giáo Viên", TEACHER_AUTOSTART_KEY))
    if role in ("student", "both"):
        roles.append(("--student", "Phòng Tin Học - Học Sinh", STUDENT_AUTOSTART_KEY))
    if not roles:
        raise ValueError("Vai trò cài đặt không hợp lệ.")

    install_dir.mkdir(parents=True, exist_ok=True)
    dst_exe = install_dir / "NTQ Remote.exe"
    if src.resolve() != dst_exe.resolve():
        log(f"Đang sao chép NTQ Remote.exe vào {install_dir}...")
        shutil.copy2(src, dst_exe)

    desktop_links: list[Path] = []
    desktop_dir = _get_desktop_dir()
    start_menu_dir = _get_start_menu_programs_dir() / "Phòng Tin Học VN"

    launched: list[tuple[Path, str]] = []
    for flag, shortcut_title, reg_key in roles:
        launched.append((dst_exe, flag))
        if make_desktop and desktop_dir.exists():
            lnk = desktop_dir / f"{shortcut_title}.lnk"
            log(f"Đang tạo biểu tượng Desktop: {lnk.name}")
            create_windows_shortcut(dst_exe, lnk, shortcut_title, arguments=flag)
            desktop_links.append(lnk)

        if make_start_menu:
            lnk = start_menu_dir / f"{shortcut_title}.lnk"
            log(f"Đang tạo lối tắt Start Menu: {shortcut_title}")
            create_windows_shortcut(dst_exe, lnk, shortcut_title, arguments=flag)

        if enable_autostart:
            if elevated_task and try_register_scheduled_task(reg_key, dst_exe, flag):
                log(f"Đã tạo tác vụ hệ thống quyền cao ({shortcut_title}).")
            else:
                ok, msg = set_autostart(reg_key, True, f'"{dst_exe}" {flag}')
                log(f"Khởi động cùng Windows ({shortcut_title}): {msg}")

    uninst_bat = write_uninstaller_bat(install_dir, desktop_links, start_menu_dir)
    if make_start_menu:
        create_windows_shortcut(
            uninst_bat,
            start_menu_dir / "Gỡ cài đặt Phòng Tin Học VN.lnk",
            "Gỡ cài đặt Phòng Tin Học VN",
        )

    if add_firewall:
        fw_ok = try_add_firewall_rules([dst_exe])
        if fw_ok:
            log("Đã tự động mở cổng tường lửa Windows.")
        else:
            log("Lưu ý: Chưa có quyền Quản trị để tự mở tường lửa (khi mở lần đầu hãy bấm 'Allow').")

    log("Hoàn tất cài đặt!")
    return launched


class SetupWizardApp:
    """Giao diện Trình cài đặt 100% Tiếng Việt."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"Cài đặt Phòng Tin Học VN (v{APP_VERSION})")
        self.root.geometry("620x520")
        self.root.resizable(False, False)
        self.installed_exes: list[Path] = []

        self._build_ui()

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg="#1e3a8a", height=72)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text="TRÌNH CÀI ĐẶT PHẦN MỀM PHÒNG TIN HỌC VN",
            bg="#1e3a8a",
            fg="#ffffff",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", padx=18, pady=(14, 2))
        tk.Label(
            header,
            text=f"Phiên bản {APP_VERSION} — Quản lý phòng máy 100% Tiếng Việt (Giáo viên & Học sinh)",
            bg="#1e3a8a",
            fg="#dbeafe",
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=18)

        body = tk.Frame(self.root, padx=18, pady=12)
        body.pack(fill="both", expand=True)

        # Bước 1: Chọn vai trò
        grp_role = tk.LabelFrame(body, text=" 1. Chọn loại máy cần cài đặt ", font=("Segoe UI", 10, "bold"), padx=10, pady=8)
        grp_role.pack(fill="x", pady=(0, 10))
        self.var_role = tk.StringVar(value="student")
        tk.Radiobutton(
            grp_role,
            text="Máy Học Sinh (cài đặt trên các máy trạm trong phòng thực hành)",
            variable=self.var_role,
            value="student",
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        tk.Radiobutton(
            grp_role,
            text="Máy Giáo Viên (cài đặt trên máy điều khiển của giáo viên)",
            variable=self.var_role,
            value="teacher",
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        tk.Radiobutton(
            grp_role,
            text="Cài cả hai (dùng để kiểm thử cả Giáo viên và Học sinh)",
            variable=self.var_role,
            value="both",
            font=("Segoe UI", 9),
        ).pack(anchor="w")

        # Bước 2: Thư mục cài đặt
        grp_dir = tk.LabelFrame(body, text=" 2. Thư mục cài đặt ", font=("Segoe UI", 10, "bold"), padx=10, pady=8)
        grp_dir.pack(fill="x", pady=(0, 10))
        dir_row = tk.Frame(grp_dir)
        dir_row.pack(fill="x")
        self.var_dir = tk.StringVar(value=str(default_install_dir()))
        tk.Entry(dir_row, textvariable=self.var_dir, font=("Segoe UI", 9)).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        tk.Button(
            dir_row,
            text="Chọn thư mục...",
            command=self._browse_dir,
            font=("Segoe UI", 9),
        ).pack(side="right")

        # Bước 3: Tùy chọn
        grp_opt = tk.LabelFrame(body, text=" 3. Tùy chọn thêm ", font=("Segoe UI", 10, "bold"), padx=10, pady=8)
        grp_opt.pack(fill="x", pady=(0, 10))
        self.var_desktop = tk.BooleanVar(value=True)
        self.var_start_menu = tk.BooleanVar(value=True)
        self.var_autostart = tk.BooleanVar(value=True)
        self.var_firewall = tk.BooleanVar(value=True)

        tk.Checkbutton(grp_opt, text="Tạo biểu tượng ngoài màn hình Desktop", variable=self.var_desktop, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Checkbutton(grp_opt, text="Tạo lối tắt trong Start Menu & bộ gỡ cài đặt", variable=self.var_start_menu, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Checkbutton(grp_opt, text="Tự động khởi động cùng Windows khi mở máy", variable=self.var_autostart, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Checkbutton(grp_opt, text="Tự động mở cổng tường lửa Windows (nếu có quyền Quản trị)", variable=self.var_firewall, font=("Segoe UI", 9)).pack(anchor="w")

        # Tiến trình
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill="x", pady=(4, 4))
        self.lbl_status = tk.Label(body, text="Sẵn sàng cài đặt.", anchor="w", fg="#334155", font=("Segoe UI", 9))
        self.lbl_status.pack(fill="x")

        # Nút điều khiển dưới cùng
        btn_row = tk.Frame(body, pady=10)
        btn_row.pack(fill="x")
        self.btn_install = tk.Button(
            btn_row,
            text="Cài đặt ngay",
            bg="#2563eb",
            fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            padx=16,
            pady=5,
            command=self._start_install,
        )
        self.btn_install.pack(side="left")

        self.btn_launch = tk.Button(
            btn_row,
            text="Mở phần mềm ngay",
            state="disabled",
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=5,
            command=self._launch_installed,
        )
        self.btn_launch.pack(side="left", padx=10)

        tk.Button(
            btn_row,
            text="Đóng",
            font=("Segoe UI", 9),
            padx=12,
            pady=5,
            command=self.root.destroy,
        ).pack(side="right")

    def _browse_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.var_dir.get(), title="Chọn thư mục cài đặt")
        if chosen:
            self.var_dir.set(chosen)

    def _start_install(self) -> None:
        target_dir = Path(self.var_dir.get().strip())
        if not str(target_dir):
            messagebox.showwarning("Thiếu thư mục", "Vui lòng chọn thư mục cài đặt.")
            return

        self.btn_install.config(state="disabled")
        self.progress.start(12)

        def _worker() -> None:
            try:
                exes = perform_install(
                    role=self.var_role.get(),
                    install_dir=target_dir,
                    make_desktop=self.var_desktop.get(),
                    make_start_menu=self.var_start_menu.get(),
                    enable_autostart=self.var_autostart.get(),
                    add_firewall=self.var_firewall.get(),
                    log_cb=lambda m: self.root.after(0, lambda msg=m: self.lbl_status.config(text=msg)),
                )
                self.root.after(0, lambda: self._on_success(exes))
            except Exception as exc:
                self.root.after(0, lambda e=exc: self._on_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_success(self, exes: list[Path]) -> None:
        self.progress.stop()
        self.installed_exes = exes
        self.btn_install.config(state="normal", text="Cài đặt lại")
        self.btn_launch.config(state="normal")
        messagebox.showinfo(
            "Cài đặt thành công",
            f"Đã cài đặt xong tại:\n{self.var_dir.get()}\n\nBạn có thể bấm 'Mở phần mềm ngay' hoặc mở từ biểu tượng ngoài Desktop.",
        )

    def _on_error(self, err: str) -> None:
        self.progress.stop()
        self.btn_install.config(state="normal")
        self.lbl_status.config(text=f"Lỗi cài đặt: {err}")
        messagebox.showerror("Lỗi cài đặt", f"Không thể hoàn tất cài đặt:\n{err}")

    def _launch_installed(self) -> None:
        for exe in self.installed_exes:
            if exe.is_file():
                subprocess.Popen([str(exe)], cwd=str(exe.parent))
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main() -> int:
    return SetupWizardApp().run()


if __name__ == "__main__":
    raise SystemExit(main())
