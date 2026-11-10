"""这份可执行文件是从哪个 commit 编出来的。

没有这个，日志无法自证版本。实测过的代价：团队连续三轮拿着旧包跑，报告里
看不出区别，因为唯一能证明版本的是 ``self-check``，而它只在有人想起来时才被调用
（三轮里只调了一次）。把这一行打进每次运行的常规输出里，版本就不再靠自觉。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def manifest_path() -> Path:
    """``VENDOR.json`` 的位置：onefile 打包后在 ``_MEIPASS``，源码树里在包的上层。"""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "VENDOR.json"
    return Path(__file__).resolve().parents[1] / "VENDOR.json"


def load_manifest() -> dict[str, Any] | None:
    path = manifest_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_stamp() -> str:
    """一行版本身份：``<commit> · vendor N files · frozen|dev``。"""
    manifest = load_manifest()
    if manifest is None:
        try:
            from bugfix_agent1 import __version__
        except Exception:  # pragma: no cover - 版本模块缺失时仍要能打
            __version__ = "unknown"
        return f"source checkout (v{__version__}, no VENDOR.json)"
    mode = "frozen" if getattr(sys, "frozen", False) else "dev"
    return f"{manifest.get('commit', '?')} · vendor {len(manifest.get('files', {}))} files · {mode}"
