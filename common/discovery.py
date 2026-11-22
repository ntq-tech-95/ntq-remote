"""Tự động phát hiện máy Giáo viên trong mạng LAN qua UDP Broadcast."""

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable

from common.config import DISCOVERY_INTERVAL_SEC, DISCOVERY_UDP_PORT
from common.network import get_broadcast_addresses, get_local_ip


@dataclass
class DiscoveredRoom:
    """Thông tin một phòng học tìm thấy trong mạng LAN."""

    room_code: str
    teacher_name: str
    host_ip: str
    ws_port: int
    last_seen: float


class TeacherBeacon:
    """Phát tín hiệu UDP định kỳ để máy Học sinh tự tìm thấy máy Giáo viên."""

    def __init__(self, room_code: str, teacher_name: str, ws_port: int) -> None:
        self.room_code = room_code
        self.teacher_name = teacher_name
        self.ws_port = ws_port
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def update_info(self, room_code: str, teacher_name: str) -> None:
        self.room_code = room_code
        self.teacher_name = teacher_name

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            while not self._stop_event.is_set():
                payload = json.dumps(
                    {
                        "app": "PhongTinHocVN",
                        "room": self.room_code,
                        "teacher": self.teacher_name,
                        "ip": get_local_ip(),
                        "ws_port": self.ws_port,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                for addr in get_broadcast_addresses():
                    try:
                        sock.sendto(payload, (addr, DISCOVERY_UDP_PORT))
                    except OSError:
                        pass
                self._stop_event.wait(DISCOVERY_INTERVAL_SEC)
        finally:
            sock.close()


class StudentDiscoveryListener:
    """Lắng nghe tín hiệu UDP từ các máy Giáo viên trong mạng LAN."""

    def __init__(
        self,
        on_rooms_changed: Callable[[list[DiscoveredRoom]], None] | None = None,
    ) -> None:
        self._on_rooms_changed = on_rooms_changed
        self._rooms: dict[tuple[str, int], DiscoveredRoom] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def get_rooms(self) -> list[DiscoveredRoom]:
        now = time.monotonic()
        with self._lock:
            stale = [k for k, v in self._rooms.items() if now - v.last_seen > 6.0]
            for k in stale:
                del self._rooms[k]
            return list(self._rooms.values())

    def _run(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", DISCOVERY_UDP_PORT))
            sock.settimeout(1.0)
        except OSError:
            sock.close()
            return

        try:
            while not self._stop_event.is_set():
                try:
                    data, sender = sock.recvfrom(4096)
                except TimeoutError:
                    self._notify_if_pruned()
                    continue
                except OSError:
                    break

                try:
                    obj = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue

                if obj.get("app") != "PhongTinHocVN":
                    continue

                host_ip = str(obj.get("ip") or sender[0])
                ws_port = int(obj.get("ws_port") or 47821)
                room_code = str(obj.get("room") or "PHONG-TIN-01")
                teacher_name = str(obj.get("teacher") or "Giáo viên")

                with self._lock:
                    self._rooms[(host_ip, ws_port)] = DiscoveredRoom(
                        room_code=room_code,
                        teacher_name=teacher_name,
                        host_ip=host_ip,
                        ws_port=ws_port,
                        last_seen=time.monotonic(),
                    )
                    rooms = list(self._rooms.values())
                if self._on_rooms_changed:
                    self._on_rooms_changed(rooms)
        finally:
            sock.close()

    def _notify_if_pruned(self) -> None:
        now = time.monotonic()
        changed = False
        with self._lock:
            stale = [k for k, v in self._rooms.items() if now - v.last_seen > 6.0]
            for k in stale:
                del self._rooms[k]
                changed = True
            rooms = list(self._rooms.values())
        if changed and self._on_rooms_changed:
            self._on_rooms_changed(rooms)
