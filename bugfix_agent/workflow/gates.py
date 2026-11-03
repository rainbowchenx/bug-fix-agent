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
    def __init__(self, artifact: str, detail: str):
        self.artifact = artifact
        self.detail = detail
        super().__init__(f"{artifact} validation failed: {detail}")


def require_defect_batch(data: Any) -> DefectBatch:
    ok, result = safe_validate_defect_batch(data)
    if not ok:
        raise ArtifactValidationError("defect-batch", str(result))
    assert isinstance(result, DefectBatch)
    return result


def require_code_knowledge(data: Any) -> CodeKnowledge:
    ok, result = safe_validate_code_knowledge(data)
    if not ok:
        raise ArtifactValidationError("code-knowledge", str(result))
    assert isinstance(result, CodeKnowledge)
    return result


def require_analysis_report(data: Any) -> AnalysisReport:
    ok, result = safe_validate_analysis_report(data)
    if not ok:
        raise ArtifactValidationError("analysis-report", str(result))
    assert isinstance(result, AnalysisReport)
    return result
