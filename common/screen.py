"""Chụp màn hình tối ưu và xử lý điều khiển chuột/bàn phím từ xa."""

import contextlib
import io
import threading
from typing import Any

import mss
from mss.exception import ScreenShotError
from PIL import Image, ImageDraw
from pynput.keyboard import Controller as KeyController
from pynput.keyboard import Key
from pynput.mouse import Button
from pynput.mouse import Controller as MouseController


def get_primary_screen_size() -> tuple[int, int]:
    """Lấy kích thước màn hình chính (chiều rộng, chiều cao)."""
    with mss.MSS() as sct:
        mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
        return int(mon["width"]), int(mon["height"])


class ScreenCapturer:
    """Bộ chụp màn hình an toàn theo từng luồng, tự fallback khi Windows khóa màn hình."""

    def __init__(self) -> None:
        self._tls = threading.local()

    def _get_sct(self) -> mss.MSS:
        sct = getattr(self._tls, "sct", None)
        if sct is None:
            sct = mss.MSS()
            self._tls.sct = sct
        return sct

    def close(self) -> None:
        sct = getattr(self._tls, "sct", None)
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass
            self._tls.sct = None

    def capture_jpeg(self, max_width: int, max_height: int, quality: int) -> bytes:
        """Chụp màn hình chính, thu nhỏ theo tỷ lệ và nén JPEG."""
        try:
            sct = self._get_sct()
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            raw = sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            if img.width > max_width or img.height > max_height:
                img.thumbnail((max_width, max_height), Image.Resampling.BILINEAR)
        except (ScreenShotError, OSError):
            img = self._placeholder_image(max_width, max_height)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=False)
        return buf.getvalue()

    @staticmethod
    def _placeholder_image(width: int, height: int) -> Image.Image:
        w = max(240, width)
        h = max(135, height)
        img = Image.new("RGB", (w, h), color=(30, 41, 59))
        draw = ImageDraw.Draw(img)
        draw.text(
            (16, h // 2 - 10),
            "Man hinh tam khoa (Windows / UAC)",
            fill=(203, 213, 225),
        )
        return img


_SPECIAL_KEYS: dict[str, Key] = {
    "enter": Key.enter,
    "return": Key.enter,
    "backspace": Key.backspace,
    "tab": Key.tab,
    "escape": Key.esc,
    "esc": Key.esc,
    "space": Key.space,
    "delete": Key.delete,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
    "shift": Key.shift,
    "ctrl": Key.ctrl,
    "alt": Key.alt,
    "caps_lock": Key.caps_lock,
    "f1": Key.f1,
    "f2": Key.f2,
    "f3": Key.f3,
    "f4": Key.f4,
    "f5": Key.f5,
    "f6": Key.f6,
    "f7": Key.f7,
    "f8": Key.f8,
    "f9": Key.f9,
    "f10": Key.f10,
    "f11": Key.f11,
    "f12": Key.f12,
}


class RemoteInputController:
    """Thực thi thao tác chuột và bàn phím nhận từ máy Giáo viên."""

    def __init__(self) -> None:
        self._mouse = MouseController()
        self._keyboard = KeyController()

    def apply(self, payload: dict[str, Any]) -> None:
        action = payload.get("action", "")
        if action in ("move", "click", "dblclick", "rclick", "down", "up", "scroll"):
            w, h = get_primary_screen_size()
            x_norm = max(0.0, min(1.0, float(payload.get("x", 0.0))))
            y_norm = max(0.0, min(1.0, float(payload.get("y", 0.0))))
            px = int(x_norm * max(1, w - 1))
            py = int(y_norm * max(1, h - 1))
            self._mouse.position = (px, py)

            btn_name = payload.get("button", "left")
            btn = Button.right if btn_name == "right" else Button.left

            if action == "click":
                self._mouse.click(btn, 1)
            elif action == "dblclick":
                self._mouse.click(btn, 2)
            elif action == "rclick":
                self._mouse.click(Button.right, 1)
            elif action == "down":
                self._mouse.press(btn)
            elif action == "up":
                self._mouse.release(btn)
            elif action == "scroll":
                dy = int(payload.get("dy", 0))
                self._mouse.scroll(0, dy)
        elif action == "key":
            key_name = str(payload.get("key", ""))
            text = str(payload.get("text", ""))
            modifiers = [str(m).lower() for m in payload.get("modifiers", [])]
            mod_keys = [_SPECIAL_KEYS[m] for m in modifiers if m in _SPECIAL_KEYS]

            special = _SPECIAL_KEYS.get(key_name.lower())
            with contextlib.ExitStack() as stack:
                for mk in mod_keys:
                    stack.enter_context(self._keyboard.pressed(mk))
                if special is not None:
                    self._keyboard.press(special)
                    self._keyboard.release(special)
                elif key_name and len(key_name) == 1:
                    ch = key_name.lower()
                    self._keyboard.press(ch)
                    self._keyboard.release(ch)
                elif text:
                    self._keyboard.type(text)
