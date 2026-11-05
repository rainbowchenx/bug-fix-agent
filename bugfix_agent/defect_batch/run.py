"""Agent-1 公开入口：原始缺陷 → ``defect-batch``。

``preloaded`` 模式加载 CSV/JSON/xlsx 派生载荷，再跑确定性的蒸馏 / 筛选 / 分簇
（不调 LLM）。``mcp`` / ``crawler`` 拉取模式仍为 stub，待生产缺陷 MCP 就绪。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional, Union

from bugfix_agent.contracts.defect_batch import DefectBatch, RawDefect
from bugfix_agent.defect_batch.prepare import prepare_defect_batch
from bugfix_agent.defect_batch.rules import ScreenProfile
from bugfix_agent.ingest.preloaded import load_preloaded


def run_defect_batch_prepare(
    *,
    product_line: str,
    mode: Literal["preloaded", "mcp", "crawler"] = "preloaded",
    source: Optional[Union[str, Path, dict[str, Any], list[Any]]] = None,
    defects: Optional[list[RawDefect]] = None,
    posture: Literal["alpha", "beta"] = "beta",
    profile: Optional[ScreenProfile] = None,
) -> DefectBatch:
    """加载（可选）+ 制备；供 CLI ``prepare-batch`` 与图节点 agent1 调用。"""
    if mode != "preloaded":
        raise NotImplementedError(f"ingest mode {mode!r} is stubbed; use preloaded")
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
