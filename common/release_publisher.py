"""Công cụ 1 chạm tự động đóng gói, đẩy GitHub Releases và cập nhật Cloudflare Pages."""

import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from common.config import APP_VERSION
from common.network import get_app_data_dir
from common.updater import sync_app_version_files, write_release_manifest

DEFAULT_GITHUB_REPO = "ntq-tech-95/ntq-remote"
DEFAULT_CF_PROJECT = "phongtin-key"


def get_publisher_config_path(base_dir: Path | None = None) -> Path:
    """Lưu cấu hình & Token phát hành ngoài thư mục mã nguồn (tránh lộ lên GitHub)."""
    root = base_dir or get_app_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / "publisher_secrets.json"


def load_publisher_config(base_dir: Path | None = None) -> dict[str, str]:
    """Đọc cấu hình phát hành đã lưu tại máy tác giả."""
    path = get_publisher_config_path(base_dir)
    defaults = {
        "github_repo": DEFAULT_GITHUB_REPO,
        "github_token": "",
        "cf_account_id": "",
        "cf_api_token": "",
        "cf_pages_project": DEFAULT_CF_PROJECT,
    }
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for k in defaults:
                    if k in loaded and str(loaded[k]).strip():
                        defaults[k] = str(loaded[k]).strip()
        except (OSError, json.JSONDecodeError):
            pass

    # Cho phép ghi đè qua biến môi trường nếu có
    env_map = {
        "github_token": "GITHUB_TOKEN",
        "github_repo": "GITHUB_REPOSITORY",
        "cf_account_id": "CLOUDFLARE_ACCOUNT_ID",
        "cf_api_token": "CLOUDFLARE_API_TOKEN",
        "cf_pages_project": "CF_PAGES_PROJECT",
    }
    for key, env_name in env_map.items():
        val = os.environ.get(env_name, "").strip()
        if val:
            defaults[key] = val
    return defaults


