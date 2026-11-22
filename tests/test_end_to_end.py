"""Kiểm thử tự động toàn bộ giao thức, truyền màn hình, khóa máy và truyền tệp."""

import os
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from common.adaptive import AdaptiveTierController
from common.autostart import build_launch_command, is_autostart_enabled, set_autostart
from common.config import (
    APP_AUTHOR,
    BIN_FILE_TRANSFER,
    BIN_STUDENT_SCREEN,
    BIN_TEACHER_AUDIO,
    BIN_TEACHER_BROADCAST,
)
from common.device_control import set_system_audio_muted, set_usb_storage_blocked
from common.licensing import (
    check_active_license,
    get_hardware_id,
    save_license_key,
    verify_license_key,
)
from common.recorder import MjpegAviWriter
from common.ui_helpers import load_app_icon
from QuanLyBanQuyen.build_mobile_keygen import build_mobile_html
from QuanLyBanQuyen.keygen_tool import sign_license_key
from installer.setup_wizard import (
    create_windows_shortcut,
    perform_install,
    perform_unified_install,
)
from unified_app import UnifiedLauncherWindow, _get_arg_value
from common.network import parse_mac_bytes, sanitize_filename, send_wake_on_lan
from common.policy import match_blocked_app, match_web_title_allowed
from common.win_hook import KeyboardBlocker
from student.app_update import prepare_self_update_script, verify_sha256
from student.exam_dialog import StudentExamDialog
from teacher.annotation_overlay import AnnotationController
from teacher.exam_dialog import ExamTeacherDialog
from common.protocol import (
    decode_msg,
    encode_msg,
    pack_file_packet,
    pack_screen_frame,
    unpack_binary_packet,
)
from common.screen import ScreenCapturer
from student.client import StudentClient
from student.tray_window import StudentMainWindow
from teacher.main_window import TeacherMainWindow
from teacher.server import StudentInfo, TeacherServer
from teacher.update_dialog import OnlineUpdateDialog
from common.updater import (
    compute_sha256,
    download_update_exe,
    fetch_update_manifest,
    is_newer_version,
    parse_version,
    write_release_manifest,
)
from common.release_publisher import (
    create_or_update_github_release,
    load_publisher_config,
    save_publisher_config,
)


def _pump_events(app: QApplication, predicate, timeout_sec: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.03)
    return predicate()


