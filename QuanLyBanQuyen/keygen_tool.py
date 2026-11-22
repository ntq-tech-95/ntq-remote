"""Công cụ Cấp Mã Bản Quyền (chỉ dành cho Tác giả — không phân phối cho người dùng cuối)."""

import base64
import json
import sys
import tkinter as tk
from datetime import date, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.licensing import get_hardware_id  # noqa: E402


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def get_private_key_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "private_key.pem"
    return Path(__file__).resolve().parent / "private_key.pem"


def sign_license_key(
    hwid: str,
    owner: str,
    max_students: int,
    expires_at: str,
    private_key_path: Path | None = None,
) -> str:
    """Ký số tạo Mã bản quyền PTH1.<payload>.<signature> bằng private_key.pem."""
    pem_path = private_key_path or get_private_key_path()
    if not pem_path.is_file():
        raise FileNotFoundError(
            f"Không tìm thấy khóa bí mật ký bản quyền tại: {pem_path}"
        )
    priv = serialization.load_pem_private_key(pem_path.read_bytes(), password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        raise ValueError("Khóa bí mật không phải định dạng Ed25519.")

    payload = {
        "hwid": hwid.strip().upper(),
        "owner": owner.strip() or "Đơn vị được cấp phép",
        "max_students": max(1, int(max_students)),
        "expires_at": expires_at.strip(),
        "issued_at": date.today().isoformat(),
    }
    payload_bytes = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    sig_bytes = priv.sign(payload_bytes)
    return f"PTH1.{_b64u(payload_bytes)}.{_b64u(sig_bytes)}"


class KeygenApp:
    """Giao diện 100% Tiếng Việt để tác giả tạo Mã bản quyền cho từng phòng máy."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Công Cụ Cấp Bản Quyền — Phòng Tin Học VN (Dành cho Tác giả)")
        self.root.geometry("640x520")
        self.root.resizable(False, False)
        self._build_ui()

    def _build_ui(self) -> None:
        hdr = tk.Frame(self.root, bg="#0f172a", height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(
            hdr,
            text="🔐 CÔNG CỤ CẤP MÃ BẢN QUYỀN (CHỦ SỞ HỮU)",
            bg="#0f172a",
            fg="#ffffff",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", padx=16, pady=(12, 2))
        tk.Label(
            hdr,
            text="Lưu ý bảo mật: KHÔNG gửi tệp private_key.pem hoặc công cụ này cho khách hàng.",
            bg="#0f172a",
            fg="#fde68a",
            font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16)

        body = tk.Frame(self.root, padx=16, pady=12)
        body.pack(fill="both", expand=True)

        # Mã máy khách hàng
        tk.Label(body, text="1. Mã máy (Hardware ID) của máy Giáo viên:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        hw_row = tk.Frame(body)
        hw_row.pack(fill="x", pady=(2, 8))
        self.var_hwid = tk.StringVar(value=get_hardware_id())
        tk.Entry(hw_row, textvariable=self.var_hwid, font=("Consolas", 10)).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        tk.Button(
            hw_row,
            text="Lấy mã máy này",
            command=lambda: self.var_hwid.set(get_hardware_id()),
        ).pack(side="right")

        # Tên đơn vị
        tk.Label(body, text="2. Tên trường / Đơn vị được cấp phép:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.var_owner = tk.StringVar(value="Phòng Tin Học Chuẩn")
        tk.Entry(body, textvariable=self.var_owner, font=("Segoe UI", 10)).pack(
            fill="x", pady=(2, 8)
        )

        # Số máy & thời hạn
        opt_row = tk.Frame(body)
        opt_row.pack(fill="x", pady=(0, 10))
        tk.Label(opt_row, text="3. Số máy học sinh tối đa:", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.var_max = tk.StringVar(value="50")
        tk.Entry(opt_row, textvariable=self.var_max, width=8, font=("Segoe UI", 10)).pack(
            side="left", padx=(6, 18)
        )

        self.var_perm = tk.BooleanVar(value=True)
        tk.Checkbutton(
            opt_row,
            text="Bản quyền vĩnh viễn",
            variable=self.var_perm,
            command=self._toggle_expiry,
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")

        exp_row = tk.Frame(body)
        exp_row.pack(fill="x", pady=(0, 10))
        tk.Label(exp_row, text="Hoặc hết hạn vào ngày (YYYY-MM-DD):", font=("Segoe UI", 9)).pack(side="left")
        self.var_exp = tk.StringVar(value=(date.today() + timedelta(days=365)).isoformat())
        self.ent_exp = tk.Entry(exp_row, textvariable=self.var_exp, width=16, state="disabled")
        self.ent_exp.pack(side="left", padx=8)

        tk.Button(
            body,
            text="🔑 Tạo Mã Bản Quyền",
            bg="#2563eb",
            fg="#ffffff",
            font=("Segoe UI", 10, "bold"),
            pady=6,
            command=self._on_generate,
        ).pack(fill="x", pady=(2, 10))

        tk.Label(body, text="Mã bản quyền đã tạo (gửi mã này hoặc file .lic cho máy Giáo viên):", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.txt_key = tk.Text(body, height=5, font=("Consolas", 9), wrap="char")
        self.txt_key.pack(fill="both", expand=True, pady=(4, 8))

        btn_row = tk.Frame(body)
        btn_row.pack(fill="x")
        tk.Button(btn_row, text="📋 Copy Mã Bản Quyền", command=self._on_copy).pack(side="left")
        tk.Button(btn_row, text="💾 Lưu thành tệp .lic...", command=self._on_save).pack(side="left", padx=8)

    def _toggle_expiry(self) -> None:
        self.ent_exp.config(state="disabled" if self.var_perm.get() else "normal")

    def _on_generate(self) -> None:
        hwid = self.var_hwid.get().strip().upper()
        if not hwid.startswith("PTH-"):
            messagebox.showwarning("Mã máy không hợp lệ", "Mã máy phải có dạng PTH-XXXX-XXXX-XXXX.")
            return
        try:
            max_st = int(self.var_max.get().strip())
        except ValueError:
            messagebox.showwarning("Số máy không hợp lệ", "Vui lòng nhập số nguyên cho số máy tối đa.")
            return
        expires = "VINH_VIEN" if self.var_perm.get() else self.var_exp.get().strip()
        if expires != "VINH_VIEN":
            try:
                date.fromisoformat(expires)
            except ValueError:
                messagebox.showwarning("Ngày không hợp lệ", "Ngày hết hạn phải theo định dạng YYYY-MM-DD.")
                return
        try:
            key = sign_license_key(hwid, self.var_owner.get(), max_st, expires)
            self.txt_key.delete("1.0", "end")
            self.txt_key.insert("1.0", key)
        except Exception as exc:
            messagebox.showerror("Lỗi tạo mã", str(exc))

    def _on_copy(self) -> None:
        key = self.txt_key.get("1.0", "end").strip()
        if not key:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(key)
        messagebox.showinfo("Đã sao chép", "Đã sao chép Mã bản quyền vào bộ nhớ tạm.")

    def _on_save(self) -> None:
        key = self.txt_key.get("1.0", "end").strip()
        if not key:
            return
        hwid = self.var_hwid.get().strip().upper()
        path = filedialog.asksaveasfilename(
            title="Lưu tệp bản quyền",
            initialfile=f"BanQuyen_{hwid}.lic",
            defaultextension=".lic",
            filetypes=[("Tệp bản quyền (*.lic)", "*.lic")],
        )
        if path:
            Path(path).write_text(key, encoding="utf-8")
            messagebox.showinfo("Đã lưu", f"Đã lưu tệp bản quyền tại:\n{path}")

    def run(self) -> int:
        self.root.mainloop()
        return 0


if __name__ == "__main__":
    raise SystemExit(KeygenApp().run())
