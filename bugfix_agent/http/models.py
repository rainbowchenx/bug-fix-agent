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
    """Three-agent run request (Dify-oriented async shell)."""

    workDir: str = Field(min_length=1)
    productLine: str = Field(min_length=1)
    source: Union[str, dict[str, Any], list[Any]] = Field(
        description="Path to CSV/JSON, or inline raw-defects payload"
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
