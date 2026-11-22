"""Chặn phím tắt hệ thống (Win, Alt+Tab, Alt+F4, Ctrl+Esc) khi khóa máy học sinh."""

import ctypes
import sys
import threading
from ctypes import wintypes

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_QUIT = 0x0012

VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_F4 = 0x73
VK_CONTROL = 0x11
LLKHF_ALTDOWN = 0x20


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KeyboardBlocker:
    """Chặn phím hệ thống ở mức low-level trên Windows khi màn hình bị khóa."""

    def __init__(self) -> None:
        self._active = False
        self._thread: threading.Thread | None = None
        self._thread_id: int = 0
        self._hook = None
        self._hook_proc = None
        self._lock = threading.Lock()

    def is_active(self) -> bool:
        return self._active

    def start(self) -> None:
        if sys.platform != "win32":
            return
        with self._lock:
            if self._active:
                return
            self._active = True
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            tid = self._thread_id
        if sys.platform == "win32" and tid:
            ctypes.windll.user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()

        LRESULT = ctypes.c_ssize_t
        HOOKPROC = ctypes.WINFUNCTYPE(
            LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )

        user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.CallNextHookEx.restype = LRESULT
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            HOOKPROC,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL

        def _low_level_proc(n_code: int, w_param: int, l_param: int) -> int:
            if n_code >= 0 and self._active and w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                kb = ctypes.cast(l_param, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                vk = kb.vkCode
                alt_down = bool(kb.flags & LLKHF_ALTDOWN)
                ctrl_down = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)

                if vk in (VK_LWIN, VK_RWIN):
                    return 1
                if alt_down and vk in (VK_TAB, VK_ESCAPE, VK_F4):
                    return 1
                if ctrl_down and vk == VK_ESCAPE:
                    return 1

            return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

        self._hook_proc = HOOKPROC(_low_level_proc)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc, 0, 0)
        if not self._hook:
            self._active = False
            return

        msg = wintypes.MSG()
        try:
            while self._active and user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None
            self._hook_proc = None
            self._thread_id = 0
