"""Ghi hình bài giảng thành tệp video AVI (Motion JPEG) không cần thư viện ngoài."""

import io
import struct
import threading
import time
from pathlib import Path

from PIL import Image

from common.screen import ScreenCapturer


def get_teacher_recordings_dir() -> Path:
    """Thư mục lưu video bài giảng đã quay trên máy Giáo viên."""
    desktop = Path.home() / "Desktop"
    base = desktop if desktop.exists() else Path.home()
    folder = base / "BaiGiangDaQuay"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class MjpegAviWriter:
    """Trình ghi video định dạng RIFF AVI (MJPG) chuẩn, tương thích Windows Media Player & VLC."""

    def __init__(self, path: Path, width: int, height: int, fps: int = 10) -> None:
        self.path = Path(path)
        self.width = width
        self.height = height
        self.fps = max(1, fps)
        self._fp = open(self.path, "wb")
        self._index: list[tuple[int, int]] = []
        self._frame_count = 0

        # Chừa chỗ cho phần đầu RIFF AVI (224 byte cố định)
        self._hdr_size = 224
        self._fp.write(b"\x00" * self._hdr_size)
        self._movi_list_pos = self._fp.tell()
        self._fp.write(b"LIST")
        self._movi_size_pos = self._fp.tell()
        self._fp.write(struct.pack("<I", 4))
        self._fp.write(b"movi")
        self._movi_data_start = self._fp.tell()

    def write_jpeg_frame(self, jpeg_bytes: bytes) -> None:
        """Ghi 1 khung hình JPEG vào luồng video."""
        offset_from_movi = self._fp.tell() - self._movi_data_start + 4
        size = len(jpeg_bytes)
        self._fp.write(b"00dc")
        self._fp.write(struct.pack("<I", size))
        self._fp.write(jpeg_bytes)
        if size % 2 == 1:
            self._fp.write(b"\x00")
        self._index.append((offset_from_movi, size))
        self._frame_count += 1

    def close(self) -> None:
        if self._fp.closed:
            return
        movi_end = self._fp.tell()
        movi_payload_size = movi_end - self._movi_list_pos - 8

        # Ghi chỉ mục idx1
        self._fp.write(b"idx1")
        self._fp.write(struct.pack("<I", len(self._index) * 16))
        for offset, size in self._index:
            self._fp.write(struct.pack("<4sIII", b"00dc", 0x10, offset, size))

        file_end = self._fp.tell()
        riff_size = file_end - 8

        # Cập nhật kích thước LIST movi
        self._fp.seek(self._movi_size_pos)
        self._fp.write(struct.pack("<I", movi_payload_size))

        # Ghi phần đầu RIFF AVI hoàn chỉnh
        us_per_frame = int(1_000_000 / self.fps)
        avih = struct.pack(
            "<IIIIIIIIIIIIII",
            us_per_frame,  # dwMicroSecPerFrame
            self.width * self.height * 3,  # dwMaxBytesPerSec
            0,  # dwPaddingGranularity
            0x10,  # dwFlags (AVIF_HASINDEX)
            self._frame_count,  # dwTotalFrames
            0,  # dwInitialFrames
            1,  # dwStreams
            1048576,  # dwSuggestedBufferSize
            self.width,
            self.height,
            0,
            0,
            0,
            0,
        )
        strh = struct.pack(
            "<4s4sIHHIIIIIIIIhhhh",
            b"vids",
            b"MJPG",
            0,
            0,
            0,
            0,
            1,
            self.fps,
            0,
            self._frame_count,
            1048576,
            0xFFFFFFFF,
            0,
            0,
            0,
            self.width,
            self.height,
        )
        strf = struct.pack(
            "<IIIHH4sIIIII",
            40,
            self.width,
            self.height,
            1,
            24,
            b"MJPG",
            self.width * self.height * 3,
            0,
            0,
            0,
            0,
        )

        strl_body = (
            b"strh" + struct.pack("<I", len(strh)) + strh + b"strf" + struct.pack("<I", len(strf)) + strf
        )
        strl_chunk = b"LIST" + struct.pack("<I", 4 + len(strl_body)) + b"strl" + strl_body
        hdrl_body = b"avih" + struct.pack("<I", len(avih)) + avih + strl_chunk
        hdrl_chunk = b"LIST" + struct.pack("<I", 4 + len(hdrl_body)) + b"hdrl" + hdrl_body
        header = b"RIFF" + struct.pack("<I", riff_size) + b"AVI " + hdrl_chunk

        assert len(header) <= self._hdr_size
        self._fp.seek(0)
        self._fp.write(header)
        if len(header) < self._hdr_size:
            junk_payload = self._hdr_size - len(header) - 8
            if junk_payload >= 0:
                self._fp.write(b"JUNK" + struct.pack("<I", junk_payload) + (b"\x00" * junk_payload))

        self._fp.close()


class ScreenRecorder:
    """Quay lại toàn bộ màn hình Giáo viên kèm chú thích viết bảng thành video AVI."""

    def __init__(self, width: int = 1280, height: int = 720, fps: int = 10) -> None:
        self.width = width
        self.height = height
        self.fps = fps
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.output_path: Path | None = None

    def is_recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, output_path: Path | None = None) -> Path:
        if self.is_recording() and self.output_path is not None:
            return self.output_path
        if output_path is None:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            output_path = get_teacher_recordings_dir() / f"BaiGiang_{stamp}.avi"
        self.output_path = output_path
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return output_path

    def stop(self) -> Path | None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=4.0)
            self._thread = None
        return self.output_path

    def _run(self) -> None:
        assert self.output_path is not None
        capturer = ScreenCapturer()
        writer = MjpegAviWriter(self.output_path, self.width, self.height, self.fps)
        interval = 1.0 / max(1, self.fps)
        try:
            while not self._stop_event.is_set():
                t0 = time.monotonic()
                raw_jpeg = capturer.capture_jpeg(self.width, self.height, 72)
                img = Image.open(io.BytesIO(raw_jpeg)).convert("RGB")
                if img.size != (self.width, self.height):
                    canvas = Image.new("RGB", (self.width, self.height), (0, 0, 0))
                    ox = (self.width - img.width) // 2
                    oy = (self.height - img.height) // 2
                    canvas.paste(img, (ox, oy))
                    buf = io.BytesIO()
                    canvas.save(buf, format="JPEG", quality=72)
                    frame_bytes = buf.getvalue()
                else:
                    frame_bytes = raw_jpeg
                writer.write_jpeg_frame(frame_bytes)
                elapsed = time.monotonic() - t0
                self._stop_event.wait(max(0.01, interval - elapsed))
        finally:
            writer.close()
            capturer.close()
