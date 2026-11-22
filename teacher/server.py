"""Máy chủ WebSocket trung tâm cho phần mềm Máy Giáo Viên."""

import asyncio
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from common.adaptive import AdaptiveTierController
from common.audio import AudioSender
from common.config import (
    APP_VERSION,
    BIN_FILE_TRANSFER,
    BIN_STUDENT_SCREEN,
    BIN_TEACHER_AUDIO,
    BIN_TEACHER_BROADCAST,
    BROADCAST_FPS,
    BROADCAST_HEIGHT,
    BROADCAST_QUALITY,
    BROADCAST_WIDTH,
    DEFAULT_ROOM_CODE,
    DEFAULT_TEACHER_NAME,
    DEFAULT_UPDATE_MANIFEST_URL,
    FILE_CHUNK_SIZE,
    GRID_DEFAULT_FPS,
    GRID_DEFAULT_HEIGHT,
    GRID_DEFAULT_QUALITY,
    GRID_DEFAULT_WIDTH,
    REMOTE_VIEW_FPS,
    REMOTE_VIEW_HEIGHT,
    REMOTE_VIEW_QUALITY,
    REMOTE_VIEW_WIDTH,
    WS_PORT,
)
from common.discovery import TeacherBeacon
from common.licensing import LicenseInfo, check_active_license
from common.network import get_teacher_collect_dir, sanitize_filename, send_wake_on_lan
from common.protocol import (
    decode_msg,
    encode_msg,
    pack_file_packet,
    pack_screen_frame,
    unpack_binary_packet,
)
from common.screen import ScreenCapturer
from common.storage import hash_password, load_teacher_state, save_teacher_state
from common.updater import compute_sha256, is_newer_version


@dataclass
class StudentInfo:
    """Thông tin trạng thái hiển thị của một máy học sinh."""

    student_id: str
    pc_name: str
    student_name: str
    ip_address: str
    mac_address: str = ""
    seat_label: str = ""
    app_version: str = ""
    locked: bool = False
    blanked: bool = False
    hand_raised: bool = False
    connected_at: str = ""


class TeacherSignals(QObject):
    """Tín hiệu Qt an toàn luồng để cập nhật giao diện Giáo viên."""

    student_connected = Signal(dict)
    student_disconnected = Signal(str)
    student_updated = Signal(dict)
    student_frame = Signal(str, bytes)
    chat_received = Signal(str, str, str)
    file_collected = Signal(str, str, str)
    quiz_answer_received = Signal(str, str, int, str)
    exam_submission_received = Signal(str, str, str, int, int, float)
    device_notice = Signal(str, str)
    server_status = Signal(str)
    server_error = Signal(str)