def save_publisher_config(cfg: dict[str, str], base_dir: Path | None = None) -> Path:
    """Lưu cấu hình phát hành vào AppData cục bộ."""
    path = get_publisher_config_path(base_dir)
    clean = {k: str(v).strip() for k, v in cfg.items()}
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _gh_request(
    method: str,
    url: str,
    token: str,
    json_body: dict[str, Any] | None = None,
    raw_data: bytes | None = None,
    content_type: str = "application/json",
    timeout: float = 30.0,
) -> tuple[int, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": f"NTQ-Remote-Publisher/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif raw_data is not None:
        data = raw_data
        headers["Content-Type"] = content_type

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as err:
        try:
            err_text = err.read().decode("utf-8", errors="replace")
            code = err.code
        finally:
            err.close()
        try:
            err_obj = json.loads(err_text)
        except json.JSONDecodeError:
            err_obj = {"message": err_text}
        return code, err_obj


def create_or_update_github_release(
    repo: str,
    token: str,
    tag_name: str,
    release_title: str,
    notes: str,
    assets: list[Path],
    api_base: str = "https://api.github.com",
    uploads_base: str = "https://uploads.github.com",
) -> dict[str, Any]:
    """Tạo (hoặc cập nhật) GitHub Release và tải lên các tệp EXE / version.json."""
    owner_repo = repo.strip().strip("/")
    tag = tag_name if tag_name.startswith("v") else f"v{tag_name}"

    status, rel = _gh_request(
        "GET", f"{api_base}/repos/{owner_repo}/releases/tags/{tag}", token
    )
    if status == 404:
        status, rel = _gh_request(
            "POST",
            f"{api_base}/repos/{owner_repo}/releases",
            token,
            json_body={
                "tag_name": tag,
                "name": release_title,
                "body": notes,
                "draft": False,
                "prerelease": False,
            },
        )
        if status not in (200, 201):
            raise RuntimeError(f"Không tạo được GitHub Release ({status}): {rel}")
    elif status != 200:
        raise RuntimeError(f"Lỗi truy vấn GitHub Release ({status}): {rel}")

    release_id = rel["id"]
    existing_assets = {a["name"]: a["id"] for a in rel.get("assets", [])}
    uploaded_urls: dict[str, str] = {}

    for asset_path in assets:
        name = asset_path.name
        if name in existing_assets:
            _gh_request(
                "DELETE",
                f"{api_base}/repos/{owner_repo}/releases/assets/{existing_assets[name]}",
                token,
            )
        encoded_name = urllib.parse.quote(name)
        up_url = (
            f"{uploads_base}/repos/{owner_repo}/releases/{release_id}"
            f"/assets?name={encoded_name}"
        )
        up_status, up_res = _gh_request(
            "POST",
            up_url,
            token,
            raw_data=asset_path.read_bytes(),
            content_type="application/octet-stream",
            timeout=300.0,
        )
        if up_status not in (200, 201):
            raise RuntimeError(f"Tải tệp '{name}' lên Release thất bại ({up_status}): {up_res}")
        uploaded_urls[name] = str(up_res.get("browser_download_url") or "")

    return {
        "release_id": release_id,
        "html_url": str(rel.get("html_url") or ""),
        "assets": uploaded_urls,
    }


def clean_token_input(raw: str) -> str:
    """Làm sạch token nếu vô tình dán thừa dấu ngoặc, khoảng trắng hoặc 'Bearer '."""
    val = str(raw or "").strip().strip('"').strip("'").strip()
    if "=" in val and val.split("=", 1)[0].strip().isupper():
        val = val.split("=", 1)[1].strip()
    if val.lower().startswith("bearer "):
        val = val[7:].strip()
    return val


def verify_cloudflare_token(account_id: str, api_token: str) -> tuple[bool, str]:
    """Kiểm tra nhanh định dạng và quyền của CLOUDFLARE_API_TOKEN qua Cloudflare API."""
    tok = clean_token_input(api_token)
    if len(tok) < 25 or not tok.isascii() or any(c.isspace() for c in tok):
        return (
            False,
            f"Token Cloudflare hiện tại không đúng định dạng (chỉ dài {len(tok)} ký tự; "
            "Token thật của Cloudflare thường dài khoảng 40 ký tự).",
        )
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{account_id}/pages/projects",
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
            "User-Agent": f"NTQ-Remote-Publisher/{APP_VERSION}",
        },
        method="GET",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=12.0, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if data.get("success"):
                return True, "Hợp lệ"
            return False, f"Cloudflare từ chối token: {data.get('errors')}"
    except urllib.error.HTTPError as err:
        try:
            err_body = err.read().decode("utf-8", errors="replace")
            code = err.code
        finally:
            err.close()
        return False, f"Cloudflare báo lỗi ({code}): {err_body[:180]}"
    except Exception as exc:
        return True, f"Không kiểm tra trước được do lỗi mạng ({exc}), tiếp tục thử đẩy..."


