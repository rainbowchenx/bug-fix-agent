"""Agent-1 公开入口：原始缺陷 → ``defect-batch``。

``preloaded`` 模式加载 CSV/JSON/xlsx 派生载荷，再跑确定性的蒸馏 / 筛选 / 分簇
（不调 LLM）。``mcp`` / ``crawler`` 拉取模式仍为 stub，待生产缺陷 MCP 就绪。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional, Union

from bugfix_contracts.defect_batch import (
    DefectBatch,
    DefectBatchInput,
    RawDefect,
    validate_defect_batch,
)
from bugfix_agent1.defect_batch.prepare import prepare_defect_batch
from bugfix_agent1.defect_batch.rules import ScreenProfile
from bugfix_agent1.ingest.preloaded import load_preloaded
from bugfix_agent1.ingest.project import resolve_product_line


def load_defect_batch(value: DefectBatchInput) -> DefectBatch:
    from bugfix_contracts.defect_batch import load_defect_batch as _impl

    return _impl(value)


def run_defect_batch_prepare(
    *,
    product_line: Optional[str] = None,
    mode: Literal["preloaded", "mcp", "crawler"] = "preloaded",
    source: Optional[Union[str, Path, dict[str, Any], list[Any]]] = None,
    defects: Optional[list[RawDefect]] = None,
    posture: Literal["alpha", "beta"] = "beta",
    profile: Optional[ScreenProfile] = None,
) -> DefectBatch:
    """加载原始缺陷并制备 ``defect-batch``。

    供 CLI ``prepare-batch`` 与 ``defect-batch-prepare`` skill 调用。

    Args:
        product_line: 批次命名空间。写入 ``defect-batch.productLine``，并参与
            ``clusterId``（``{line}::{module}::{tag}::{intent}``）。为 None 时
            按 :func:`resolve_product_line` 派生（文件名里的项目号等），不打断
            调用方。
        mode: Ingest 方式。当前仅 ``preloaded`` 可用；``mcp`` / ``crawler``
            仍为 stub。
        source: ``preloaded`` 且未给 ``defects`` 时的原始载荷。可为文件路径
            （平台 CSV / ``raw-defects`` JSON / 缺陷列表 JSON）、内存 dict
            （含 ``defects`` 的文件对象，或单条平台行 / canonical 行）、或
            缺陷 dict 列表。与 ``defects`` 二选一。
        defects: 已归一的 ``RawDefect`` 列表。有则跳过 Ingest，直接进蒸馏。
        posture: 筛选姿态。``beta`` 时非 Open/New 状态进 ``excluded``；
            ``alpha`` 不过这条状态门。写入产物 ``defect-batch.posture``。
        profile: 可选筛池规则覆盖（空模板、端侧/非代码正则等）。默认
            ``ScreenProfile()``。

    Returns:
        校验通过的 ``DefectBatch``。

    Raises:
        NotImplementedError: ``mode`` 为 ``mcp`` 或 ``crawler``。
        ValueError: ``preloaded`` 模式下 ``source`` 与 ``defects`` 都未提供。
    """
    if mode != "preloaded":
        raise NotImplementedError(f"ingest mode {mode!r} is stubbed; use preloaded")
    product_line, _ = resolve_product_line(source, product_line)
    if defects is None:
        if source is None:
            raise ValueError("source or defects is required for preloaded mode")
        defects = load_preloaded(source)
    return prepare_defect_batch(
        product_line=product_line,
        defects=defects,
        posture=posture,
        profile=profile,
    )
