"""Máy khách WebSocket chạy trên Máy Học Sinh."""

import asyncio
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from common.audio import AudioReceiver
from common.config import (
    APP_VERSION,
    BIN_FILE_TRANSFER,
    BIN_STUDENT_SCREEN,
    BIN_TEACHER_AUDIO,
    BIN_TEACHER_BROADCAST,
    CLIENT_RECONNECT_SEC,
    DEFAULT_TEACHER_PASSWORD,
    FILE_CHUNK_SIZE,
    GRID_DEFAULT_FPS,
    GRID_DEFAULT_HEIGHT,
    GRID_DEFAULT_QUALITY,
    GRID_DEFAULT_WIDTH,
    WS_PORT,
)
from common.device_control import set_system_audio_muted, set_usb_storage_blocked
from common.discovery import DiscoveredRoom, StudentDiscoveryListener
from common.network import (
    get_hostname,
    get_mac_address,
    get_student_inbox_dir,
    sanitize_filename,
)
from common.policy import enforce_blocked_apps, enforce_web_policy
from common.protocol import (
    decode_msg,
    encode_msg,
    pack_file_packet,
    pack_screen_frame,
    unpack_binary_packet,
)
from common.screen import RemoteInputController, ScreenCapturer
from common.storage import (
    hash_password,
    load_student_state,
    save_student_state,
    verify_password,
)
from student.app_update import (
    get_update_dir,
    prepare_self_update_script,
    verify_sha256,
)


class StudentSignals(QObject):
    """Tín hiệu Qt gửi từ luồng mạng về giao diện Học sinh."""

    connection_changed = Signal(bool, str)
    rooms_discovered = Signal(list)
    lock_changed = Signal(bool, str)
    blank_changed = Signal(bool, str)
    broadcast_changed = Signal(bool)
    broadcast_presenter = Signal(str)
    broadcast_frame = Signal(bytes)
    chat_received = Signal(str, str)
    announcement_received = Signal(str, str)
    file_received = Signal(str, str)
    collect_requested = Signal(str)
    quiz_received = Signal(dict)
    exam_received = Signal(dict)
    exam_result_received = Signal(dict)
    hand_acknowledged = Signal()
    update_ready = Signal(str)
    status_message = Signal(str)


class _IncomingStudentFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = open(path, "wb")

    def write(self, data: bytes) -> None:
        self.handle.write(data)

    def close(self) -> None:
        self.handle.close()


