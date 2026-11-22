"""Thu và phát âm thanh trực tiếp qua mạng LAN (Micro Giáo viên -> Loa Học sinh)."""

import queue
import threading
from typing import Callable

import sounddevice as sd

from common.config import AUDIO_BLOCK_FRAMES, AUDIO_CHANNELS, AUDIO_SAMPLE_RATE


class AudioSender:
    """Thu âm từ micro máy Giáo viên và gửi từng đoạn PCM nhỏ."""

    def __init__(self, on_chunk: Callable[[bytes], None]) -> None:
        self._on_chunk = on_chunk
        self._stream: sd.RawInputStream | None = None
        self._lock = threading.Lock()

    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self._stream is not None:
                return True, "Đang truyền âm thanh."
            try:
                self._stream = sd.RawInputStream(
                    samplerate=AUDIO_SAMPLE_RATE,
                    channels=AUDIO_CHANNELS,
                    dtype="int16",
                    blocksize=AUDIO_BLOCK_FRAMES,
                    callback=self._callback,
                )
                self._stream.start()
                return True, "Đã bật truyền âm thanh từ micro."
            except Exception as exc:
                self._stream = None
                return False, f"Không mở được micro trên máy Giáo viên: {exc}"

    def _callback(self, indata, _frames, _time_info, _status) -> None:
        try:
            self._on_chunk(bytes(indata))
        except Exception:
            pass

    def stop(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None


class AudioReceiver:
    """Nhận và phát âm thanh từ Giáo viên ra loa/tai nghe Học sinh."""

    def __init__(self) -> None:
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=20)
        self._stream: sd.RawOutputStream | None = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        with self._lock:
            if self._stream is not None:
                return True
            self._clear_queue()
            try:
                self._stream = sd.RawOutputStream(
                    samplerate=AUDIO_SAMPLE_RATE,
                    channels=AUDIO_CHANNELS,
                    dtype="int16",
                    blocksize=AUDIO_BLOCK_FRAMES,
                    callback=self._callback,
                )
                self._stream.start()
                return True
            except Exception:
                self._stream = None
                return False

    def push(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes or self._stream is None:
            return
        while self._queue.full():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        try:
            self._queue.put_nowait(pcm_bytes)
        except queue.Full:
            pass

    def _callback(self, outdata, frames, _time_info, _status) -> None:
        needed = frames * AUDIO_CHANNELS * 2
        try:
            chunk = self._queue.get_nowait()
        except queue.Empty:
            outdata[:] = b"\x00" * needed
            return
        if len(chunk) >= needed:
            outdata[:] = chunk[:needed]
        else:
            outdata[: len(chunk)] = chunk
            outdata[len(chunk) :] = b"\x00" * (needed - len(chunk))

    def _clear_queue(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def stop(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self._clear_queue()