class _IncomingFile:
    """Quản lý luồng nhận tệp bài làm đang tải từ học sinh."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = open(path, "wb")

    def write(self, data: bytes) -> None:
        self.handle.write(data)

    def close(self) -> None:
        self.handle.close()


class TeacherServer:
    """Điều phối kết nối, truyền màn hình, khóa máy, chính sách và truyền tệp."""

    def __init__(
        self,
        room_code: str | None = None,
        teacher_name: str | None = None,
        ws_port: int = WS_PORT,
        enable_discovery: bool = True,
        state_dir: Path | None = None,
        require_license: bool = True,
    ) -> None:
        self._state_dir = state_dir
        self.require_license = require_license
        self.license_info: LicenseInfo | None = None
        self.max_students: int | None = None
        if require_license:
            ok, lic_info, _ = check_active_license(state_dir)
            if ok and lic_info:
                self.license_info = lic_info
                self.max_students = lic_info.max_students

        self._state = load_teacher_state(state_dir)
        self.room_code = room_code or str(self._state.get("room_code") or DEFAULT_ROOM_CODE)
        self.teacher_name = teacher_name or str(
            self._state.get("teacher_name") or DEFAULT_TEACHER_NAME
        )
        self.password_hash = str(self._state.get("password_hash") or hash_password("123456"))
        self.policy: dict[str, Any] = dict(
            self._state.get("policy")
            or {"blocked_apps": [], "web_mode": "allow_all", "web_domains": []}
        )
        self.known_pcs: dict[str, dict[str, str]] = dict(
            self._state.get("known_pcs") or {}
        )
        self.update_url: str = str(
            self._state.get("update_url") or DEFAULT_UPDATE_MANIFEST_URL
        ).strip()
        self.auto_check_update: bool = bool(
            self._state.get("auto_check_update", True)
        )

        self.ws_port = ws_port
        self.enable_discovery = enable_discovery
        self.signals = TeacherSignals()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_async: asyncio.Event | None = None
        self._beacon: TeacherBeacon | None = None

        self._sessions: dict[str, ServerConnection] = {}
        self._students: dict[str, StudentInfo] = {}
        self._incoming_files: dict[tuple[str, str], _IncomingFile] = {}

        self._broadcast_targets: set[str] = set()
        self._broadcast_task: asyncio.Task[None] | None = None
        self._broadcast_width: int = BROADCAST_WIDTH
        self._broadcast_height: int = BROADCAST_HEIGHT
        self._broadcast_fps: float = BROADCAST_FPS
        self._broadcast_quality: int = BROADCAST_QUALITY
        self._broadcast_auto: bool = True
        self._last_dense_mode: bool = False
        self._remote_student_id: str | None = None

        self._showcase_student_id: str | None = None
        self._showcase_viewers: set[str] = set()
        self._audio_targets: set[str] = set()
        self._audio_sender: AudioSender | None = None
        self._active_exams: dict[str, dict[str, Any]] = {}
        self._history: dict[str, list[str]] = {}

    def _persist_state(self) -> None:
        self._state["room_code"] = self.room_code
        self._state["teacher_name"] = self.teacher_name
        self._state["password_hash"] = self.password_hash
        self._state["known_pcs"] = self.known_pcs
        self._state["policy"] = self.policy
        self._state["update_url"] = self.update_url
        self._state["auto_check_update"] = self.auto_check_update
        try:
            save_teacher_state(self._state, self._state_dir)
        except OSError:
            pass

    def set_update_settings(self, update_url: str, auto_check: bool) -> None:
        self.update_url = update_url.strip() or DEFAULT_UPDATE_MANIFEST_URL
        self.auto_check_update = bool(auto_check)
        self._persist_state()

    def get_outdated_student_ids(self, target_version: str = APP_VERSION) -> list[str]:
        """Trả về danh sách student_id đang chạy phiên bản cũ hơn Giáo viên."""
        outdated: list[str] = []
        for sid, info in self._students.items():
            ver = (info.app_version or "").strip()
            if not ver or is_newer_version(target_version, ver):
                outdated.append(sid)
        return outdated

    def refresh_license(self) -> tuple[bool, LicenseInfo | None, str]:
        ok, lic_info, msg = check_active_license(self._state_dir)
        if ok and lic_info:
            self.license_info = lic_info
            self.max_students = lic_info.max_students
        return ok, lic_info, msg

    def start(self) -> None:
        """Khởi chạy máy chủ trong luồng nền riêng."""
        if self.require_license:
            ok, lic_info, msg = self.refresh_license()
            if not ok or lic_info is None:
                self.signals.server_error.emit(msg)
                return
        if self._thread and self._thread.is_alive():
            return
        if self.enable_discovery:
            self._beacon = TeacherBeacon(self.room_code, self.teacher_name, self.ws_port)
            self._beacon.start()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Dừng máy chủ và đóng toàn bộ kết nối."""
        if self._audio_sender:
            self._audio_sender.stop()
            self._audio_sender = None
        if self._beacon:
            self._beacon.stop()
        if self._loop and self._stop_async:
            self._loop.call_soon_threadsafe(self._stop_async.set)
        if self._thread:
            self._thread.join(timeout=3.0)

    def _record_history(self, student_id: str, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        entries = self._history.setdefault(student_id, [])
        entries.append(f"[{stamp}] {text}")
        if len(entries) > 200:
            del entries[: len(entries) - 200]

    def get_student_history(self, student_id: str) -> list[str]:
        return list(self._history.get(student_id, []))

    def set_room_info(self, room_code: str, teacher_name: str) -> None:
        self.room_code = room_code.strip() or DEFAULT_ROOM_CODE
        self.teacher_name = teacher_name.strip() or DEFAULT_TEACHER_NAME
        if self._beacon:
            self._beacon.update_info(self.room_code, self.teacher_name)
        self._persist_state()
        self._schedule(
            self._send_to_targets(
                None,
                encode_msg(
                    "room_update",
                    room_name=self.room_code,
                    teacher_name=self.teacher_name,
                ),
            )
        )

    def set_teacher_password(self, new_password: str) -> None:
        self.password_hash = hash_password(new_password)
        self._persist_state()
        self._schedule(
            self._send_to_targets(
                None, encode_msg("password_update", password_hash=self.password_hash)
            )
        )

    def set_seat_label(self, student_id: str, seat_label: str) -> None:
        info = self._students.get(student_id)
        if not info:
            return
        info.seat_label = seat_label.strip()
        if info.mac_address and info.mac_address in self.known_pcs:
            self.known_pcs[info.mac_address]["seat_label"] = info.seat_label
            self._persist_state()
        self.signals.student_updated.emit(asdict(info))

    def get_known_pcs(self) -> list[dict[str, str]]:
        return list(self.known_pcs.values())

    def set_known_pc_seat(self, mac_address: str, seat_label: str) -> None:
        mac = mac_address.strip().upper()
        if mac in self.known_pcs:
            self.known_pcs[mac]["seat_label"] = seat_label.strip()
            self._persist_state()

    def remove_known_pc(self, mac_address: str) -> None:
        mac = mac_address.strip().upper()
        if mac in self.known_pcs:
            del self.known_pcs[mac]
            self._persist_state()

    def wake_pcs(self, mac_list: list[str]) -> tuple[int, list[str]]:
        ok_count = 0
        messages: list[str] = []
        for mac in mac_list:
            ok, msg = send_wake_on_lan(mac)
            if ok:
                ok_count += 1
            messages.append(msg)
        return ok_count, messages

    def get_students_snapshot(self) -> list[dict[str, Any]]:
        return [asdict(s) for s in self._students.values()]

    def _run_loop(self) -> None:
        asyncio.run(self._serve_forever())

    async def _serve_forever(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_async = asyncio.Event()
        try:
            async with serve(
                self._handle_client,
                "0.0.0.0",
                self.ws_port,
                max_size=16 * 1024 * 1024,
            ):
                self.signals.server_status.emit(
                    f"Đang mở lớp '{self.room_code}' trên cổng {self.ws_port}"
                )
                await self._stop_async.wait()
        except OSError as exc:
            self.signals.server_error.emit(
                f"Không thể mở cổng {self.ws_port}: {exc}"
            )
        finally:
            if self._broadcast_task:
                self._broadcast_task.cancel()
            for inc in self._incoming_files.values():
                inc.close()
            self._incoming_files.clear()

    def _schedule(self, coro: Any) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _handle_client(self, ws: ServerConnection) -> None:
        student_id: str | None = None
        remote_ip = "127.0.0.1"
        if ws.remote_address:
            remote_ip = str(ws.remote_address[0])

        try:
            async for message in ws:
                if isinstance(message, str):
                    try:
                        data = decode_msg(message)
                    except (ValueError, Exception):
                        continue
                    msg_type = data.get("type")

                    if msg_type == "hello":
                        student_id = str(data.get("student_id") or uuid.uuid4().hex[:8])
                        if (
                            self.require_license
                            and self.max_students is not None
                            and student_id not in self._students
                            and len(self._students) >= self.max_students
                        ):
                            await ws.send(
                                encode_msg(
                                    "license_limit",
                                    message=f"Đã đạt giới hạn tối đa {self.max_students} máy học sinh theo bản quyền.",
                                )
                            )
                            await ws.close()
                            return
                        pc_name = str(data.get("pc_name") or "Máy học sinh")
                        student_name = str(data.get("student_name") or "").strip()
                        mac_addr = str(data.get("mac_address") or "").strip().upper()
                        app_version = str(data.get("app_version") or "").strip()

                        seat_label = ""
                        if mac_addr:
                            prev = self.known_pcs.get(mac_addr, {})
                            seat_label = prev.get("seat_label", "")
                            self.known_pcs[mac_addr] = {
                                "mac_address": mac_addr,
                                "pc_name": pc_name,
                                "last_ip": remote_ip,
                                "seat_label": seat_label,
                                "last_seen": time.strftime("%d/%m/%Y %H:%M"),
                            }
                            self._persist_state()

                        info = StudentInfo(
                            student_id=student_id,
                            pc_name=pc_name,
                            student_name=student_name,
                            ip_address=remote_ip,
                            mac_address=mac_addr,
                            seat_label=seat_label,
                            app_version=app_version,
                            connected_at=time.strftime("%H:%M:%S"),
                        )
                        self._sessions[student_id] = ws
                        self._students[student_id] = info
                        self._record_history(
                            student_id,
                            f"Đã kết nối vào lớp (IP: {remote_ip}, Tên: {student_name or 'Chưa nhập'})",
                        )
                        self.signals.student_connected.emit(asdict(info))

                        await ws.send(
                            encode_msg(
                                "welcome",
                                room_name=self.room_code,
                                teacher_name=self.teacher_name,
                                password_hash=self.password_hash,
                                policy=self.policy,
                                broadcasting=student_id in self._broadcast_targets,
                            )
                        )
                        await self._send_screen_profile(student_id, ws)
                        await self._check_dense_grid_transition()

                    elif student_id and msg_type == "set_name":
                        info = self._students.get(student_id)
                        if info:
                            info.student_name = str(data.get("student_name") or "").strip()
                            self._record_history(student_id, f"Điểm danh tên: {info.student_name}")
                            self.signals.student_updated.emit(asdict(info))

                    elif student_id and msg_type == "raise_hand":
                        info = self._students.get(student_id)
                        if info:
                            info.hand_raised = bool(data.get("raised", False))
                            if info.hand_raised:
                                self._record_history(student_id, "Giơ tay xin hỗ trợ")
                            self.signals.student_updated.emit(asdict(info))

                    elif student_id and msg_type == "chat":
                        info = self._students.get(student_id)
                        sender = (
                            info.student_name or info.pc_name
                            if info
                            else "Học sinh"
                        )
                        text = str(data.get("text") or "").strip()
                        if text:
                            self._record_history(student_id, f"Nhắn tin: {text}")
                            self.signals.chat_received.emit(student_id, sender, text)

                    elif student_id and msg_type == "quiz_answer":
                        info = self._students.get(student_id)
                        who = (
                            (info.student_name or info.pc_name)
                            if info
                            else student_id
                        )
                        quiz_id = str(data.get("quiz_id") or "")
                        choice = int(data.get("choice_index", -1))
                        if quiz_id and choice >= 0:
                            self.signals.quiz_answer_received.emit(
                                student_id, quiz_id, choice, who
                            )

                    elif student_id and msg_type == "exam_submit":
                        await self._handle_exam_submit(student_id, data)

                    elif student_id and msg_type == "policy_violation":
                        detail = str(data.get("detail") or "")
                        if detail:
                            self._record_history(student_id, f"Vi phạm chính sách: {detail}")
                            info = self._students.get(student_id)
                            who = (info.student_name or info.pc_name) if info else student_id
                            self.signals.server_status.emit(f"⚠ {who}: {detail}")

                    elif student_id and msg_type == "device_notice":
                        msg = str(data.get("message") or "")
                        if msg:
                            self._record_history(student_id, msg)
                            self.signals.device_notice.emit(student_id, msg)

                elif isinstance(message, bytes) and student_id:
                    try:
                        kind, header, payload = unpack_binary_packet(message)
                    except ValueError:
                        continue

                    if kind == BIN_STUDENT_SCREEN:
                        self.signals.student_frame.emit(student_id, payload)
                        if (
                            self._showcase_student_id == student_id
                            and self._showcase_viewers
                        ):
                            await self._forward_showcase_frame(payload)
                    elif kind == BIN_FILE_TRANSFER and header:
                        self._handle_incoming_file(student_id, header, payload)

        except ConnectionClosed:
            pass
        finally:
            if student_id:
                self._sessions.pop(student_id, None)
                self._students.pop(student_id, None)
                self._broadcast_targets.discard(student_id)
                self._showcase_viewers.discard(student_id)
                self._audio_targets.discard(student_id)
                if self._showcase_student_id == student_id:
                    self._showcase_student_id = None
                    viewers = list(self._showcase_viewers)
                    self._showcase_viewers.clear()
                    await self._send_to_targets(viewers, encode_msg("broadcast_stop"))
                if self._remote_student_id == student_id:
                    self._remote_student_id = None
                stale_keys = [k for k in self._incoming_files if k[0] == student_id]
                for k in stale_keys:
                    self._incoming_files.pop(k).close()
                self.signals.student_disconnected.emit(student_id)
                await self._check_dense_grid_transition()

    def _handle_incoming_file(
        self, student_id: str, header: dict[str, Any], chunk: bytes
    ) -> None:
        transfer_id = str(header.get("transfer_id") or "")
        if not transfer_id:
            return
        key = (student_id, transfer_id)
        if key not in self._incoming_files:
            info = self._students.get(student_id)
            label = sanitize_filename(
                f"{info.student_name}_{info.pc_name}"
                if info and info.student_name
                else (info.pc_name if info else student_id)
            )
            dest_dir = get_teacher_collect_dir() / label
            dest_dir.mkdir(parents=True, exist_ok=True)
            filename = sanitize_filename(str(header.get("filename") or "bai_nop"))
            dest_path = dest_dir / filename
            self._incoming_files[key] = _IncomingFile(dest_path)

        inc = self._incoming_files[key]
        if chunk:
            inc.write(chunk)
        if header.get("eof"):
            saved_path = str(inc.path)
            filename = inc.path.name
            inc.close()
            del self._incoming_files[key]
            self._record_history(student_id, f"Đã nộp bài: {filename}")
            self.signals.file_collected.emit(student_id, filename, saved_path)

    async def _send_screen_profile(self, student_id: str, ws: ServerConnection) -> None:
        if self._remote_student_id == student_id or self._showcase_student_id == student_id:
            msg = encode_msg(
                "request_screen",
                width=REMOTE_VIEW_WIDTH,
                height=REMOTE_VIEW_HEIGHT,
                fps=REMOTE_VIEW_FPS,
                quality=REMOTE_VIEW_QUALITY,
            )
        elif len(self._students) > 25:
            # Tối ưu cho phòng 45-50 máy: giảm tải lưới xuống 1 FPS & ảnh gọn hơn
            msg = encode_msg(
                "request_screen",
                width=320,
                height=180,
                fps=1.0,
                quality=40,
            )
        else:
            msg = encode_msg(
                "request_screen",
                width=GRID_DEFAULT_WIDTH,
                height=GRID_DEFAULT_HEIGHT,
                fps=GRID_DEFAULT_FPS,
                quality=GRID_DEFAULT_QUALITY,
            )
        await ws.send(msg)

    async def _check_dense_grid_transition(self) -> None:
        dense = len(self._students) > 25
        if dense != self._last_dense_mode:
            self._last_dense_mode = dense
            for sid, ws in list(self._sessions.items()):
                if sid != self._remote_student_id and sid != self._showcase_student_id:
                    try:
                        await self._send_screen_profile(sid, ws)
                    except Exception:
                        pass

    async def _send_binary_safe(
        self, ws: ServerConnection, pkt: bytes, timeout: float = 0.35
    ) -> bool:
        try:
            await asyncio.wait_for(ws.send(pkt), timeout=timeout)
            return True
        except Exception:
            return False

    async def _broadcast_binary(
        self, target_ids: list[str], pkt: bytes, timeout: float = 0.35
    ) -> tuple[int, int]:
        coros = [
            self._send_binary_safe(self._sessions[sid], pkt, timeout=timeout)
            for sid in target_ids
            if sid in self._sessions
        ]
        if not coros:
            return 0, 0
        results = await asyncio.gather(*coros, return_exceptions=True)
        ok_count = sum(1 for r in results if r is True)
        fail_count = len(results) - ok_count
        return ok_count, fail_count

    async def _send_to_targets(self, student_ids: list[str] | None, text: str) -> None:
        targets = (
            list(self._sessions.keys())
            if student_ids is None
            else [sid for sid in student_ids if sid in self._sessions]
        )
        coros = [
            self._sessions[sid].send(text)
            for sid in targets
            if sid in self._sessions
        ]
        if coros:
            await asyncio.gather(*coros, return_exceptions=True)

    # --- Các lệnh điều khiển từ giao diện Giáo viên ---

    def set_policy(
        self,
        student_ids: list[str] | None,
        blocked_apps: list[str],
        web_mode: str,
        web_domains: list[str],
    ) -> None:
        policy = {
            "blocked_apps": blocked_apps,
            "web_mode": web_mode,
            "web_domains": web_domains,
        }
        if student_ids is None:
            self.policy = policy
            self._persist_state()
        self._schedule(
            self._send_to_targets(student_ids, encode_msg("policy_update", **policy))
        )

    def send_quiz(
        self,
        student_ids: list[str] | None,
        quiz_id: str,
        question: str,
        options: list[str],
    ) -> None:
        self._schedule(
            self._send_to_targets(
                student_ids,
                encode_msg(
                    "quiz",
                    quiz_id=quiz_id,
                    question=question,
                    options=options,
                ),
            )
        )

    def lock_students(
        self,
        student_ids: list[str] | None,
        locked: bool,
        message: str = "Màn hình đã bị khóa. Vui lòng chú ý nghe giảng!",
    ) -> None:
        async def _op() -> None:
            targets = (
                list(self._students.keys())
                if student_ids is None
                else [sid for sid in student_ids if sid in self._students]
            )
            for sid in targets:
                info = self._students.get(sid)
                if info:
                    info.locked = locked
                    self.signals.student_updated.emit(asdict(info))
            await self._send_to_targets(
                targets,
                encode_msg("lock" if locked else "unlock", message=message),
            )

        self._schedule(_op())

    def blank_students(
        self,
        student_ids: list[str] | None,
        blanked: bool,
        message: str = "Tạm tắt màn hình để chú ý bảng.",
    ) -> None:
        async def _op() -> None:
            targets = (
                list(self._students.keys())
                if student_ids is None
                else [sid for sid in student_ids if sid in self._students]
            )
            for sid in targets:
                info = self._students.get(sid)
                if info:
                    info.blanked = blanked
                    self.signals.student_updated.emit(asdict(info))
            await self._send_to_targets(
                targets,
                encode_msg("blank" if blanked else "unblank", message=message),
            )

        self._schedule(_op())

    def set_remote_view(self, student_id: str | None) -> None:
        async def _op() -> None:
            prev = self._remote_student_id
            self._remote_student_id = student_id
            if prev and prev in self._sessions and prev != student_id:
                await self._send_screen_profile(prev, self._sessions[prev])
            if student_id and student_id in self._sessions:
                await self._send_screen_profile(student_id, self._sessions[student_id])

        self._schedule(_op())

    def send_remote_input(self, student_id: str, payload: dict[str, Any]) -> None:
        async def _op() -> None:
            ws = self._sessions.get(student_id)
            if ws:
                try:
                    await ws.send(encode_msg("remote_input", **payload))
                except Exception:
                    pass

        self._schedule(_op())

    def send_chat(self, student_ids: list[str] | None, text: str) -> None:
        self._schedule(
            self._send_to_targets(
                student_ids,
                encode_msg("chat", sender=self.teacher_name, text=text),
            )
        )

    def send_announcement(
        self, student_ids: list[str] | None, title: str, text: str
    ) -> None:
        self._schedule(
            self._send_to_targets(
                student_ids,
                encode_msg("announcement", title=title, text=text),
            )
        )

    def clear_hand(self, student_id: str) -> None:
        async def _op() -> None:
            info = self._students.get(student_id)
            if info:
                info.hand_raised = False
                self.signals.student_updated.emit(asdict(info))
            await self._send_to_targets([student_id], encode_msg("hand_ack"))

        self._schedule(_op())

    def open_url(self, student_ids: list[str] | None, url: str) -> None:
        self._schedule(self._send_to_targets(student_ids, encode_msg("open_url", url=url)))

    def send_power(self, student_ids: list[str] | None, action: str) -> None:
        self._schedule(
            self._send_to_targets(student_ids, encode_msg("power", action=action))
        )

    def request_collect_file(self, student_ids: list[str] | None, note: str = "") -> None:
        self._schedule(
            self._send_to_targets(student_ids, encode_msg("collect_request", note=note))
        )

    def distribute_file(self, student_ids: list[str] | None, file_path: str) -> None:
        self._schedule(
            self._stream_file_to_targets(student_ids, file_path, purpose="distribute")
        )

    def distribute_update(self, student_ids: list[str] | None, exe_path: str) -> None:
        self._schedule(
            self._stream_file_to_targets(student_ids, exe_path, purpose="app_update")
        )

    async def _stream_file_to_targets(
        self, student_ids: list[str] | None, file_path: str, purpose: str
    ) -> None:
        path = Path(file_path)
        if not path.is_file():
            self.signals.server_error.emit(f"Không tìm thấy tệp: {file_path}")
            return
        transfer_id = uuid.uuid4().hex[:10]
        total_size = path.stat().st_size
        filename = "NTQ_Remote_update.exe" if purpose == "app_update" else path.name
        targets = (
            list(self._sessions.keys())
            if student_ids is None
            else [sid for sid in student_ids if sid in self._sessions]
        )
        if not targets:
            return

        sha256_hex = compute_sha256(path) if purpose == "app_update" else ""

        with open(path, "rb") as f:
            sent = 0
            while True:
                chunk = f.read(FILE_CHUNK_SIZE)
                sent += len(chunk)
                eof = sent >= total_size or len(chunk) == 0
                header: dict[str, Any] = {
                    "transfer_id": transfer_id,
                    "filename": filename,
                    "total_size": total_size,
                    "purpose": purpose,
                    "eof": eof,
                }
                if eof and sha256_hex:
                    header["sha256"] = sha256_hex
                pkt = pack_file_packet(header, chunk)
                await self._broadcast_binary(targets, pkt, timeout=2.0)
                if eof:
                    break
                await asyncio.sleep(0.005)

        if purpose == "app_update":
            self.signals.server_status.emit(
                f"🔄 Đã gửi bản cập nhật tới {len(targets)} máy học sinh."
            )
        else:
            self.signals.server_status.emit(
                f"Đã phát tệp '{filename}' tới {len(targets)} máy học sinh."
            )

    def start_broadcast(
        self,
        student_ids: list[str] | None,
        fps: float = BROADCAST_FPS,
        quality: int = BROADCAST_QUALITY,
        width: int = BROADCAST_WIDTH,
        height: int = BROADCAST_HEIGHT,
        auto_adapt: bool = True,
    ) -> None:
        async def _op() -> None:
            self._broadcast_auto = auto_adapt
            self._broadcast_width = max(320, int(width))
            self._broadcast_height = max(180, int(height))
            self._broadcast_fps = max(2.0, float(fps))
            self._broadcast_quality = max(30, min(90, int(quality)))
            targets = (
                set(self._sessions.keys())
                if student_ids is None
                else {sid for sid in student_ids if sid in self._sessions}
            )
            self._broadcast_targets = targets
            await self._send_to_targets(list(targets), encode_msg("broadcast_start"))
            if self._broadcast_task is None or self._broadcast_task.done():
                self._broadcast_task = asyncio.create_task(self._broadcast_loop())
            mode_note = " (Chế độ tự động thích ứng)" if auto_adapt else ""
            self.signals.server_status.emit(
                f"Đang trình chiếu màn hình giáo viên tới {len(targets)} máy{mode_note}."
            )

        self._schedule(_op())

    def stop_broadcast(self) -> None:
        async def _op() -> None:
            targets = list(self._broadcast_targets)
            self._broadcast_targets.clear()
            if self._broadcast_task and not self._broadcast_task.done():
                self._broadcast_task.cancel()
            await self._send_to_targets(targets, encode_msg("broadcast_stop"))
            self.signals.server_status.emit("Đã dừng trình chiếu màn hình.")

        self._schedule(_op())

    async def _broadcast_loop(self) -> None:
        capturer = ScreenCapturer()
        last_jpeg: bytes | None = None
        last_sent_time = 0.0
        # Nếu lớp đông (>25 máy), tự khởi đầu ở mức vừa (bậc 1) rồi tự điều chỉnh lên/xuống
        init_tier = 1 if len(self._students) > 25 else 0
        adapt = AdaptiveTierController(initial_tier=init_tier)
        try:
            while self._broadcast_targets:
                if self._broadcast_auto:
                    tier = adapt.current
                    w, h, fps, qual = tier.width, tier.height, tier.fps, tier.quality
                else:
                    w, h, fps, qual = (
                        self._broadcast_width,
                        self._broadcast_height,
                        self._broadcast_fps,
                        self._broadcast_quality,
                    )

                interval = 1.0 / max(2.0, fps)
                t0 = time.monotonic()
                jpeg = await asyncio.to_thread(capturer.capture_jpeg, w, h, qual)
                now = time.monotonic()
                fail_count = 0
                sent_frame = False
                # Bỏ qua khung hình giống hệt để tiết kiệm băng thông LAN/Wi-Fi
                if jpeg != last_jpeg or (now - last_sent_time) >= 2.0:
                    last_jpeg = jpeg
                    last_sent_time = now
                    pkt = pack_screen_frame(BIN_TEACHER_BROADCAST, jpeg)
                    _, fail_count = await self._broadcast_binary(
                        list(self._broadcast_targets), pkt, timeout=0.35
                    )
                    sent_frame = True

                elapsed = time.monotonic() - t0
                if self._broadcast_auto and sent_frame:
                    prev_idx = adapt.tier_index
                    changed = adapt.record_sample(elapsed, fail_count)
                    if changed is not None:
                        if adapt.tier_index > prev_idx:
                            self.signals.server_status.emit(
                                f"⚡ Mạng đang tải cao — Tự động hạ trình chiếu xuống: {changed.label}"
                            )
                        else:
                            self.signals.server_status.emit(
                                f"✨ Mạng ổn định — Tự động nâng trình chiếu lên: {changed.label}"
                            )
                await asyncio.sleep(max(0.02, interval - elapsed))
        except asyncio.CancelledError:
            pass
        finally:
            capturer.close()

    async def _forward_showcase_frame(self, jpeg_bytes: bytes) -> None:
        pkt = pack_screen_frame(BIN_TEACHER_BROADCAST, jpeg_bytes)
        await self._broadcast_binary(list(self._showcase_viewers), pkt, timeout=0.35)

    def start_showcase(self, student_id: str) -> None:
        """Chiếu màn hình 1 học sinh xuất sắc cho toàn lớp cùng xem."""
        async def _op() -> None:
            if student_id not in self._sessions:
                return
            self._showcase_student_id = student_id
            viewers = [sid for sid in self._sessions if sid != student_id]
            self._showcase_viewers = set(viewers)
            info = self._students.get(student_id)
            who = (info.student_name or info.pc_name) if info else "Học sinh"
            await self._send_screen_profile(student_id, self._sessions[student_id])
            await self._send_to_targets(
                viewers,
                encode_msg("broadcast_start", presenter=f"Bài của bạn {who}"),
            )
            self.signals.server_status.emit(
                f"Đang chiếu màn hình của '{who}' tới {len(viewers)} máy khác."
            )

        self._schedule(_op())

    def stop_showcase(self) -> None:
        async def _op() -> None:
            prev = self._showcase_student_id
            self._showcase_student_id = None
            viewers = list(self._showcase_viewers)
            self._showcase_viewers.clear()
            if prev and prev in self._sessions:
                await self._send_screen_profile(prev, self._sessions[prev])
            await self._send_to_targets(viewers, encode_msg("broadcast_stop"))
            self.signals.server_status.emit("Đã dừng chiếu màn hình học sinh.")

        self._schedule(_op())

    def start_audio_broadcast(self, student_ids: list[str] | None) -> tuple[bool, str]:
        """Bật micro máy Giáo viên truyền giọng nói xuống loa/tai nghe học sinh."""
        sender = AudioSender(self._on_audio_chunk)
        ok, msg = sender.start()
        if not ok:
            return False, msg
        self._audio_sender = sender

        async def _op() -> None:
            targets = (
                set(self._sessions.keys())
                if student_ids is None
                else {sid for sid in student_ids if sid in self._sessions}
            )
            self._audio_targets = targets
            await self._send_to_targets(list(targets), encode_msg("audio_start"))
            self.signals.server_status.emit(
                f"Đang truyền âm thanh micro tới {len(targets)} máy học sinh."
            )

        self._schedule(_op())
        return True, msg

    def stop_audio_broadcast(self) -> None:
        if self._audio_sender:
            self._audio_sender.stop()
            self._audio_sender = None

        async def _op() -> None:
            targets = list(self._audio_targets)
            self._audio_targets.clear()
            await self._send_to_targets(targets, encode_msg("audio_stop"))
            self.signals.server_status.emit("Đã tắt truyền âm thanh micro.")

        self._schedule(_op())

    def _on_audio_chunk(self, pcm_bytes: bytes) -> None:
        if not self._audio_targets:
            return
        pkt = pack_screen_frame(BIN_TEACHER_AUDIO, pcm_bytes)

        async def _send() -> None:
            await self._broadcast_binary(list(self._audio_targets), pkt, timeout=0.25)

        self._schedule(_send())

    def send_device_control(
        self, student_ids: list[str] | None, action: str, value: bool
    ) -> None:
        self._schedule(
            self._send_to_targets(
                student_ids, encode_msg("device_control", action=action, value=value)
            )
        )

    def send_exam(
        self,
        student_ids: list[str] | None,
        exam_id: str,
        title: str,
        duration_minutes: int,
        questions: list[dict[str, Any]],
    ) -> None:
        """Gửi bộ đề nhiều câu xuống học sinh (ẩn đáp án đúng trên gói gửi đi)."""
        self._active_exams[exam_id] = {
            "title": title,
            "questions": questions,
        }
        public_questions = [
            {"question": q["question"], "options": q["options"]} for q in questions
        ]
        self._schedule(
            self._send_to_targets(
                student_ids,
                encode_msg(
                    "exam_start",
                    exam_id=exam_id,
                    title=title,
                    duration_minutes=duration_minutes,
                    questions=public_questions,
                ),
            )
        )

    async def _handle_exam_submit(
        self, student_id: str, data: dict[str, Any]
    ) -> None:
        exam_id = str(data.get("exam_id") or "")
        exam = self._active_exams.get(exam_id)
        if not exam:
            return
        answers = data.get("answers") or []
        questions = exam["questions"]
        total = len(questions)
        correct = 0
        for idx, q in enumerate(questions):
            ans = int(answers[idx]) if idx < len(answers) else -1
            if ans == int(q.get("correct_index", -1)):
                correct += 1
        score = round((correct / max(1, total)) * 10.0, 2)

        info = self._students.get(student_id)
        who = (info.student_name or info.pc_name) if info else student_id
        self._record_history(
            student_id,
            f"Nộp bài '{exam['title']}': {correct}/{total} câu ({score} điểm)",
        )
        self.signals.exam_submission_received.emit(
            student_id, exam_id, who, correct, total, score
        )
        ws = self._sessions.get(student_id)
        if ws:
            try:
                await ws.send(
                    encode_msg(
                        "exam_result",
                        exam_id=exam_id,
                        title=exam["title"],
                        correct=correct,
                        total=total,
                        score=score,
                    )
                )
            except Exception:
                pass