def deploy_cloudflare_pages(
    upload_dir: Path,
    project_name: str,
    account_id: str,
    api_token: str,
) -> None:
    """Đẩy thư mục WebCapKey_Upload (chứa index.html & version.json) lên Cloudflare Pages."""
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        raise FileNotFoundError("Không tìm thấy Node.js / npx để chạy Wrangler.")
    env = os.environ.copy()
    env["CLOUDFLARE_ACCOUNT_ID"] = account_id.strip()
    env["CLOUDFLARE_API_TOKEN"] = clean_token_input(api_token)
    cmd = [
        npx,
        "--yes",
        "wrangler",
        "pages",
        "deploy",
        str(upload_dir),
        f"--project-name={project_name}",
        "--commit-dirty=true",
    ]
    res = subprocess.run(cmd, env=env, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Triển khai Cloudflare Pages thất bại (mã {res.returncode}).")


def _prompt_if_missing(cfg: dict[str, str], interactive: bool) -> dict[str, str]:
    changed = False
    if not interactive:
        return cfg

    if not cfg["github_token"]:
        print("\n--- Thiet lap lan dau: GitHub Token ---")
        print("Tao tai: https://github.com/settings/tokens/new (tich quyen 'repo')")
        cfg["github_token"] = clean_token_input(
            input("Dan GitHub Personal Access Token (ghp_...): ")
        )
        changed = True
    if not cfg["cf_account_id"]:
        print("\n--- Thiet lap lan dau: Cloudflare Account ID ---")
        cfg["cf_account_id"] = clean_token_input(input("Dan CLOUDFLARE_ACCOUNT_ID (32 ky tu): "))
        changed = True

    while True:
        if not cfg["cf_api_token"]:
            print("\n--- Thiet lap Cloudflare API Token (chuoi dai ~40 ky tu) ---")
            print("Luu y: Dan dung chuoi Token khi bam 'Create Token', KHONG dan ten Token.")
            cfg["cf_api_token"] = clean_token_input(input("Dan CLOUDFLARE_API_TOKEN: "))
            changed = True
        ok_cf, cf_msg = verify_cloudflare_token(cfg["cf_account_id"], cfg["cf_api_token"])
        if ok_cf:
            break
        print(f"\n[CANH BAO] {cf_msg}")
        cfg["cf_api_token"] = clean_token_input(
            input("Dan lai CLOUDFLARE_API_TOKEN moi (hoac Enter de huy): ")
        )
        if not cfg["cf_api_token"]:
            raise RuntimeError(cf_msg)
        changed = True

    if changed:
        save_path = save_publisher_config(cfg)
        print(f"Da luu cau hinh an toan tai: {save_path} (khong nam trong thu muc Git).\n")
    return cfg


def run_publish_pipeline(
    version: str,
    notes: str = "",
    project_root: Path | None = None,
    skip_tests: bool = False,
    reuse_exe: bool = False,
    interactive: bool = True,
) -> None:
    """Thực thi trọn gói: kiểm thử -> đóng gói EXE -> GitHub Release -> Cloudflare Pages."""
    root = project_root or Path(__file__).resolve().parent.parent
    cfg = _prompt_if_missing(load_publisher_config(), interactive=interactive)
    for req_key in ("github_token", "cf_account_id", "cf_api_token"):
        if not cfg.get(req_key):
            raise ValueError(f"Thiếu thông tin cấu hình '{req_key}'.")

    ver_3, _ = sync_app_version_files(version, root)
    tag = f"v{ver_3}"
    release_notes = notes.strip() or f"Phát hành NTQ Remote {tag}"

    py_exe = root / ".venv" / "Scripts" / "python.exe"
    python_bin = str(py_exe if py_exe.is_file() else sys.executable)

    if not skip_tests:
        print(f"[1/6] Đang chạy toàn bộ kiểm thử tự động cho v{ver_3}...")
        subprocess.run(
            [python_bin, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=str(root),
            check=True,
        )

    raw_exe = root / "BoCaiDat" / "NTQ Remote.exe"
    if not (reuse_exe and raw_exe.is_file()):
        print(f"[2/6] Đang đóng gói NTQ Remote.exe v{ver_3}...")
        env = os.environ.copy()
        env["NO_PAUSE"] = "1"
        subprocess.run(
            ["cmd", "/c", str(root / "Dong_Goi_EXE.bat")],
            cwd=str(root),
            env=env,
            check=True,
        )
    else:
        print(f"[2/6] Dùng lại tệp có sẵn: {raw_exe}")

    upload_exe = root / "BoCaiDat" / "NTQ-Remote.exe"
    shutil.copy2(raw_exe, upload_exe)

    manifest_path = root / "QuanLyBanQuyen" / "WebCapKey_Upload" / "version.json"
    dl_url = f"https://github.com/{cfg['github_repo']}/releases/download/{tag}/NTQ-Remote.exe"
    print(f"[3/6] Tạo version.json (SHA-256 & link tải {dl_url})...")
    write_release_manifest(
        upload_exe,
        manifest_path,
        version=ver_3,
        download_url=dl_url,
        notes=release_notes,
    )

    if (root / ".git").exists():
        print("[4/6] Đang đồng bộ mã nguồn lên GitHub...")
        subprocess.run(["git", "add", "-A"], cwd=str(root), check=True)
        diff_res = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(root))
        if diff_res.returncode != 0:
            subprocess.run(
                ["git", "commit", "-m", f"Phat hanh NTQ Remote {tag}: {release_notes}"],
                cwd=str(root),
                check=True,
            )
        subprocess.run(["git", "tag", "-f", tag], cwd=str(root), check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(root), check=True)
        subprocess.run(["git", "push", "origin", tag, "--force"], cwd=str(root), check=True)

    print(f"[5/6] Đang tải NTQ-Remote.exe lên GitHub Release {tag}...")
    rel_info = create_or_update_github_release(
        repo=cfg["github_repo"],
        token=cfg["github_token"],
        tag_name=tag,
        release_title=f"NTQ Remote {tag}",
        notes=release_notes,
        assets=[upload_exe, manifest_path],
    )
    print(f"   -> GitHub Release: {rel_info['html_url']}")

    print(f"[6/6] Đang cập nhật https://{cfg['cf_pages_project']}.pages.dev/version.json...")
    deploy_cloudflare_pages(
        upload_dir=root / "QuanLyBanQuyen" / "WebCapKey_Upload",
        project_name=cfg["cf_pages_project"],
        account_id=cfg["cf_account_id"],
        api_token=cfg["cf_api_token"],
    )
    print("\n=== PHÁT HÀNH THÀNH CÔNG HOÀN TOÀN! ===")
    print(f"Link tải EXE: {dl_url}")
    print(f"Manifest OTA: https://{cfg['cf_pages_project']}.pages.dev/version.json")


def deploy_cloudflare_only(project_root: Path | None = None, interactive: bool = True) -> None:
    """Chỉ chạy lại bước đẩy WebCapKey_Upload (version.json) lên Cloudflare Pages."""
    root = project_root or Path(__file__).resolve().parent.parent
    cfg = _prompt_if_missing(load_publisher_config(), interactive=interactive)
    print(f"Đang cập nhật https://{cfg['cf_pages_project']}.pages.dev/version.json...")
    deploy_cloudflare_pages(
        upload_dir=root / "QuanLyBanQuyen" / "WebCapKey_Upload",
        project_name=cfg["cf_pages_project"],
        account_id=cfg["cf_account_id"],
        api_token=cfg["cf_api_token"],
    )
    print(f"\n=== ĐẨY CLOUDFLARE THÀNH CÔNG: https://{cfg['cf_pages_project']}.pages.dev/version.json ===")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Phát hành NTQ Remote 1 chạm (Hướng A)")
    parser.add_argument("--version", default="", help="Số phiên bản (VD: 2.0.0)")
    parser.add_argument("--notes", default="", help="Ghi chú thay đổi")
    parser.add_argument("--skip-tests", action="store_true", help="Bỏ qua bước unittest")
    parser.add_argument("--reuse-exe", action="store_true", help="Dùng lại EXE vừa build")
    parser.add_argument("--cf-only", action="store_true", help="Chỉ đẩy lại version.json lên Cloudflare")
    parser.add_argument("--reset-tokens", action="store_true", help="Nhập lại Token GitHub/Cloudflare")
    ns = parser.parse_args()

    if ns.reset_tokens:
        p = get_publisher_config_path()
        p.unlink(missing_ok=True)
        print(f"Đã xóa cấu hình token cũ tại {p}")

    if ns.cf_only:
        deploy_cloudflare_only(interactive=True)
        sys.exit(0)

    ver = ns.version.strip()
    if not ver:
        ver = input(f"Nhập phiên bản muốn phát hành [mặc định {APP_VERSION}]: ").strip() or APP_VERSION
    notes_val = ns.notes.strip()
    if not ns.version and not notes_val:
        notes_val = input("Ghi chú bản phát hành (Enter để dùng mặc định): ").strip()

    run_publish_pipeline(
        version=ver,
        notes=notes_val,
        skip_tests=ns.skip_tests,
        reuse_exe=ns.reuse_exe,
        interactive=True,
    )