class TestPhongTinHocVN(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_protocol_and_sanitize(self) -> None:
        raw = encode_msg("chat", sender="Giáo viên", text="Chào cả lớp")
        obj = decode_msg(raw)
        self.assertEqual(obj["type"], "chat")
        self.assertEqual(obj["sender"], "Giáo viên")

        pkt = pack_screen_frame(BIN_STUDENT_SCREEN, b"\xff\xd8\xffdemo")
        kind, header, payload = unpack_binary_packet(pkt)
        self.assertEqual(kind, BIN_STUDENT_SCREEN)
        self.assertIsNone(header)
        self.assertEqual(payload, b"\xff\xd8\xffdemo")

        fpkt = pack_file_packet({"transfer_id": "t1", "filename": "a.txt", "eof": True}, b"abc")
        fkind, fheader, fdata = unpack_binary_packet(fpkt)
        self.assertEqual(fkind, BIN_FILE_TRANSFER)
        self.assertEqual(fheader["filename"], "a.txt")
        self.assertEqual(fdata, b"abc")

        self.assertEqual(sanitize_filename("../../evil<file>.txt"), "evil_file_.txt")

    def test_screen_capture(self) -> None:
        cap = ScreenCapturer()
        try:
            jpeg = cap.capture_jpeg(320, 180, 50)
            self.assertGreater(len(jpeg), 500)
            self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        finally:
            cap.close()

    def test_end_to_end_teacher_student(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = 48921
            server = TeacherServer(
                room_code="LOP-TEST",
                teacher_name="Cô Lan",
                ws_port=port,
                enable_discovery=False,
                state_dir=Path(tmpdir) / "t_state",
                require_license=False,
            )
            client = StudentClient(
                student_name="Nguyễn Văn A",
                manual_host="127.0.0.1",
                ws_port=port,
                enable_discovery=False,
                allow_power_commands=False,
                state_dir=Path(tmpdir) / "s_state",
            )

            events: dict[str, list] = {
                "connected": [],
                "updated": [],
                "frames": [],
                "teacher_chat": [],
                "student_chat": [],
                "lock": [],
                "blank": [],
                "broadcast": [],
                "broadcast_frames": [],
                "student_files": [],
                "teacher_files": [],
                "hand_ack": [],
                "quiz": [],
                "quiz_ans": [],
                "exam": [],
                "exam_sub": [],
                "exam_res": [],
                "conn_msgs": [],
            }

            server.signals.student_connected.connect(lambda info: events["connected"].append(info))
            server.signals.student_updated.connect(lambda info: events["updated"].append(info))
            server.signals.student_frame.connect(lambda sid, data: events["frames"].append((sid, len(data))))
            server.signals.chat_received.connect(lambda sid, s, t: events["teacher_chat"].append((s, t)))
            server.signals.file_collected.connect(
                lambda sid, fn, path: events["teacher_files"].append((fn, path))
            )
            server.signals.quiz_answer_received.connect(
                lambda sid, qid, c, who: events["quiz_ans"].append((qid, c, who))
            )
            server.signals.exam_submission_received.connect(
                lambda sid, eid, who, cor, tot, sc: events["exam_sub"].append((eid, cor, tot, sc))
            )

            client.signals.connection_changed.connect(
                lambda ok, msg: (
                    events["connected"].append(("client", ok, msg)) if ok else None,
                    events["conn_msgs"].append(msg),
                )
            )
            client.signals.lock_changed.connect(lambda l, m: events["lock"].append((l, m)))
            client.signals.blank_changed.connect(lambda b, m: events["blank"].append((b, m)))
            client.signals.broadcast_changed.connect(lambda a: events["broadcast"].append(a))
            client.signals.broadcast_frame.connect(lambda d: events["broadcast_frames"].append(len(d)))
            client.signals.chat_received.connect(lambda s, t: events["student_chat"].append((s, t)))
            client.signals.file_received.connect(lambda fn, p: events["student_files"].append((fn, p)))
            client.signals.hand_acknowledged.connect(lambda: events["hand_ack"].append(True))
            client.signals.quiz_received.connect(lambda q: events["quiz"].append(q))
            client.signals.exam_received.connect(lambda ex: events["exam"].append(ex))
            client.signals.exam_result_received.connect(lambda res: events["exam_res"].append(res))

            src_homework = Path(tmpdir) / "BaiTapTest_VN.txt"
            src_homework.write_bytes(b"Noi dung bai tap Tin hoc 100% Tieng Viet")
            src_submit = Path(tmpdir) / "BaiLamHocSinh.txt"
            src_submit.write_bytes(b"Bai lam cua em Nguyen Van A")

            server.start()
            time.sleep(0.3)
            client.start()
            try:
                ok = _pump_events(
                    self.app,
                    lambda: len(events["connected"]) >= 2 and len(events["frames"]) >= 1,
                    timeout_sec=8.0,
                )
                self.assertTrue(ok, f"Kết nối hoặc truyền màn hình thất bại: {events}")

                sid = server.get_students_snapshot()[0]["student_id"]

                # Giơ tay & hạ tay
                client.set_hand_raised(True)
                self.assertTrue(
                    _pump_events(
                        self.app,
                        lambda: any(u.get("hand_raised") for u in events["updated"]),
                    )
                )
                server.clear_hand(sid)
                self.assertTrue(_pump_events(self.app, lambda: len(events["hand_ack"]) >= 1))

                # Khóa & mở khóa
                server.lock_students([sid], True, "Tạm khóa để kiểm tra")
                self.assertTrue(
                    _pump_events(self.app, lambda: (True, "Tạm khóa để kiểm tra") in events["lock"])
                )
                server.lock_students([sid], False)
                self.assertTrue(_pump_events(self.app, lambda: (False, "") in events["lock"]))

                # Tắt & bật màn hình
                server.blank_students([sid], True)
                self.assertTrue(
                    _pump_events(self.app, lambda: any(b for b, _ in events["blank"]))
                )
                server.blank_students([sid], False)

                # Trò chuyện 2 chiều
                server.send_chat([sid], "Chào em")
                client.send_chat("Em chào cô ạ")
                self.assertTrue(
                    _pump_events(
                        self.app,
                        lambda: ("Cô Lan", "Chào em") in events["student_chat"]
                        and ("Nguyễn Văn A", "Em chào cô ạ") in events["teacher_chat"],
                    )
                )

                # Phát bài tập & Thu bài
                server.distribute_file([sid], str(src_homework))
                self.assertTrue(
                    _pump_events(self.app, lambda: len(events["student_files"]) >= 1)
                )
                _, saved_student_path = events["student_files"][0]
                self.assertEqual(
                    Path(saved_student_path).read_bytes(),
                    b"Noi dung bai tap Tin hoc 100% Tieng Viet",
                )

                client.submit_file(str(src_submit))
                self.assertTrue(
                    _pump_events(self.app, lambda: len(events["teacher_files"]) >= 1)
                )
                _, saved_teacher_path = events["teacher_files"][0]
                self.assertEqual(
                    Path(saved_teacher_path).read_bytes(),
                    b"Bai lam cua em Nguyen Van A",
                )

                # Trình chiếu màn hình giáo viên
                server.start_broadcast([sid])
                self.assertTrue(
                    _pump_events(
                        self.app,
                        lambda: True in events["broadcast"] and len(events["broadcast_frames"]) >= 1,
                        timeout_sec=6.0,
                    )
                )
                server.stop_broadcast()
                self.assertTrue(_pump_events(self.app, lambda: False in events["broadcast"]))

                # Đồng bộ mật khẩu lớp, chính sách chặn & trắc nghiệm nhanh
                server.set_teacher_password("lop6a1")
                self.assertTrue(
                    _pump_events(self.app, lambda: client.verify_teacher_password("lop6a1"))
                )
                server.set_policy([sid], ["roblox"], "block_list", ["facebook"])
                self.assertTrue(
                    _pump_events(self.app, lambda: "roblox" in client._policy_apps)
                )
                server.send_quiz([sid], "q1", "1+1=?", ["1", "2"])
                self.assertTrue(_pump_events(self.app, lambda: len(events["quiz"]) == 1))
                client.send_quiz_answer("q1", 1)
                self.assertTrue(
                    _pump_events(self.app, lambda: ("q1", 1, "Nguyễn Văn A") in events["quiz_ans"])
                )
                self.assertGreaterEqual(len(server.get_known_pcs()), 1)

                # Bài kiểm tra nhiều câu tự chấm điểm & nhật ký từng em
                server.send_exam(
                    [sid],
                    "ex1",
                    "Thi giữa kỳ",
                    5,
                    [
                        {"question": "Q1", "options": ["A", "B", "C", "D"], "correct_index": 0},
                        {"question": "Q2", "options": ["A", "B", "C", "D"], "correct_index": 2},
                    ],
                )
                self.assertTrue(_pump_events(self.app, lambda: len(events["exam"]) == 1))
                self.assertNotIn("correct_index", events["exam"][0]["questions"][0])
                client.submit_exam("ex1", [0, 2])
                self.assertTrue(
                    _pump_events(
                        self.app,
                        lambda: ("ex1", 2, 2, 10.0) in events["exam_sub"]
                        and len(events["exam_res"]) == 1,
                    )
                )
                self.assertEqual(events["exam_res"][0]["score"], 10.0)
                hist = server.get_student_history(sid)
                self.assertTrue(any("Thi giữa kỳ" in h for h in hist))

                # Đổi tên giáo viên & mã phòng đồng bộ sang học sinh
                self.assertEqual(APP_AUTHOR, "NTQ - TECH")
                server.set_room_info("PHONG-MOI", "Thầy Minh")
                self.assertTrue(
                    _pump_events(
                        self.app,
                        lambda: any("PHONG-MOI (Thầy Minh)" in m for m in events["conn_msgs"]),
                    )
                )

                # Dọn tệp test đã tạo trên Desktop
                for _, p in events["student_files"] + events["teacher_files"]:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            finally:
                client.stop()
                server.stop()

    def test_gui_windows_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            server = TeacherServer(
                ws_port=48922,
                enable_discovery=False,
                state_dir=Path(tmpdir) / "t_gui",
                require_license=False,
            )
            client = StudentClient(
                manual_host="127.0.0.1",
                ws_port=48922,
                enable_discovery=False,
                allow_power_commands=False,
                state_dir=Path(tmpdir) / "s_gui",
            )
            t_win = TeacherMainWindow(server)
            s_win = StudentMainWindow(client)
            self.app.processEvents()
            self.assertIn("Máy Giáo Viên", t_win.windowTitle())
            self.assertIn("Máy Học Sinh", s_win.windowTitle())
            self.assertTrue(hasattr(t_win, "chk_autostart"))
            self.assertTrue(hasattr(s_win, "chk_autostart"))
            s_win._allow_quit = True
            s_win.close()
            t_win.close()
            self.app.processEvents()

    def test_wol_policy_and_keyboard_hook(self) -> None:
        self.assertEqual(parse_mac_bytes("aa-bb-cc-dd-ee-ff"), bytes.fromhex("aabbccddeeff"))
        ok, _ = send_wake_on_lan("AA:BB:CC:DD:EE:FF", broadcast_ips=["127.0.0.1"])
        self.assertTrue(ok)

        self.assertTrue(match_blocked_app("RobloxPlayerBeta.exe", ["roblox"]))
        self.assertFalse(match_blocked_app("PhongTinHocVN.exe", ["roblox"]))
        self.assertFalse(
            match_web_title_allowed("Facebook - Google Chrome", "block_list", ["facebook"])
        )
        self.assertTrue(
            match_web_title_allowed("OLM.VN - Học trực tuyến - Microsoft Edge", "allow_only", ["olm.vn"])
        )
        self.assertFalse(
            match_web_title_allowed("YouTube - Microsoft Edge", "allow_only", ["olm.vn"])
        )

        blocker = KeyboardBlocker()
        blocker.start()
        self.assertTrue(blocker.is_active())
        blocker.stop()
        self.assertFalse(blocker.is_active())

    def test_autostart_registry_toggle(self) -> None:
        import winreg

        test_reg_path = r"Software\PhongTinHocVN_UnitTest_Run"
        app_key = "TestApp"
        cmd = build_launch_command("run_student.py")
        self.assertIn("run_student.py", cmd)

        try:
            ok, _ = set_autostart(app_key, True, cmd, reg_path=test_reg_path)
            self.assertTrue(ok)
            self.assertTrue(is_autostart_enabled(app_key, reg_path=test_reg_path))

            ok2, _ = set_autostart(app_key, False, reg_path=test_reg_path)
            self.assertTrue(ok2)
            self.assertFalse(is_autostart_enabled(app_key, reg_path=test_reg_path))
        finally:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, test_reg_path)
            except FileNotFoundError:
                pass

    def test_installer_perform_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = Path(tmpdir) / "payload"
            payload.mkdir()
            (payload / "GiaoVien.exe").write_bytes(b"teacher-exe-stub")
            (payload / "HocSinh.exe").write_bytes(b"student-exe-stub")

            target = Path(tmpdir) / "installed"
            exes = perform_install(
                role="both",
                install_dir=target,
                make_desktop=False,
                make_start_menu=False,
                enable_autostart=False,
                add_firewall=False,
                payload_dir=payload,
            )
            self.assertEqual(len(exes), 2)
            self.assertTrue((target / "GiaoVien.exe").is_file())
            self.assertTrue((target / "HocSinh.exe").is_file())
            self.assertTrue((target / "Go_Cai_Dat.bat").is_file())

    def test_unified_launcher_and_install(self) -> None:
        launcher = UnifiedLauncherWindow(self.app)
        launcher.show()
        self.app.processEvents()
        self.assertIn("Phòng Tin Học VN", launcher.windowTitle())
        launcher._set_status_text("Lỗi: " + ("X" * 1000), is_error=True)
        self.app.processEvents()
        self.assertLessEqual(launcher.width(), 720)
        launcher.close()

        with tempfile.TemporaryDirectory() as tmpdir:
            src_exe = Path(tmpdir) / "NTQ Remote.exe"
            src_exe.write_bytes(b"unified-exe-stub")
            target = Path(tmpdir) / "installed_unified"
            launched = perform_unified_install(
                role="both",
                install_dir=target,
                make_desktop=False,
                make_start_menu=False,
                enable_autostart=False,
                add_firewall=False,
                source_exe=src_exe,
            )
            self.assertEqual(len(launched), 2)
            self.assertTrue((target / "NTQ Remote.exe").is_file())
            self.assertTrue((target / "Go_Cai_Dat.bat").is_file())
            self.assertFalse(match_blocked_app("NTQ Remote.exe", ["ntq", "remote"]))

            # Lối tắt Tiếng Việt Unicode (.lnk) phải tạo được trên mọi locale Windows
            lnk_student = Path(tmpdir) / "Phòng Tin Học - Học Sinh.lnk"
            lnk_uninst = Path(tmpdir) / "Gỡ cài đặt Phòng Tin Học VN.lnk"
            create_windows_shortcut(
                target / "NTQ Remote.exe",
                lnk_student,
                "Phòng Tin Học - Học Sinh",
                arguments="--student",
            )
            create_windows_shortcut(
                target / "Go_Cai_Dat.bat",
                lnk_uninst,
                "Gỡ cài đặt Phòng Tin Học VN",
            )
            self.assertTrue(lnk_student.is_file() and lnk_student.stat().st_size > 100)
            self.assertTrue(lnk_uninst.is_file() and lnk_uninst.stat().st_size > 100)

    def test_audio_recorder_annotation_exam_and_device(self) -> None:
        # 1. Đóng gói khung âm thanh
        apkt = pack_screen_frame(BIN_TEACHER_AUDIO, b"\x01\x02\x03\x04")
        kind, hdr, payload = unpack_binary_packet(apkt)
        self.assertEqual(kind, BIN_TEACHER_AUDIO)
        self.assertIsNone(hdr)
        self.assertEqual(payload, b"\x01\x02\x03\x04")

        # 2. Ghi video MJPEG AVI thuần Python
        cap = ScreenCapturer()
        try:
            frame = cap.capture_jpeg(320, 180, 50)
        finally:
            cap.close()
        with tempfile.TemporaryDirectory() as tmpdir:
            avi_path = Path(tmpdir) / "test_rec.avi"
            writer = MjpegAviWriter(avi_path, 320, 180, fps=5)
            writer.write_jpeg_frame(frame)
            writer.write_jpeg_frame(frame)
            writer.close()
            raw = avi_path.read_bytes()
            self.assertTrue(raw.startswith(b"RIFF"))
            self.assertIn(b"AVI ", raw[:16])
            self.assertIn(b"idx1", raw)

        # 3. Smoke test giao diện Bảng vẽ & Đề kiểm tra
        ann = AnnotationController()
        ann.stop()
        ex_t = ExamTeacherDialog()
        ex_s = StudentExamDialog(
            "ex_t",
            "Kiểm tra",
            5,
            [{"question": "1+1?", "options": ["1", "2", "3", "4"]}],
        )
        ex_s._timer.stop()
        ex_s.close()
        ex_t.close()

        # 4. Kiểm tra hàm điều khiển USB (trả về True nếu Admin, hoặc thông báo rõ nếu không có Admin)
        ok_usb, msg_usb = set_usb_storage_blocked(False)
        self.assertIsInstance(ok_usb, bool)
        self.assertTrue(len(msg_usb) > 0)
        ok_audio, msg_audio = set_system_audio_muted(False)
        self.assertIsInstance(ok_audio, bool)
        self.assertTrue(len(msg_audio) > 0)

    def test_showcase_student_to_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            port = 48923
            server = TeacherServer(
                room_code="LOP-SHOWCASE",
                teacher_name="Thầy Nam",
                ws_port=port,
                enable_discovery=False,
                state_dir=Path(tmpdir) / "t_sc",
                require_license=False,
            )
            s1 = StudentClient(
                student_name="HS Trình Chiếu",
                manual_host="127.0.0.1",
                ws_port=port,
                enable_discovery=False,
                allow_power_commands=False,
                state_dir=Path(tmpdir) / "s1",
            )
            s2 = StudentClient(
                student_name="HS Khán Giả",
                manual_host="127.0.0.1",
                ws_port=port,
                enable_discovery=False,
                allow_power_commands=False,
                state_dir=Path(tmpdir) / "s2",
            )
            s2_state = {"broadcast": [], "frames": []}
            s2.signals.broadcast_changed.connect(lambda a: s2_state["broadcast"].append(a))
            s2.signals.broadcast_frame.connect(lambda d: s2_state["frames"].append(len(d)))

            server.start()
            time.sleep(0.3)
            s1.start()
            s2.start()
            try:
                ok = _pump_events(
                    self.app,
                    lambda: len(server.get_students_snapshot()) == 2,
                    timeout_sec=8.0,
                )
                self.assertTrue(ok)
                snaps = server.get_students_snapshot()
                presenter_id = next(
                    x["student_id"] for x in snaps if x["student_name"] == "HS Trình Chiếu"
                )
                server.start_showcase(presenter_id)
                self.assertTrue(
                    _pump_events(
                        self.app,
                        lambda: True in s2_state["broadcast"] and len(s2_state["frames"]) >= 1,
                        timeout_sec=6.0,
                    )
                )
                server.stop_showcase()
                self.assertTrue(_pump_events(self.app, lambda: False in s2_state["broadcast"]))
            finally:
                s1.stop()
                s2.stop()
                server.stop()

    def test_licensing_ed25519_and_max_students(self) -> None:
        hwid = get_hardware_id()
        self.assertTrue(hwid.startswith("PTH-"))

        repo_root = Path(__file__).resolve().parent.parent
        pem_path = repo_root / "QuanLyBanQuyen" / "private_key.pem"
        orig_defaults = verify_license_key.__defaults__
        with tempfile.TemporaryDirectory() as key_tmp:
            try:
                if not pem_path.is_file():
                    from cryptography.hazmat.primitives import serialization
                    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                        Ed25519PrivateKey,
                    )

                    priv = Ed25519PrivateKey.generate()
                    pem_path = Path(key_tmp) / "test_private.pem"
                    pem_path.write_bytes(
                        priv.private_bytes(
                            serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption(),
                        )
                    )
                    pub_raw = priv.public_key().public_bytes(
                        serialization.Encoding.Raw,
                        serialization.PublicFormat.Raw,
                    )
                    verify_license_key.__defaults__ = (None, pub_raw, None)

                valid_key = sign_license_key(
                    hwid, "Trường THCS Test", 1, "VINH_VIEN", private_key_path=pem_path
                )
                ok, info, _ = verify_license_key(valid_key, expected_hwid=hwid)
                self.assertTrue(ok)
                self.assertIsNotNone(info)
                self.assertEqual(info.max_students, 1)

                # Từ chối khi sai mã máy, sửa chữ ký hoặc hết hạn
                ok_wrong, _, _ = verify_license_key(
                    valid_key, expected_hwid="PTH-0000-0000-0000"
                )
                self.assertFalse(ok_wrong)

                tampered = valid_key[:-4] + "AAAA"
                ok_tamp, _, _ = verify_license_key(tampered, expected_hwid=hwid)
                self.assertFalse(ok_tamp)

                expired_key = sign_license_key(
                    hwid, "Trường Hết Hạn", 30, "2020-01-01", private_key_path=pem_path
                )
                ok_exp, _, _ = verify_license_key(expired_key, expected_hwid=hwid)
                self.assertFalse(ok_exp)

                # Kiểm tra giới hạn max_students=1 trên TeacherServer thật
                with tempfile.TemporaryDirectory() as tmpdir:
                    t_dir = Path(tmpdir) / "t_lic"
                    save_license_key(valid_key, t_dir)
                    ok_saved, _, _ = check_active_license(t_dir)
                    self.assertTrue(ok_saved)

                    port = 48924
                    server = TeacherServer(
                        room_code="LOP-LIC",
                        teacher_name="Cô Hoa",
                        ws_port=port,
                        enable_discovery=False,
                        state_dir=t_dir,
                        require_license=True,
                    )
                    s1 = StudentClient(
                        student_name="HS 1",
                        manual_host="127.0.0.1",
                        ws_port=port,
                        enable_discovery=False,
                        allow_power_commands=False,
                        state_dir=Path(tmpdir) / "s1_lic",
                    )
                    s2 = StudentClient(
                        student_name="HS 2",
                        manual_host="127.0.0.1",
                        ws_port=port,
                        enable_discovery=False,
                        allow_power_commands=False,
                        state_dir=Path(tmpdir) / "s2_lic",
                    )
                    s2_errors: list[str] = []
                    s2.signals.connection_changed.connect(
                        lambda ok_conn, msg: s2_errors.append(msg) if not ok_conn else None
                    )

                    server.start()
                    time.sleep(0.3)
                    s1.start()
                    try:
                        self.assertTrue(
                            _pump_events(
                                self.app, lambda: len(server.get_students_snapshot()) == 1
                            )
                        )
                        s2.start()
                        self.assertTrue(
                            _pump_events(
                                self.app,
                                lambda: any("giới hạn" in m for m in s2_errors),
                                timeout_sec=5.0,
                            )
                        )
                        self.assertEqual(len(server.get_students_snapshot()), 1)
                    finally:
                        s1.stop()
                        s2.stop()
                        server.stop()
            finally:
                verify_license_key.__defaults__ = orig_defaults

    def test_mobile_html_keygen_generates_valid_key(self) -> None:
        import shutil
        import subprocess

        node_exe = shutil.which("node")
        if not node_exe:
            self.skipTest("Không có Node.js để kiểm tra JS Ed25519")

        repo_root = Path(__file__).resolve().parent.parent
        pem_path = repo_root / "QuanLyBanQuyen" / "private_key.pem"
        orig_defaults = verify_license_key.__defaults__
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                if not pem_path.is_file():
                    from cryptography.hazmat.primitives import serialization
                    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                        Ed25519PrivateKey,
                    )

                    priv = Ed25519PrivateKey.generate()
                    pem_path = Path(tmpdir) / "test_mobile_private.pem"
                    pem_path.write_bytes(
                        priv.private_bytes(
                            serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption(),
                        )
                    )
                    pub_raw = priv.public_key().public_bytes(
                        serialization.Encoding.Raw,
                        serialization.PublicFormat.Raw,
                    )
                    verify_license_key.__defaults__ = (None, pub_raw, None)

                out_html = Path(tmpdir) / "CapBanQuyen_Test.html"
                build_mobile_html("TestPwd!2026", private_key_path=pem_path, output_path=out_html)
                js_script = (
                    f"const fs=require('fs');const h=fs.readFileSync({str(out_html)!r},'utf8');"
                    "const m=h.match(/<script>([\\s\\S]*?)<\\/script>/);"
                    "const f=new Function(m[1]+';return {unlockSeed,ed25519Sign,b64u};');"
                    "const api=f();"
                    "if(api.unlockSeed('sai')!==null)throw new Error('bad pwd accepted');"
                    "const s=api.unlockSeed('TestPwd!2026');"
                    "const p=new TextEncoder().encode(JSON.stringify({hwid:'PTH-AAAA-BBBB-CCCC',owner:'Mobile Test',max_students:30,expires_at:'VINH_VIEN',issued_at:'2026-11-22'}));"
                    "const sig=api.ed25519Sign(s,p);"
                    "console.log('PTH1.'+api.b64u(p)+'.'+api.b64u(sig));"
                )
                res = subprocess.run(
                    [node_exe, "-e", js_script],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                key = res.stdout.strip()
                ok, info, msg = verify_license_key(key, expected_hwid="PTH-AAAA-BBBB-CCCC")
                self.assertTrue(ok, msg)
                self.assertEqual(info.owner, "Mobile Test")
            finally:
                verify_license_key.__defaults__ = orig_defaults

    def test_adaptive_tier_auto_downgrade_and_upgrade(self) -> None:
        ctrl = AdaptiveTierController(initial_tier=0, downgrade_threshold=3, upgrade_threshold=4)
        self.assertEqual(ctrl.tier_index, 0)

        # 3 khung hình chậm/timeout liên tiếp -> tự hạ xuống bậc 1
        self.assertIsNone(ctrl.record_sample(0.05, 1))
        self.assertIsNone(ctrl.record_sample(0.05, 1))
        tier1 = ctrl.record_sample(0.05, 1)
        self.assertIsNotNone(tier1)
        self.assertEqual(ctrl.tier_index, 1)

        # 4 khung hình nhanh mượt liên tiếp -> tự nâng lại bậc 0
        for _ in range(3):
            self.assertIsNone(ctrl.record_sample(0.01, 0))
        tier0 = ctrl.record_sample(0.01, 0)
        self.assertIsNotNone(tier0)
        self.assertEqual(ctrl.tier_index, 0)

    def test_v2_icon_offline_cards_and_lan_update(self) -> None:
        # 1. Kiểm tra biểu tượng & version_info
        ico = load_app_icon()
        self.assertFalse(ico.isNull())
        self.assertTrue(Path(r"D:\PhongTinHocVN\version_info.txt").is_file())
        self.assertEqual(
            _get_arg_value(["--install-student", "--room", "PHONG-02"], "--room"),
            "PHONG-02",
        )

        # 2. Kiểm tra thẻ máy đang tắt (offline) & xóa/sửa vị trí
        with tempfile.TemporaryDirectory() as tmpdir:
            t_dir = Path(tmpdir) / "t_off"
            s_dir = Path(tmpdir) / "s_upd"
            from common.storage import save_teacher_state

            save_teacher_state(
                {
                    "known_pcs": {
                        "AA:BB:CC:DD:EE:01": {
                            "mac_address": "AA:BB:CC:DD:EE:01",
                            "pc_name": "MAY-01",
                            "last_ip": "192.168.1.101",
                            "seat_label": "Máy 01",
                        }
                    }
                },
                t_dir,
            )
            server = TeacherServer(
                ws_port=48925,
                enable_discovery=False,
                state_dir=t_dir,
                require_license=False,
            )
            t_win = TeacherMainWindow(server)
            self.app.processEvents()
            self.assertIn("AA:BB:CC:DD:EE:01", t_win._offline_cards)
            self.assertTrue(t_win._offline_cards["AA:BB:CC:DD:EE:01"].is_offline)
            t_win._on_remove_offline_mac("AA:BB:CC:DD:EE:01")
            self.assertNotIn("AA:BB:CC:DD:EE:01", t_win._offline_cards)

            # 3. Kiểm tra truyền gói cập nhật qua LAN + SHA-256 + tạo script cập nhật
            fake_exe = Path(tmpdir) / "NTQ Remote.exe"
            fake_exe.write_bytes(b"MZ_FAKE_NEW_VERSION_2_0")
            self.assertTrue(
                verify_sha256(
                    fake_exe,
                    __import__("hashlib").sha256(b"MZ_FAKE_NEW_VERSION_2_0").hexdigest(),
                )
            )
            bat = prepare_self_update_script(
                fake_exe, Path(tmpdir) / "Target.exe", work_dir=Path(tmpdir)
            )
            self.assertTrue(bat.is_file())
            self.assertIn("--student", bat.read_text(encoding="utf-8"))

            client = StudentClient(
                manual_host="127.0.0.1",
                ws_port=48925,
                enable_discovery=False,
                allow_power_commands=False,
                state_dir=s_dir,
            )
            upd_msgs: list[str] = []
            client.signals.status_message.connect(lambda m: upd_msgs.append(m))
            client.start()
            try:
                self.assertTrue(
                    _pump_events(self.app, lambda: len(server.get_students_snapshot()) == 1)
                )
                server.distribute_update(None, str(fake_exe))
                self.assertTrue(
                    _pump_events(
                        self.app,
                        lambda: any("SHA-256 OK" in m for m in upd_msgs),
                        timeout_sec=6.0,
                    )
                )
            finally:
                client.stop()
                t_win.close()
                self.app.processEvents()

    def test_online_ota_updater_manifest_and_download(self) -> None:
        import functools
        import http.server
        import socketserver
        import threading

        self.assertEqual(parse_version("v2.1.3"), (2, 1, 3))
        self.assertTrue(is_newer_version("2.1.0", "2.0.0"))
        self.assertFalse(is_newer_version("2.0.0", "2.0.0"))
        self.assertFalse(is_newer_version("1.9.9", "2.0.0"))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            web_dir = root / "web"
            web_dir.mkdir()
            fake_payload = b"MZ_FAKE_NTQ_REMOTE_v2_1_0" * 500
            exe_file = web_dir / "NTQ_Remote.exe"
            exe_file.write_bytes(fake_payload)
            sha = compute_sha256(exe_file)

            class QuietHandler(http.server.SimpleHTTPRequestHandler):
                def log_message(self, format, *args):
                    pass

            handler = functools.partial(QuietHandler, directory=str(web_dir))
            httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                dl_url = f"http://127.0.0.1:{port}/NTQ_Remote.exe"
                manifest_path = write_release_manifest(
                    exe_file,
                    web_dir / "version.json",
                    version="2.1.0",
                    download_url=dl_url,
                    notes="Sửa lỗi và bổ sung OTA",
                )
                self.assertTrue(manifest_path.is_file())

                manifest = fetch_update_manifest(f"http://127.0.0.1:{port}/version.json")
                self.assertEqual(manifest["version"], "2.1.0")
                self.assertEqual(manifest["sha256"], sha)

                progress_ticks: list[tuple[int, int]] = []
                got_exe = download_update_exe(
                    manifest["download_url"],
                    expected_sha256=manifest["sha256"],
                    dest_dir=root / "dl",
                    progress_cb=lambda g, tot: progress_ticks.append((g, tot)),
                )
                self.assertTrue(got_exe.is_file())
                self.assertEqual(got_exe.read_bytes(), fake_payload)
                self.assertGreaterEqual(len(progress_ticks), 1)

                with self.assertRaises(ValueError):
                    download_update_exe(
                        manifest["download_url"],
                        expected_sha256="0" * 64,
                        dest_dir=root / "dl_bad",
                    )

                srv = TeacherServer(
                    ws_port=48926,
                    enable_discovery=False,
                    state_dir=root / "t_ota",
                    require_license=False,
                )
                srv._students["s_old"] = StudentInfo("s_old", "PC-01", "An", "127.0.0.1", app_version="1.9.0")
                srv._students["s_new"] = StudentInfo("s_new", "PC-02", "Bình", "127.0.0.1", app_version="2.0.0")
                self.assertEqual(srv.get_outdated_student_ids("2.0.0"), ["s_old"])

                srv.set_update_settings(f"http://127.0.0.1:{port}/version.json", False)
                dlg = OnlineUpdateDialog(srv, initial_manifest=manifest)
                self.app.processEvents()
                self.assertTrue(dlg.btn_download.isEnabled())
                self.assertIn("2.1.0", dlg.lbl_result.text())
                dlg.close()
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_release_publisher_config_and_github_release_mock(self) -> None:
        import http.server
        import json
        import socketserver
        import threading

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            save_publisher_config(
                {
                    "github_repo": "ntq-tech-95/ntq-remote",
                    "github_token": "ghp_test_token_123",
                    "cf_account_id": "acc_123",
                    "cf_api_token": "cf_tok_123",
                    "cf_pages_project": "phongtin-key",
                },
                base_dir=root,
            )
            cfg = load_publisher_config(base_dir=root)
            self.assertEqual(cfg["github_repo"], "ntq-tech-95/ntq-remote")
            self.assertEqual(cfg["cf_pages_project"], "phongtin-key")

            state = {"release_created": False, "uploaded": {}, "deleted": []}

            class MockGitHubHandler(http.server.BaseHTTPRequestHandler):
                def log_message(self, format, *args):
                    pass

                def _send_json(self, code: int, obj: dict) -> None:
                    raw = json.dumps(obj).encode("utf-8")
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

                def do_GET(self):
                    if not state["release_created"]:
                        self._send_json(404, {"message": "Not Found"})
                    else:
                        self._send_json(
                            200,
                            {
                                "id": 77,
                                "html_url": "https://github.com/ntq-tech-95/ntq-remote/releases/tag/v2.0.0",
                                "assets": [{"id": 99, "name": "NTQ-Remote.exe"}],
                            },
                        )

                def do_POST(self):
                    length = int(self.headers.get("Content-Length") or 0)
                    body = self.rfile.read(length)
                    if self.path.endswith("/releases"):
                        state["release_created"] = True
                        self._send_json(
                            201,
                            {
                                "id": 77,
                                "html_url": "https://github.com/ntq-tech-95/ntq-remote/releases/tag/v2.0.0",
                                "assets": [],
                            },
                        )
                    elif "/assets?name=" in self.path:
                        name = self.path.split("name=")[-1]
                        state["uploaded"][name] = body
                        self._send_json(
                            201,
                            {"browser_download_url": f"https://example.test/{name}"},
                        )

                def do_DELETE(self):
                    state["deleted"].append(self.path)
                    self.send_response(204)
                    self.end_headers()

            httpd = socketserver.TCPServer(("127.0.0.1", 0), MockGitHubHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                fake_exe = root / "NTQ-Remote.exe"
                fake_exe.write_bytes(b"FAKE_EXE_BYTES")
                res1 = create_or_update_github_release(
                    "ntq-tech-95/ntq-remote",
                    "ghp_test",
                    "v2.0.0",
                    "NTQ Remote v2.0.0",
                    "Release 1",
                    [fake_exe],
                    api_base=f"http://127.0.0.1:{port}",
                    uploads_base=f"http://127.0.0.1:{port}",
                )
                self.assertEqual(res1["release_id"], 77)
                self.assertEqual(state["uploaded"]["NTQ-Remote.exe"], b"FAKE_EXE_BYTES")

                res2 = create_or_update_github_release(
                    "ntq-tech-95/ntq-remote",
                    "ghp_test",
                    "2.0.0",
                    "NTQ Remote v2.0.0",
                    "Release 2",
                    [fake_exe],
                    api_base=f"http://127.0.0.1:{port}",
                    uploads_base=f"http://127.0.0.1:{port}",
                )
                self.assertEqual(len(state["deleted"]), 1)
                self.assertEqual(res2["assets"]["NTQ-Remote.exe"], "https://example.test/NTQ-Remote.exe")
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