class StudentClient:
    """Quản lý kết nối tự động, truyền màn hình, chính sách và lệnh từ Giáo viên."""

    def __init__(
        self,
        student_name: str | None = None,
        manual_host: str | None = None,
        target_room: str | None = None,
        ws_port: int = WS_PORT,
        enable_discovery: bool = True,
        allow_power_commands: bool = True,
        state_dir: Path | None = None,
    ) -> None:
        self._state_dir = state_dir
        self._state = load_student_state(state_dir)

        self.student_id = uuid.uuid4().hex[:10]
        self.pc_name = get_hostname()
        self.mac_address = get_mac_address()
        self.student_name = (
            student_name if student_name is not None else str(self._state.get("student_name") or "")
        ).strip()
        self.manual_host = (
            manual_host if manual_host is not None else str(self._state.get("manual_host") or "")
        ).strip()
        self.target_room = (
            target_room if target_room is not None else str(self._state.get("target_room") or "")
        ).strip()
        self.password_hash = str(
            self._state.get("password_hash") or hash_password(DEFAULT_TEACHER_PASSWORD)
        )

        self.ws_port = ws_port
        self.enable_discovery = enable_discovery
        self.allow_power_commands = allow_power_commands

        self.signals = StudentSignals()
        self._discovery: StudentDiscoveryListener | None = None
        self._discovered_rooms: list[DiscoveredRoom] = []

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._ws: ClientConnection | None = None
        self._target_changed = threading.Event()

        self._screen_width = GRID_DEFAULT_WIDTH
        self._screen_height = GRID_DEFAULT_HEIGHT
        self._screen_fps = GRID_DEFAULT_FPS
        self._screen_quality = GRID_DEFAULT_QUALITY

        self._policy_apps: list[str] = []
        self._policy_web_mode: str = "allow_all"
        self._policy_web_domains: list[str] = []

        self._incoming_files: dict[str, _IncomingStudentFile] = {}
        self._input_ctrl = RemoteInputController()
        self._audio_receiver = AudioReceiver()

    def _persist_state(self) -> None:
        self._state["student_name"] = self.student_name
        self._state["manual_host"] = self.manual_host
        self._state["target_room"] = self.target_room
        self._state["password_hash"] = self.password_hash
        try:
            save_student_state(self._state, self._state_dir)
        except OSError:
            pass

    def verify_teacher_password(self, plain: str) -> bool:
        """Kiểm tra mật khẩu giáo viên (để thoát hoặc tắt tự khởi động)."""
        return verify_password(plain, self.password_hash)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_flag.clear()
        if self.enable_discovery:
            self._discovery = StudentDiscoveryListener(self._on_rooms_updated)
            self._discovery.start()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        self._target_changed.set()
        if self._discovery:
            self._discovery.stop()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._close_ws_sync)
        if self._thread:
            self._thread.join(timeout=3.0)

    def _close_ws_sync(self) -> None:
        if self._ws:
            asyncio.create_task(self._ws.close())

    def _on_rooms_updated(self, rooms: list[DiscoveredRoom]) -> None:
        self._discovered_rooms = rooms
        serialized = [
            {
                "room_code": r.room_code,
                "teacher_name": r.teacher_name,
                "host_ip": r.host_ip,
                "ws_port": r.ws_port,
            }
            for r in rooms
        ]
        self.signals.rooms_discovered.emit(serialized)

    def set_manual_host(self, host: str, port: int = WS_PORT) -> None:
        self.manual_host = host.strip()
        self.ws_port = port
        self._persist_state()
        self._target_changed.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._close_ws_sync)

    def set_target_room(self, room_code: str) -> None:
        self.target_room = room_code.strip()
        self._persist_state()
        self._target_changed.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._close_ws_sync)

    def set_student_name(self, name: str) -> None:
        self.student_name = name.strip()
        self._persist_state()
        self._send_json("set_name", student_name=self.student_name)

    def set_hand_raised(self, raised: bool) -> None:
        self._send_json("raise_hand", raised=raised)

    def send_chat(self, text: str) -> None:
        if text.strip():
            self._send_json("chat", text=text.strip())

    def send_quiz_answer(self, quiz_id: str, choice_index: int) -> None:
        self._send_json("quiz_answer", quiz_id=quiz_id, choice_index=choice_index)

    def submit_exam(self, exam_id: str, answers: list[int]) -> None:
        self._send_json("exam_submit", exam_id=exam_id, answers=answers)

    def submit_file(self, file_path: str) -> None:
        async def _op() -> None:
            ws = self._ws
            if not ws:
                self.signals.status_message.emit(
                    "Chưa kết nối tới máy Giáo viên nên chưa thể nộp bài."
                )
                return
            path = Path(file_path)
            if not path.is_file():
                self.signals.status_message.emit("Không tìm thấy tệp để nộp.")
                return
            transfer_id = uuid.uuid4().hex[:10]
            total_size = path.stat().st_size
            filename = path.name
            with open(path, "rb") as f:
                sent = 0
                while True:
                    chunk = f.read(FILE_CHUNK_SIZE)
                    sent += len(chunk)
                    eof = sent >= total_size or len(chunk) == 0
                    pkt = pack_file_packet(
                        {
                            "transfer_id": transfer_id,
                            "filename": filename,
                            "total_size": total_size,
                            "purpose": "collect",
                            "eof": eof,
                        },
                        chunk,
                    )
                    await ws.send(pkt)
                    if eof:
                        break
                    await asyncio.sleep(0.005)
            self.signals.status_message.emit(f"Đã nộp bài '{filename}' thành công!")

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_op(), self._loop)

    def _send_json(self, msg_type: str, **payload: Any) -> None:
        async def _op() -> None:
            if self._ws:
                try:
                    await self._ws.send(encode_msg(msg_type, **payload))
                except Exception:
                    pass

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(_op(), self._loop)

    def _pick_target(self) -> tuple[str, int] | None:
        if self.manual_host:
            return self.manual_host, self.ws_port
        if self.target_room:
            wanted = self.target_room.lower()
            for r in self._discovered_rooms:
                if r.room_code.lower() == wanted:
                    return r.host_ip, r.ws_port
            return None
        if self._discovered_rooms:
            room = self._discovered_rooms[0]
            return room.host_ip, room.ws_port
        return None

    def _run_loop(self) -> None:
        asyncio.run(self._client_loop())

    async def _client_loop(self) -> None:
        self._loop = asyncio.get_running_loop()
        while not self._stop_flag.is_set():
            self._target_changed.clear()
            target = self._pick_target()
            if not target:
                msg = (
                    f"Đang chờ đúng phòng '{self.target_room}' trong mạng LAN..."
                    if self.target_room
                    else "Đang tìm máy Giáo viên trong mạng LAN..."
                )
                self.signals.connection_changed.emit(False, msg)
                await asyncio.sleep(1.0)
                continue

            host, port = target
            uri = f"ws://{host}:{port}"
            try:
                async with connect(uri, max_size=16 * 1024 * 1024) as ws:
                    self._ws = ws
                    await ws.send(
                        encode_msg(
                            "hello",
                            student_id=self.student_id,
                            pc_name=self.pc_name,
                            student_name=self.student_name,
                            mac_address=self.mac_address,
                            app_version=APP_VERSION,
                        )
                    )
                    screen_task = asyncio.create_task(self._screen_stream_loop(ws))
                    policy_task = asyncio.create_task(self._policy_loop())
                    try:
                        async for message in ws:
                            if self._stop_flag.is_set() or self._target_changed.is_set():
                                break
                            if isinstance(message, str):
                                await self._handle_text(message)
                            elif isinstance(message, bytes):
                                self._handle_binary(message)
                    finally:
                        screen_task.cancel()
                        policy_task.cancel()
                        for t in (screen_task, policy_task):
                            try:
                                await t
                            except asyncio.CancelledError:
                                pass
            except (OSError, ConnectionClosed, Exception):
                pass
            finally:
                self._ws = None
                self._audio_receiver.stop()
                self._policy_apps = []
                self._policy_web_mode = "allow_all"
                self._policy_web_domains = []
                for inc in self._incoming_files.values():
                    inc.close()
                self._incoming_files.clear()
                # An toàn: Tự động mở khóa và tắt trình chiếu nếu mất kết nối giáo viên
                self.signals.lock_changed.emit(False, "")
                self.signals.blank_changed.emit(False, "")
                self.signals.broadcast_changed.emit(False)
                self.signals.connection_changed.emit(False, "Mất kết nối — Đang kết nối lại...")

            if not self._stop_flag.is_set() and not self._target_changed.is_set():
                await asyncio.sleep(CLIENT_RECONNECT_SEC)

    async def _policy_loop(self) -> None:
        try:
            while not self._stop_flag.is_set():
                if self._policy_apps:
                    killed = await asyncio.to_thread(
                        enforce_blocked_apps, self._policy_apps
                    )
                    if killed:
                        msg = f"Đã chặn ứng dụng '{killed[0]}' trong giờ học."
                        self.signals.status_message.emit(f"🚫 {msg}")
                        if self._ws:
                            await self._ws.send(encode_msg("policy_violation", detail=msg))
                if self._policy_web_mode != "allow_all" and self._policy_web_domains:
                    closed = await asyncio.to_thread(
                        enforce_web_policy,
                        self._policy_web_mode,
                        self._policy_web_domains,
                    )
                    if closed:
                        msg = f"Đã đóng trang web không hợp lệ ({closed[0][:40]})."
                        self.signals.status_message.emit(f"🌐 {msg}")
                        if self._ws:
                            await self._ws.send(encode_msg("policy_violation", detail=msg))
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            pass

    async def _screen_stream_loop(self, ws: ClientConnection) -> None:
        capturer = ScreenCapturer()
        last_jpeg: bytes | None = None
        last_sent_time = 0.0
        throttle_scale = 1.0
        slow_streak = 0
        fast_streak = 0
        try:
            while not self._stop_flag.is_set():
                base_fps = max(0.5, float(self._screen_fps))
                eff_fps = max(0.5, base_fps * throttle_scale)
                eff_quality = max(32, int(self._screen_quality * (0.85 if throttle_scale < 1.0 else 1.0)))
                interval = 1.0 / eff_fps
                t0 = time.monotonic()
                jpeg = await asyncio.to_thread(
                    capturer.capture_jpeg,
                    self._screen_width,
                    self._screen_height,
                    eff_quality,
                )
                now = time.monotonic()
                if jpeg != last_jpeg or (now - last_sent_time) >= 4.0:
                    last_jpeg = jpeg
                    last_sent_time = now
                    await ws.send(pack_screen_frame(BIN_STUDENT_SCREEN, jpeg))
                elapsed = time.monotonic() - t0
                # Tự hạ tốc độ gửi nếu máy học sinh yếu hoặc mạng chậm, tự phục hồi khi thông thoáng
                if elapsed > interval * 0.8:
                    slow_streak += 1
                    fast_streak = 0
                    if slow_streak >= 3 and throttle_scale > 0.5:
                        throttle_scale = max(0.5, round(throttle_scale - 0.25, 2))
                        slow_streak = 0
                elif elapsed < interval * 0.35:
                    slow_streak = 0
                    fast_streak += 1
                    if fast_streak >= 10 and throttle_scale < 1.0:
                        throttle_scale = min(1.0, round(throttle_scale + 0.25, 2))
                        fast_streak = 0
                else:
                    slow_streak = 0
                await asyncio.sleep(max(0.05, interval - elapsed))
        except (asyncio.CancelledError, ConnectionClosed, Exception):
            pass
        finally:
            capturer.close()

    async def _handle_text(self, raw: str) -> None:
        try:
            data = decode_msg(raw)
        except ValueError:
            return
        mtype = data.get("type")

        if mtype == "welcome":
            room = data.get("room_name", "Lớp học")
            teacher = data.get("teacher_name", "Giáo viên")
            if data.get("password_hash"):
                self.password_hash = str(data["password_hash"])
                self._persist_state()
            pol = data.get("policy")
            if isinstance(pol, dict):
                self._apply_policy_dict(pol)
            self.signals.connection_changed.emit(
                True, f"Đã kết nối: {room} ({teacher})"
            )
            if data.get("broadcasting"):
                self.signals.broadcast_changed.emit(True)

        elif mtype == "password_update":
            if data.get("password_hash"):
                self.password_hash = str(data["password_hash"])
                self._persist_state()

        elif mtype == "room_update":
            room = str(data.get("room_name") or "Lớp học")
            teacher = str(data.get("teacher_name") or "Giáo viên")
            self.signals.connection_changed.emit(
                True, f"Đã kết nối: {room} ({teacher})"
            )

        elif mtype == "policy_update":
            self._apply_policy_dict(data)
            self.signals.status_message.emit("🛡 Đã cập nhật quy định ứng dụng & web từ Giáo viên.")

        elif mtype == "quiz":
            self.signals.quiz_received.emit(data)

        elif mtype == "exam_start":
            self.signals.exam_received.emit(data)

        elif mtype == "exam_result":
            self.signals.exam_result_received.emit(data)

        elif mtype == "license_limit":
            msg = str(data.get("message") or "Máy Giáo viên đã đạt giới hạn bản quyền.")
            self.signals.status_message.emit(f"🔐 {msg}")
            self.signals.connection_changed.emit(False, msg)

        elif mtype == "audio_start":
            if self._audio_receiver.start():
                self.signals.status_message.emit("🔊 Đang nghe âm thanh truyền từ Giáo viên.")

        elif mtype == "audio_stop":
            self._audio_receiver.stop()
            self.signals.status_message.emit("🔇 Giáo viên đã tắt truyền âm thanh.")

        elif mtype == "device_control":
            action = str(data.get("action") or "")
            val = bool(data.get("value", False))
            if action == "mute_audio":
                _ok, msg = await asyncio.to_thread(set_system_audio_muted, val)
            elif action == "block_usb":
                _ok, msg = await asyncio.to_thread(set_usb_storage_blocked, val)
            else:
                msg = ""
            if msg:
                self.signals.status_message.emit(f"🔧 {msg}")
                if self._ws:
                    try:
                        await self._ws.send(encode_msg("device_notice", message=msg))
                    except Exception:
                        pass

        elif mtype == "request_screen":
            self._screen_width = int(data.get("width", GRID_DEFAULT_WIDTH))
            self._screen_height = int(data.get("height", GRID_DEFAULT_HEIGHT))
            self._screen_fps = float(data.get("fps", GRID_DEFAULT_FPS))
            self._screen_quality = int(data.get("quality", GRID_DEFAULT_QUALITY))

        elif mtype == "lock":
            self.signals.lock_changed.emit(
                True,
                str(data.get("message") or "Màn hình đã bị khóa. Vui lòng chú ý nghe giảng!"),
            )

        elif mtype == "unlock":
            self.signals.lock_changed.emit(False, "")

        elif mtype == "blank":
            self.signals.blank_changed.emit(
                True,
                str(data.get("message") or "Giáo viên tạm tắt màn hình."),
            )

        elif mtype == "unblank":
            self.signals.blank_changed.emit(False, "")

        elif mtype == "broadcast_start":
            presenter = str(data.get("presenter") or "Giáo viên")
            self.signals.broadcast_presenter.emit(presenter)
            self.signals.broadcast_changed.emit(True)

        elif mtype == "broadcast_stop":
            self.signals.broadcast_changed.emit(False)

        elif mtype == "chat":
            sender = str(data.get("sender") or "Giáo viên")
            text = str(data.get("text") or "")
            if text:
                self.signals.chat_received.emit(sender, text)

        elif mtype == "announcement":
            title = str(data.get("title") or "Thông báo từ Giáo viên")
            text = str(data.get("text") or "")
            self.signals.announcement_received.emit(title, text)

        elif mtype == "hand_ack":
            self.signals.hand_acknowledged.emit()

        elif mtype == "collect_request":
            self.signals.collect_requested.emit(str(data.get("note") or ""))

        elif mtype == "open_url":
            url = str(data.get("url") or "").strip()
            if url.startswith(("http://", "https://")):
                webbrowser.open(url)

        elif mtype == "remote_input":
            await asyncio.to_thread(self._input_ctrl.apply, data)

        elif mtype == "power" and self.allow_power_commands:
            self._execute_power(str(data.get("action") or ""))

    def _apply_policy_dict(self, data: dict[str, Any]) -> None:
        self._policy_apps = [str(x) for x in data.get("blocked_apps", []) if str(x).strip()]
        self._policy_web_mode = str(data.get("web_mode") or "allow_all")
        self._policy_web_domains = [
            str(x) for x in data.get("web_domains", []) if str(x).strip()
        ]

    def _execute_power(self, action: str) -> None:
        if sys.platform != "win32":
            return
        if action == "shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "5"])
        elif action == "restart":
            subprocess.Popen(["shutdown", "/r", "/t", "5"])
        elif action == "logoff":
            subprocess.Popen(["shutdown", "/l"])

    def _handle_binary(self, raw: bytes) -> None:
        try:
            kind, header, payload = unpack_binary_packet(raw)
        except ValueError:
            return
        if kind == BIN_TEACHER_BROADCAST:
            self.signals.broadcast_frame.emit(payload)
        elif kind == BIN_TEACHER_AUDIO:
            self._audio_receiver.push(payload)
        elif kind == BIN_FILE_TRANSFER and header:
            tid = str(header.get("transfer_id") or "")
            if not tid:
                return
            purpose = str(header.get("purpose") or "distribute")
            if tid not in self._incoming_files:
                fname = sanitize_filename(str(header.get("filename") or "bai_tap"))
                if purpose == "app_update":
                    dest = get_update_dir(self._state_dir) / fname
                else:
                    dest = get_student_inbox_dir() / fname
                self._incoming_files[tid] = _IncomingStudentFile(dest)
            inc = self._incoming_files[tid]
            if payload:
                inc.write(payload)
            if header.get("eof"):
                saved = Path(inc.path)
                fname = saved.name
                inc.close()
                del self._incoming_files[tid]
                if purpose == "app_update":
                    expected_sha = str(header.get("sha256") or "")
                    if not verify_sha256(saved, expected_sha):
                        self.signals.status_message.emit(
                            "⚠ Gói cập nhật bị lỗi kiểm tra SHA-256, đã hủy cài đặt."
                        )
                        return
                    if getattr(sys, "frozen", False):
                        bat_path = prepare_self_update_script(
                            saved, Path(sys.executable).resolve(), "--student"
                        )
                        self.signals.update_ready.emit(str(bat_path))
                    else:
                        self.signals.status_message.emit(
                            f"🔄 Đã nhận bản cập nhật hợp lệ (SHA-256 OK): {saved}"
                        )
                else:
                    self.signals.file_received.emit(fname, str(saved))
