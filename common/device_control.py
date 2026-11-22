"""Điều khiển thiết bị ngoại vi trên Windows: Tắt/Mở tiếng loa & Khóa/Mở cổng USB lưu trữ."""

import ctypes
import sys
from ctypes import wintypes

if sys.platform == "win32":
    import winreg


def is_admin() -> bool:
    """Kiểm tra ứng dụng có đang chạy với quyền Quản trị viên (Administrator) không."""
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def set_usb_storage_blocked(blocked: bool) -> tuple[bool, str]:
    """Khóa hoặc mở thiết bị lưu trữ USB (USBSTOR) trong Registry Windows."""
    if sys.platform != "win32":
        return False, "Chỉ hỗ trợ quản lý cổng USB trên Windows."
    key_path = r"SYSTEM\CurrentControlSet\Services\USBSTOR"
    value = 4 if blocked else 3
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, "Start", 0, winreg.REG_DWORD, value)
        state_msg = "Đã khóa các thiết bị lưu trữ USB mới." if blocked else "Đã mở lại cổng USB lưu trữ."
        return True, state_msg
    except PermissionError:
        return (
            False,
            "Cần chạy Máy Học Sinh với quyền Quản trị viên (Administrator) để khóa/mở cổng USB.",
        )
    except OSError as exc:
        return False, f"Không thể thay đổi trạng thái cổng USB: {exc}"


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_str(cls, s: str) -> "_GUID":
        import uuid

        u = uuid.UUID(s)
        d4 = (ctypes.c_ubyte * 8)(*u.bytes[8:])
        return cls(u.time_low, u.time_mid, u.time_hi_version, d4)


_CLSID_MMDeviceEnumerator = _GUID.from_str("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
_IID_IMMDeviceEnumerator = _GUID.from_str("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
_IID_IAudioEndpointVolume = _GUID.from_str("{5CDF2C82-841E-4546-9722-0CF74078229A}")


def _vtable_fn(ptr: ctypes.c_void_p, index: int, restype, *argtypes):
    vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn_type = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return fn_type(vtable[index])


def set_system_audio_muted(muted: bool) -> tuple[bool, str]:
    """Tắt hoặc mở tiếng âm thanh hệ thống qua Windows CoreAudio API."""
    if sys.platform != "win32":
        return False, "Chỉ hỗ trợ điều khiển âm thanh trên Windows."

    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    enum_ptr = ctypes.c_void_p()
    dev_ptr = ctypes.c_void_p()
    vol_ptr = ctypes.c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(_CLSID_MMDeviceEnumerator),
            None,
            1,  # CLSCTX_INPROC_SERVER
            ctypes.byref(_IID_IMMDeviceEnumerator),
            ctypes.byref(enum_ptr),
        )
        if hr != 0 or not enum_ptr.value:
            return False, "Không khởi tạo được bộ điều khiển âm thanh Windows."

        get_default = _vtable_fn(
            enum_ptr, 4, ctypes.c_long, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)
        )
        if get_default(enum_ptr, 0, 0, ctypes.byref(dev_ptr)) != 0 or not dev_ptr.value:
            return False, "Không tìm thấy thiết bị loa/âm thanh mặc định."

        activate = _vtable_fn(
            dev_ptr,
            3,
            ctypes.c_long,
            ctypes.POINTER(_GUID),
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        if (
            activate(
                dev_ptr, ctypes.byref(_IID_IAudioEndpointVolume), 1, None, ctypes.byref(vol_ptr)
            )
            != 0
            or not vol_ptr.value
        ):
            return False, "Không truy cập được âm lượng hệ thống."

        set_mute = _vtable_fn(
            vol_ptr, 14, ctypes.c_long, wintypes.BOOL, ctypes.c_void_p
        )
        res = set_mute(vol_ptr, 1 if muted else 0, None)
        if res != 0:
            return False, f"Lỗi khi đặt trạng thái âm thanh (mã {res})."
        return True, "Đã tắt tiếng loa máy tính." if muted else "Đã mở lại tiếng loa máy tính."
    except Exception as exc:
        return False, f"Không thể điều khiển âm thanh: {exc}"
    finally:
        for p in (vol_ptr, dev_ptr, enum_ptr):
            if p.value:
                try:
                    release = _vtable_fn(p, 2, ctypes.c_ulong)
                    release(p)
                except Exception:
                    pass
        ole32.CoUninitialize()
