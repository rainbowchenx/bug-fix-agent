from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


class CreateRunOptions(BaseModel):
    analyzeMode: Optional[Literal["heuristic", "sdk"]] = None
    cartographyMode: Optional[Literal["heuristic", "sdk"]] = None
    skipAgent2: bool = False
    skipAgent3: bool = False
    openMr: bool = False


class CreateRunRequest(BaseModel):
    """Agent-2→3 run request. Agent-1 defect-batch is prepared outside LangGraph."""

    workDir: str = Field(min_length=1)
    productLine: str = Field(min_length=1)
    defectBatch: Union[str, dict[str, Any]] = Field(
        description="Path to defect-batch.json, or inline defect-batch object"
    )
    posture: Literal["alpha", "beta"] = "beta"
    options: CreateRunOptions = Field(default_factory=CreateRunOptions)


class CreateRunResponse(BaseModel):
    runId: str
    workDir: str


class RunArtifactsRef(BaseModel):
    defectBatchPath: Optional[str] = None
    codeKnowledgePath: Optional[str] = None
    analysisReportPath: Optional[str] = None


class RunStatusResponse(BaseModel):
    runId: str
    workDir: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: Optional[str] = None
    error: Optional[str] = None
    funnel: Optional[dict[str, int]] = None
    profile: Optional[str] = None
    summary: Optional[dict[str, Any]] = None
    artifacts: RunArtifactsRef = Field(default_factory=RunArtifactsRef)
    schemaVersion: str = "3-agent-0.1"


class HealthResponse(BaseModel):
    ok: bool = True
    service: str = "bugfix-agent"
    version: str
