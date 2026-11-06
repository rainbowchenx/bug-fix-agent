"""Agent 之间的 Pydantic 硬门禁。

各 ``require_*`` 包装契约层的 ``safe_validate_*``；校验失败抛出
``ArtifactValidationError``。父图的 ``validate_*`` 节点捕获后写入
``ok=False`` / ``stage`` / ``error``，并以 ``Command(goto=END)`` 结束。

禁止 Agent 互相 import 内部实现——跨段只允许这些产物类型
（defect-batch → code-knowledge → analysis-report）。
"""

from __future__ import annotations

from typing import Any

from bugfix_agent.contracts import (
    AnalysisReport,
    CodeKnowledge,
    DefectBatch,
    safe_validate_analysis_report,
    safe_validate_code_knowledge,
    safe_validate_defect_batch,
)


class ArtifactValidationError(Exception):
    """跨 Agent 产物未通过 schema 校验时抛出。"""

    def __init__(self, artifact: str, detail: str):
        self.artifact = artifact
        self.detail = detail
        super().__init__(f"{artifact} validation failed: {detail}")


def require_defect_batch(data: Any) -> DefectBatch:
    """Agent-1 出口门禁：原始 dict → ``DefectBatch``，失败则抛错。"""
    ok, result = safe_validate_defect_batch(data)
    if not ok:
        raise ArtifactValidationError("defect-batch", str(result))
    assert isinstance(result, DefectBatch)
    return result


def require_code_knowledge(data: Any) -> CodeKnowledge:
    """Agent-2 出口门禁：原始 dict → ``CodeKnowledge``，失败则抛错。"""
    ok, result = safe_validate_code_knowledge(data)
    if not ok:
        raise ArtifactValidationError("code-knowledge", str(result))
    assert isinstance(result, CodeKnowledge)
    return result


def require_analysis_report(data: Any) -> AnalysisReport:
    """Agent-3 出口门禁：原始 dict → ``AnalysisReport``，失败则抛错。"""
    ok, result = safe_validate_analysis_report(data)
    if not ok:
        raise ArtifactValidationError("analysis-report", str(result))
    assert isinstance(result, AnalysisReport)
    return result
