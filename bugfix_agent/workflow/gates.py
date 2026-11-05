"""Pydantic hard gates between agents.

Each ``require_*`` wraps the contract ``safe_validate_*`` helpers and raises
``ArtifactValidationError`` on schema failure. Parent graph validate_* nodes
catch that error, set ``ok=False`` / ``stage`` / ``error``, and ``Command(goto=END)``.

Agents must not import each other's internals — only these artifact types cross
the boundary (defect-batch → code-knowledge → analysis-report).
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
    """Raised when a cross-agent artifact fails schema validation."""

    def __init__(self, artifact: str, detail: str):
        self.artifact = artifact
        self.detail = detail
        super().__init__(f"{artifact} validation failed: {detail}")


def require_defect_batch(data: Any) -> DefectBatch:
    """Gate after Agent-1: raw dict → ``DefectBatch`` or raise."""
    ok, result = safe_validate_defect_batch(data)
    if not ok:
        raise ArtifactValidationError("defect-batch", str(result))
    assert isinstance(result, DefectBatch)
    return result


def require_code_knowledge(data: Any) -> CodeKnowledge:
    """Gate after Agent-2: raw dict → ``CodeKnowledge`` or raise."""
    ok, result = safe_validate_code_knowledge(data)
    if not ok:
        raise ArtifactValidationError("code-knowledge", str(result))
    assert isinstance(result, CodeKnowledge)
    return result


def require_analysis_report(data: Any) -> AnalysisReport:
    """Gate after Agent-3: raw dict → ``AnalysisReport`` or raise."""
    ok, result = safe_validate_analysis_report(data)
    if not ok:
        raise ArtifactValidationError("analysis-report", str(result))
    assert isinstance(result, AnalysisReport)
    return result
