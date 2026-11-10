"""``productLine`` 的派生：能用文件名/文件字段定，就别打断人。

``productLine`` 不是导出里的字段，也不是仓型（仓型是 Agent-2 的
``cartographyProfile``）。它只是一个**批次命名空间**：写进产物，并作为
``clusterId`` 的前缀。既然是命名空间，稳定且唯一就够了，不必问人。

优先级（高 → 低）：

1. ``--product-line`` 显式给的
2. ``BUGFIX_PRODUCT_LINE`` 环境变量
3. ``raw-defects`` JSON 里的 ``productLine``（文件级，再退到单条票）
4. 源文件名里的项目号（``PJ01PM20260711040-当前处理人-….csv``）
5. 兜底 ``unspecified`` —— 落盘可继续跑，但 stderr 会点名

第 3 条在旧版是死字段：``xlsx-to-raw --product-line X`` 写进去，下游从不读。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

__all__ = ["PRODUCT_LINE_ENV", "FALLBACK_PRODUCT_LINE", "project_code_from_name", "resolve_product_line"]

# 项目号形如 PJ01PM20260711040 / PJ14PD20260423284：两个字母 + 两位 + 两个字母 + 至少 6 位数字。
PROJECT_CODE_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2}\d{2}[A-Z]{2}\d{6,})(?![0-9])")

PRODUCT_LINE_ENV = "BUGFIX_PRODUCT_LINE"
FALLBACK_PRODUCT_LINE = "unspecified"


def project_code_from_name(name: str) -> Optional[str]:
    """从文件名/路径里捞项目号。没有就返回 None。"""
    m = PROJECT_CODE_RE.search(Path(name).name)
    return m.group(1) if m else None


def _from_json_file(path: Path) -> tuple[Optional[str], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, ""
    if isinstance(payload, dict):
        top = payload.get("productLine")
        if isinstance(top, str) and top.strip():
            return top.strip(), "raw-defects productLine"
        defects = payload.get("defects")
        if isinstance(defects, list):
            for item in defects:
                if isinstance(item, dict):
                    val = item.get("productLine")
                    if isinstance(val, str) and val.strip():
                        return val.strip(), "raw-defects defect productLine"
    return None, ""


def resolve_product_line(
    source: Any = None,
    explicit: Optional[str] = None,
    *,
    warn: bool = True,
) -> tuple[str, str]:
    """定下这批的 ``productLine``，返回 ``(值, 出处)``。

    ``出处`` 用于在 CLI 上说明它从哪来（``--product-line`` / env /
    ``raw-defects productLine`` / ``filename`` / ``fallback``），这样产物里的
    前缀不是凭空出现的。

    Args:
        source: 源文件路径（CSV / JSON / xlsx）或已加载的载荷；可为 None。
        explicit: 调用方显式给的值，优先级最高。
        warn: 落到兜底值时是否在 stderr 点名。

    Returns:
        ``(product_line, provenance)``。
    """
    if explicit and explicit.strip():
        return explicit.strip(), "--product-line"

    env = (os.environ.get(PRODUCT_LINE_ENV) or "").strip()
    if env:
        return env, PRODUCT_LINE_ENV

    path: Optional[Path] = None
    if isinstance(source, (str, Path)):
        path = Path(source)

    if path is not None and path.suffix.lower() == ".json":
        val, why = _from_json_file(path)
        if val:
            return val, why

    if path is not None:
        code = project_code_from_name(str(path))
        if code:
            return code, "filename"

    if warn:
        print(
            f"productLine: {FALLBACK_PRODUCT_LINE!r} (no --product-line, no "
            f"{PRODUCT_LINE_ENV}, no project code in the source name). "
            f"Set one of them so clusterId prefixes stay comparable across batches.",
            file=sys.stderr,
        )
    return FALLBACK_PRODUCT_LINE, "fallback"
