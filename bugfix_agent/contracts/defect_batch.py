from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from bugfix_agent.contracts.common import CONTRACT_SCHEMA_VERSION, Confidence

DEFECT_BATCH_SCHEMA_VERSION = CONTRACT_SCHEMA_VERSION

Pool = Literal[
    "strict",
    "locatable_only",
    "needs_info",
    "hard_reject",
    "security",
    "excluded",
]
ExpectQuality = Literal["explicit", "inferred", "ambiguous", "absent"]
Intent = Literal[
    "ui_layout",
    "i18n",
    "logic",
    "data_wrong",
    "perf",
    "compat",
    "config",
    "security_scan",
    "crash",
    "unclear",
]
IntentSource = Literal["ai", "heuristic", "field_fallback", "unclear"]
Posture = Literal["alpha", "beta"]


class RawDefect(BaseModel):
    model_config = ConfigDict(extra="ignore")

    defectId: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    status: Optional[str] = None
    flowStatus: Optional[str] = None
    testModule: Optional[str] = None
    fieldType: Optional[str] = None
    severity: Optional[str] = None
    createdAt: Optional[str] = None
    duplicateOf: Optional[str] = None
    productLine: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class RawDefectsFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemaVersion: Optional[str] = None
    productLine: Optional[str] = None
    posture: Optional[Posture] = None
    defects: list[RawDefect]


class BatchTicket(BaseModel):
    model_config = ConfigDict(extra="ignore")

    defectId: str
    title: str
    pool: Pool
    clusterId: Optional[str] = None
    testModule: Optional[str] = None
    titleTag: Optional[str] = None
    intent: Optional[Intent] = None
    intentSource: Optional[IntentSource] = None
    intentConfidence: Optional[Confidence] = None
    intentRationale: Optional[str] = None
    fieldType: Optional[str] = None
    expectQuality: ExpectQuality
    reasonCode: Optional[str] = None
    reasonDetail: Optional[str] = None
    observed: Optional[str] = None
    expected: Optional[str] = None
    steps: Optional[str] = None
    status: Optional[str] = None
    severity: Optional[str] = None
    createdAt: Optional[str] = None
    duplicate: Optional[bool] = None
    semanticFree: Optional[bool] = None
    priority: Optional[float] = None


class BatchCluster(BaseModel):
    model_config = ConfigDict(extra="ignore")

    clusterId: str
    testModule: str
    titleTag: str
    intent: Intent
    size: int = Field(ge=0)
    openCount: int = Field(ge=0)
    oversized: Optional[bool] = None
    priority: Optional[float] = None
    defectIds: list[str]


class DefectBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemaVersion: str
    productLine: str
    posture: Posture = "beta"
    generatedAt: str
    funnel: dict[str, int]
    clusters: list[BatchCluster]
    tickets: list[BatchTicket]


def validate_defect_batch(data: Any) -> DefectBatch:
    return DefectBatch.model_validate(data)


def safe_validate_defect_batch(data: Any) -> tuple[bool, DefectBatch | str]:
    try:
        return True, DefectBatch.model_validate(data)
    except Exception as e:  # noqa: BLE001
        return False, str(e)
