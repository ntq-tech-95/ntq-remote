"""Xác minh và áp dụng bản cập nhật NTQ Remote (tái sử dụng từ common.updater)."""

from common.updater import (
    get_update_dir,
    launch_detached_updater,
    prepare_self_update_script,
    verify_sha256,
)

__all__ = [
    "get_update_dir",
    "launch_detached_updater",
    "prepare_self_update_script",
    "verify_sha256",
]
