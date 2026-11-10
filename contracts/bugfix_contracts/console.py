"""控制台输出编码统一。

Windows 上 ``sys.stdout`` 默认用系统 locale（cp936），而消费这些输出的平台/日志
按 UTF-8 解码。同一份输出里 ASCII 没问题，中文与 ``→`` 这类符号就会变成乱码 ——
而乱码恰好出现在最需要人读的地方（``--help``、argparse 报错、诊断行）。

``preflight`` 曾经单独做过这件事，于是同一支 CLI 里两套编码：preflight 的中文对，
其它命令的中文错。这个模块是那件事的唯一实现，两个 CLI 入口在 argparse 之前调用。

``PYTHONIOENCODING`` 若已显式设置则尊重用户，不覆盖。
"""

from __future__ import annotations

import os
import sys


def force_utf8_console() -> None:
    """把 stdout / stderr 切到 UTF-8（幂等，失败不致命）。"""
    if os.environ.get("PYTHONIOENCODING"):
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if (getattr(stream, "encoding", "") or "").lower().replace("-", "") == "utf8":
                continue
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
